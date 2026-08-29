"""图形化弹窗入口（tkinter）。

支持两种运动 + 篮球多模式：
- 足球：``python main.py gui`` / ``python -m src.gui``
- 篮球：``python main.py nba gui``（胜负 / 让分 / 两者）

弹窗支持「周X序号 / 序号 / 比赛ID」输入；篮球历史场次（如 周五307）同样可用，
用于往期赛事分析与数据验证。
"""
from __future__ import annotations

import locale
import sys
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# 与 main.py 保持一致的终端编码自适应，避免中文乱码
try:
    _enc = locale.getpreferredencoding(False) or "utf-8"
    sys.stdout.reconfigure(encoding=_enc)
    sys.stderr.reconfigure(encoding=_enc)
except Exception:
    pass


def _analyze(entry: tk.Entry, root: tk.Tk, *, resolve_fn, report_fn, example: str) -> None:
    """读取输入、解析场次、生成报告并在新窗口展示。"""
    raw = entry.get().strip()
    if not raw:
        messagebox.showwarning("提示", f"请先输入场次，例如：{example}")
        return

    try:
        resolved = resolve_fn(raw)
    except Exception as exc:
        messagebox.showerror("输入解析失败", str(exc))
        return

    match_id = str(resolved["match_id"])
    try:
        report = report_fn(match_id)
    except Exception as exc:
        messagebox.showerror("分析失败", f"比赛 {match_id} 分析失败：\n{exc}")
        return

    top = tk.Toplevel(root)
    top.title(f"分析结果 - {match_id}")
    top.geometry("760x560")

    text = scrolledtext.ScrolledText(top, wrap=tk.WORD, font=("Microsoft YaHei", 10))
    text.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

    header_parts = [f"输入：{raw}", f"解析：{resolved['source']} -> ID {match_id}"]
    if resolved.get("label"):
        label_line = f"场次：{resolved['label']}"
        if resolved.get("target_date"):
            label_line += f"（{resolved['target_date']}）"
        header_parts.append(label_line)
    note = resolved.get("note")
    if note:
        header_parts.append(f"提示：{note}")
    text.insert(tk.END, "  |  ".join(header_parts) + "\n")
    text.insert(tk.END, "=" * 56 + "\n\n")
    text.insert(tk.END, report)
    text.insert(tk.END, "\n\n【验证提示】以上为赛前赔率概率（市场共识/体彩价值）。\n")
    text.insert(tk.END, "若要验证分析可靠性，请对照该场实际比分：\n")
    text.insert(tk.END, "开赛时间见上方，可在竞彩官网或比分网查询赛果后自行比对。")
    text.configure(state=tk.DISABLED)

    tk.Button(top, text="关闭", command=top.destroy).pack(pady=5)


def _launch(*, resolve_fn, report_fn, title: str, example: str, verify_note: str) -> None:
    """启动输入弹窗（通用，单模式）。"""
    try:
        import tkinter  # noqa: F401
    except ImportError as exc:
        messagebox.showerror(
            "缺少 tkinter",
            "当前 Python 环境未安装 tkinter，无法显示弹窗。\n"
            f"请使用命令行版本，例如：\n  {verify_note}\n"
            f"原始错误：{exc}",
        )
        return

    root = tk.Tk()
    root.title(title)
    root.geometry("520x180")
    root.resizable(False, False)

    tk.Label(root, text=f"输入场次（如 {example}）：", font=("Microsoft YaHei", 11)).pack(
        padx=15, pady=(15, 5)
    )

    entry = tk.Entry(root, width=45, font=("Microsoft YaHei", 12))
    entry.pack(padx=15, pady=5)
    entry.focus()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=15)

    tk.Button(
        btn_frame, text="开始分析", width=12,
        command=lambda: _analyze(entry, root, resolve_fn=resolve_fn, report_fn=report_fn,
                                 example=example),
        font=("Microsoft YaHei", 10),
    ).pack(side=tk.LEFT, padx=8)
    tk.Button(btn_frame, text="退出", width=12, command=root.destroy,
              font=("Microsoft YaHei", 10)).pack(side=tk.LEFT, padx=8)

    entry.bind("<Return>", lambda _e: _analyze(entry, root, resolve_fn=resolve_fn,
                                               report_fn=report_fn, example=example))
    root.mainloop()


def _launch_nba(*, resolve_fn, title: str, example: str, verify_note: str) -> None:
    """篮球弹窗（含模式切换：胜负 / 让分 / 两者）。"""
    try:
        import tkinter  # noqa: F401
    except ImportError as exc:
        messagebox.showerror(
            "缺少 tkinter",
            "当前 Python 环境未安装 tkinter，无法显示弹窗。\n"
            f"请使用命令行版本，例如：\n  {verify_note}\n"
            f"原始错误：{exc}",
        )
        return

    from .nba_analysis import analyze_nba, format_nba_report
    from .nba_odds import fetch_nba_match_odds
    from .nba_spread_analysis import analyze_nba_spread, format_nba_spread_report
    from .nba_spread_odds import fetch_nba_spread

    def report_fn(match_id: str) -> str:
        mode = mode_var.get()
        parts: list[str] = []
        if mode in ("胜负", "两者"):
            try:
                m = fetch_nba_match_odds(match_id)
                parts.append(format_nba_report(analyze_nba(m)))
            except Exception as exc:
                parts.append(f"[胜负分析失败] {exc}")
        if mode in ("让分", "两者"):
            try:
                s = fetch_nba_spread(match_id)
                parts.append(format_nba_spread_report(analyze_nba_spread(s)))
            except Exception as exc:
                parts.append(f"[让分分析失败] {exc}")
        return "\n\n".join(parts)

    root = tk.Tk()
    root.title(title)
    root.geometry("560x210")
    root.resizable(False, False)

    tk.Label(root, text=f"输入场次（如 {example}）：", font=("Microsoft YaHei", 11)).pack(
        padx=15, pady=(15, 5)
    )
    entry = tk.Entry(root, width=48, font=("Microsoft YaHei", 12))
    entry.pack(padx=15, pady=5)
    entry.focus()

    ctrl = tk.Frame(root)
    ctrl.pack(pady=4)
    tk.Label(ctrl, text="分析模式：", font=("Microsoft YaHei", 10)).pack(side=tk.LEFT)
    mode_var = tk.StringVar(value="两者")
    ttk.Combobox(
        ctrl, textvariable=mode_var, width=10, state="readonly",
        values=["胜负", "让分", "两者"],
    ).pack(side=tk.LEFT, padx=5)

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=12)
    tk.Button(
        btn_frame, text="开始分析", width=12,
        command=lambda: _analyze(entry, root, resolve_fn=resolve_fn, report_fn=report_fn,
                                 example=example),
        font=("Microsoft YaHei", 10),
    ).pack(side=tk.LEFT, padx=8)
    tk.Button(btn_frame, text="退出", width=12, command=root.destroy,
              font=("Microsoft YaHei", 10)).pack(side=tk.LEFT, padx=8)

    entry.bind("<Return>", lambda _e: _analyze(entry, root, resolve_fn=resolve_fn,
                                               report_fn=report_fn, example=example))
    root.mainloop()


# --------------------------------------------------------------------------
# 足球模式
# --------------------------------------------------------------------------
def show_gui() -> None:
    """启动足球分析弹窗。"""
    from .analysis import analyze, format_report
    from .odds import fetch_match_odds
    from .schedule import resolve_match_ref

    def report_fn(match_id: str) -> str:
        match = fetch_match_odds(match_id)
        return format_report(analyze(match))

    _launch(
        resolve_fn=resolve_match_ref,
        report_fn=report_fn,
        title="体彩足球场次分析",
        example="周六015",
        verify_note="python main.py 周六015",
    )


# --------------------------------------------------------------------------
# 篮球模式
# --------------------------------------------------------------------------
def show_nba_gui() -> None:
    """启动篮球分析弹窗（胜负 / 让分 / 两者）。"""
    from .nba_schedule import resolve_nba_ref

    _launch_nba(
        resolve_fn=resolve_nba_ref,
        title="竞彩篮球分析（胜负/让分）",
        example="周六301",
        verify_note="python main.py nba 周六301",
    )


if __name__ == "__main__":
    show_gui()
