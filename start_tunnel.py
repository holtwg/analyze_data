#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台一键启动：竞彩分析 Web 服务 + Cloudflare 临时隧道。

本脚本取代了原先 Windows 专用的 ``start_tunnel.bat`` / ``start_tunnel.ps1``，
在 **Windows / macOS / Linux** 上均可运行，让项目真正跨平台。

用法::

    python3 start_tunnel.py            # 默认端口 8000
    python3 start_tunnel.py 9000       # 指定端口
    python3 start_tunnel.py --no-tunnel  # 只启动本地 Web，不建公网隧道

行为：
    1. 在当前端口（默认 8000，占用则自动顺延）启动 web_app.py。
    2. 等待 /healthz 就绪（强制用 127.0.0.1，避开 IPv6 解析问题）。
    3. 启动 cloudflared 临时隧道，抓取形如 https://xxx.trycloudflare.com 的公网地址。
    4. 地址写入 tunnel_url.txt 并打印（macOS 下尝试复制到剪贴板）。
    5. Ctrl+C 退出时一并清理 Web 与隧道子进程。

cloudflared 二进制：
    - 优先用 PATH 里的 ``cloudflared``（macOS 用 homebrew 安装后就有）。
    - 否则用本目录已下载的 ``cloudflared`` / ``cloudflared.exe``。
    - 都没有则按当前系统/架构自动从 GitHub Releases 下载（macOS 会自动移除
      Gatekeeper 隔离属性，避免“无法验证开发者”）。
"""
from __future__ import annotations

import argparse
import io
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _c(text: str) -> str:
    """尽量给终端输出加颜色（不支持则原样返回）。"""
    if sys.stdout.isatty():
        return f"\033[36m{text}\033[0m"  # cyan
    return text


def _green(text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[32m{text}\033[0m"
    return text


def _red(text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[31m{text}\033[0m"
    return text


def _yellow(text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[33m{text}\033[0m"
    return text


def find_python() -> str | None:
    """返回可用的、且装有 httpx 的 Python 解释器路径。"""
    candidates = [sys.executable, "python3", "python", "py"]
    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            r = subprocess.run(
                [c, "-c", "import httpx"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            if r.returncode == 0:
                return c
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def get_free_port(start: int = 8000) -> int:
    """找一个未被占用的本地端口。"""
    import socket

    for p in range(start, start + 100):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            s.close()
    return start


def detect_platform() -> tuple[str, str]:
    """返回 (system, arch)，system ∈ {windows, darwin, linux}。"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = "amd64"  # 兜底
    if system not in ("windows", "darwin", "linux"):
        system = "linux"
    return system, arch


def find_cloudflared(system: str, arch: str) -> str | None:
    """优先 PATH，其次本目录已下载的二进制。"""
    p = shutil.which("cloudflared")
    if p:
        return p
    names = ["cloudflared.exe"] if system == "windows" else ["cloudflared"]
    for name in names:
        fp = os.path.join(ROOT, name)
        if os.path.isfile(fp) and os.access(fp, os.X_OK):
            return fp
    return None


def download_cloudflared(system: str, arch: str) -> str:
    """从 GitHub Releases 下载适配当前平台的 cloudflared 到本目录。"""
    base = "https://github.com/cloudflare/cloudflared/releases/latest/download"
    if system == "darwin":
        url = f"{base}/cloudflared-darwin-{arch}.tgz"
        dest = os.path.join(ROOT, "cloudflared")
    elif system == "windows":
        url = f"{base}/cloudflared-windows-{arch}.exe"
        dest = os.path.join(ROOT, "cloudflared.exe")
    else:  # linux
        url = f"{base}/cloudflared-linux-{arch}"
        dest = os.path.join(ROOT, "cloudflared")

    print(_c(f"[*] 未找到 cloudflared，正在下载（{system}/{arch}）："))
    print(f"    {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()

    if url.endswith(".tgz"):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            member = next(
                (m for m in tf.getmembers() if os.path.basename(m.name) == "cloudflared"),
                None,
            )
            if member is None:
                raise RuntimeError("下载的压缩包内未找到 cloudflared 二进制")
            extracted = tf.extractfile(member).read()
        with open(dest, "wb") as f:
            f.write(extracted)
    elif data[:2] == b"\x1f\x8b":  # gzip 压缩的原始二进制
        import gzip

        with open(dest, "wb") as f:
            f.write(gzip.decompress(data))
    else:
        with open(dest, "wb") as f:
            f.write(data)

    os.chmod(dest, 0o755)

    if system == "darwin":
        # macOS Gatekeeper 会给下载文件打隔离标记，导致“无法验证开发者”。
        # 移除隔离属性即可正常运行（无需关闭 SIP）。
        try:
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", dest],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            pass
        print(_yellow("    macOS 已尝试移除隔离属性；若仍提示“无法验证开发者”，"))
        print(_yellow("    请在“系统设置 → 隐私与安全性”中点“仍要打开”，或运行："))
        print(_yellow(f"    xattr -dr com.apple.quarantine \"{dest}\""))

    return dest


def copy_to_clipboard(text: str) -> None:
    """跨平台复制到剪贴板（失败静默忽略）。"""
    system, _ = detect_platform()
    try:
        if system == "darwin":
            p = subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
        elif system == "windows":
            p = subprocess.run(["clip"], input=text.encode("utf-8"), check=False)
        else:  # linux
            p = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                check=False,
            )
        if p.returncode != 0:
            # 不影响主流程
            pass
    except (OSError, subprocess.SubprocessError):
        pass


def wait_for_healthz(port: int, timeout: int = 40) -> bool:
    import http.client

    url = f"127.0.0.1:{port}/healthz"
    for _ in range(timeout * 2):
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/healthz")
            r = conn.getresponse()
            if r.status == 200:
                conn.close()
                return True
            conn.close()
        except OSError:
            pass
        time.sleep(0.5)
    return False


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="竞彩分析 Web + Cloudflare 隧道一键启动")
    parser.add_argument("port", nargs="?", type=int, default=8000, help="Web 服务端口（默认 8000）")
    parser.add_argument("--no-tunnel", action="store_true", help="只启动本地 Web，不建立公网隧道")
    args = parser.parse_args()

    print(_c("=== 竞彩赔率分析 · 跨平台启动器 ==="))

    py = find_python()
    if not py:
        print(_red("[!] 未找到已安装 httpx 的 Python。"))
        print(_yellow("    请先安装依赖：python3 -m pip install -r requirements.txt"))
        return 1
    print(_c(f"[*] 使用 Python：{py}"))

    system, arch = detect_platform()
    print(_c(f"[*] 平台：{system} / {arch}"))

    port = get_free_port(args.port)
    if port != args.port:
        print(_yellow(f"[*] 端口 {args.port} 被占用，自动改用 {port}"))

    # 启动 Web 服务（继承 stdout/stderr，便于看日志）
    print(_c(f"[*] 正在启动网页服务：{py} web_app.py {port} ..."))
    web_proc = subprocess.Popen([py, "web_app.py", str(port)], cwd=ROOT)
    if not wait_for_healthz(port):
        print(_red("[!] 网页服务启动失败或 /healthz 未响应。"))
        print(_yellow("    请手动运行：python3 web_app.py 并查看输出。"))
        web_proc.terminate()
        return 1
    print(_green(f"[*] 网页服务已就绪：http://localhost:{port}"))

    if args.no_tunnel:
        print(_green(f"[*] 本地模式：浏览器打开 http://localhost:{port} 即可使用。"))
        print(_yellow("[*] 按 Ctrl+C 停止。"))
        try:
            web_proc.wait()
        except KeyboardInterrupt:
            pass
        web_proc.terminate()
        return 0

    # 准备 cloudflared
    cf = find_cloudflared(system, arch)
    if not cf:
        try:
            cf = download_cloudflared(system, arch)
        except Exception as exc:  # noqa: BLE001
            print(_red(f"[!] 下载 cloudflared 失败：{exc}"))
            print(_yellow("    可手动下载后放到本目录，或用 homebrew 安装：brew install cloudflared"))
            web_proc.terminate()
            return 1
    print(_c(f"[*] 使用 cloudflared：{cf}"))
    print(_c("[*] 正在启动 Cloudflare 隧道（连接公网，请稍候）..."))

    cf_proc = subprocess.Popen(
        [cf, "tunnel", "--url", f"http://127.0.0.1:{port}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # 后台读取 cloudflared 输出，抓取公网地址
    found = {"url": None}
    buf: list[str] = []

    def _reader(stream):
        for raw in iter(stream.readline, b""):
            text = raw.decode("utf-8", "replace")
            buf.append(text)
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
            if m and not found["url"]:
                found["url"] = m.group(0)

    t = threading.Thread(target=_reader, args=(cf_proc.stdout,), daemon=True)
    t.start()

    for _ in range(60):
        if found["url"]:
            break
        if cf_proc.poll() is not None:
            break
        time.sleep(1)

    if not found["url"]:
        print(_red("[!] 60 秒内未能获取隧道地址，请检查网络能否连接 cloudflare。"))
        print(_yellow("    最近输出："))
        for line in buf[-15:]:
            print("   ", line.rstrip())
        cf_proc.terminate()
        web_proc.terminate()
        return 1

    tunnel_url = found["url"]
    url_file = os.path.join(ROOT, "tunnel_url.txt")
    with open(url_file, "w", encoding="ascii") as f:
        f.write(tunnel_url + "\n")
    copy_to_clipboard(tunnel_url)

    print()
    print(_green("============================================================"))
    print(_green("   手机访问地址（已尝试复制到剪贴板）："))
    print()
    print(_green(f"   {tunnel_url}"))
    print()
    print(_green("   同时已保存到本目录 tunnel_url.txt，可直接打开复制。"))
    print(_green("============================================================"))
    print()
    print(_c("[*] 隧道运行中。保持此窗口开启；手机用上面的地址即可访问。"))
    print(_c("[*] 按 Ctrl+C 停止网页与隧道。"))

    # 注册清理
    stop = {"done": False}

    def _cleanup(signum=None, frame=None):
        if stop["done"]:
            return
        stop["done"] = True
        print(_yellow("\n[*] 正在停止网页与隧道..."))
        try:
            cf_proc.terminate()
        except OSError:
            pass
        try:
            web_proc.terminate()
        except OSError:
            pass

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        while True:
            if cf_proc.poll() is not None:
                print(_yellow("[!] cloudflared 进程已退出，隧道断开。"))
                break
            if web_proc.poll() is not None:
                print(_yellow("[!] 网页服务进程已退出。"))
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()

    print(_yellow("[*] 已停止网页与隧道。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
