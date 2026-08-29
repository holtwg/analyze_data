"""直接运行入口：``python main.py``。

设计目标：核心分析路径**零额外依赖**（仅需 httpx），不强制安装 typer，
因此在任意 Python 环境（含 PyCharm 默认解释器）都能直接跑。

用法：
    python main.py                 # 分析当日竞彩第一场（双击即可看结果）
    python main.py 3000426         # 分析指定比赛 ID
    python main.py <oddslist链接>  # 从链接自动提取 ID 并分析
    python main.py list            # 列出当日竞彩赛事（本地实现，无需 typer）
    python main.py first           # 等价于无参数（当日第一场）
    python main.py 3000426 --json  # JSON 输出（便于二次开发）
    python main.py analyze 3000426 # 转发给 Typer CLI（需 pip install typer；支持 --url）
    python main.py gui             # 图形弹窗输入（如 周六015）

说明：``list`` / ``first`` / 单个 ID 或 URL 均不依赖 typer；只有显式使用
``analyze`` 子命令（含 --url）时才延迟导入 typer，缺失会给出友好提示。
"""
from __future__ import annotations

import json
import locale
import sys

# 让 stdout/stderr 编码匹配终端：中文 Windows 终端多为 GBK(cp936)，
# 强行 UTF-8 会导致「UTF-8 字节被 GBK 终端误读」的乱码。
# 取系统首选编码（GBK 终端→GBK，UTF-8 终端→UTF-8），与终端保持一致即可正常显示。
try:
    _enc = locale.getpreferredencoding(False) or "utf-8"
    sys.stdout.reconfigure(encoding=_enc)
    sys.stderr.reconfigure(encoding=_enc)
except Exception:
    pass

from src.analysis import analyze, format_report
from src.odds import fetch_match_odds
from src.schedule import first_match, list_matches, match_id_from_url, resolve_match_ref
from src.nba_analysis import analyze_nba, format_nba_report
from src.nba_odds import fetch_nba_match_odds
from src.nba_spread_analysis import analyze_nba_spread, format_nba_spread_report
from src.nba_spread_odds import fetch_nba_spread
from src.nba_history import fetch_nba_history_records, format_nba_history_report
from src.nba_schedule import (
    first_nba_match,
    list_nba_matches,
    match_id_from_nba_url,
    resolve_nba_ref,
)


def _print_match(mid: str, as_json: bool = False) -> None:
    """抓取并分析单场（足球），按文本或 JSON 输出。"""
    match = fetch_match_odds(mid)
    result = analyze(match)
    if as_json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        print(format_report(result))


def _nba_history_record(mid: str, date_str: str | None):
    """尝试从历史汇总接口取该场记录（兜底用）。失败返回 None。"""
    if not date_str:
        return None
    try:
        recs = fetch_nba_history_records(date_str)
    except Exception:
        return None
    return recs.get(mid)


def _print_nba_match(mid: str, as_json: bool = False, target_date: str | None = None) -> bool:
    """抓取并分析单场（篮球胜负），按文本或 JSON 输出。

    实时百家欧指 JS 失败（已结束历史比赛常返回 502）时，若已知目标日期，
    自动回退到竞彩历史汇总接口做赛果对照。
    返回 True 表示走了历史兜底（避免 both 模式重复打印）。
    """
    try:
        match = fetch_nba_match_odds(mid)
        result = analyze_nba(match)
    except Exception:
        rec = _nba_history_record(mid, target_date)
        if rec is not None:
            print(format_nba_history_report(rec))
            return True
        print(f"分析失败（比赛 {mid}）：实时百家欧指接口不可达且无可回退的历史数据。")
        return False
    if as_json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        print(format_nba_report(result))
    return False


def _print_nba_spread(mid: str, as_json: bool = False, target_date: str | None = None) -> bool:
    """抓取并分析单场（篮球让分/盘口），按文本或 JSON 输出。

    让分页对历史比赛常返回 502，若已知目标日期则回退到历史汇总接口。
    """
    try:
        match = fetch_nba_spread(mid)
        result = analyze_nba_spread(match)
    except Exception:
        rec = _nba_history_record(mid, target_date)
        if rec is not None:
            print(format_nba_history_report(rec))
            return True
        print(f"分析失败（比赛 {mid}）：实时让分接口不可达且无可回退的历史数据。")
        return False
    if as_json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        print(format_nba_spread_report(result))
    return False


def _run_nba(args: list[str], as_json: bool = False) -> None:
    """处理 ``python main.py nba ...`` 子命令。

    模式：默认「胜负」；``--spread`` 仅让分；``--both`` 胜负+让分。
    """
    mode = "ml"  # moneyline 胜负
    rest = []
    for a in args:
        if a == "--spread":
            mode = "spread"
        elif a == "--both":
            mode = "both"
        else:
            rest.append(a)
    args = rest

    if not args:
        m = first_nba_match()
        if m is None:
            print("未能获取竞彩篮球赛事列表，请检查网络或站点可用性。")
            return
        mid = str(m["match_id"])
    else:
        nhead = args[0]
        if nhead == "list":
            if len(args) > 1:
                date_arg = args[1]
                try:
                    from src.nba_schedule import list_nba_matches_by_date
                    matches = list_nba_matches_by_date(date_arg)
                except Exception as exc:
                    print(f"查询 {date_arg} 篮球赛事失败：{exc}")
                    return
                if not matches:
                    print(f"无竞彩篮球赛事数据（{date_arg}）")
                    return
                print(f"共 {len(matches)} 场（竞彩篮球-{date_arg}）：")
                for mm in matches[:30]:
                    tag = f"[{mm['label']}] " if mm.get("label") else ""
                    print(f"  {tag}ID={mm['match_id']}")
                return
            matches = list_nba_matches()
            if not matches:
                print("无篮球赛事数据（今日）")
                return
            print(f"共 {len(matches)} 场（竞彩篮球-今日；场次号按列表顺序从 301 起推断）：")
            for mm in matches[:30]:
                tag = f"[{mm['label']}] " if mm.get("label") else ""
                teams = f"{mm.get('home', '')} VS {mm.get('away', '')}" if mm.get("home") else ""
                print(f"  {tag}ID={mm['match_id']}  {teams}")
            return

        if nhead == "gui":
            try:
                from src.gui import show_nba_gui
            except ImportError as exc:
                print(f"无法加载 GUI：{exc}\n请确认当前 Python 包含 tkinter，或使用命令行：python main.py nba 周六301")
                return
            show_nba_gui()
            return

        if nhead.startswith("http"):
            mid = match_id_from_nba_url(nhead)
            print(f"解析：NBA 胜负 oddslist 链接 -> ID {mid}")
            target_date = None
        else:
            resolved = resolve_nba_ref(nhead)
            mid = str(resolved["match_id"])
            target_date = resolved.get("target_date")
            ctx = f"解析：{resolved['source']} -> ID {mid}"
            if resolved.get("label"):
                ctx += f"  （{resolved['label']}）"
            print(ctx)
            if resolved.get("note"):
                print(f"提示：{resolved['note']}")

    if mode == "spread":
        _print_nba_spread(mid, as_json, target_date)
    elif mode == "both":
        used_hist = _print_nba_match(mid, as_json, target_date)
        if not used_hist:
            print()
            _print_nba_spread(mid, as_json, target_date)
    else:
        _print_nba_match(mid, as_json, target_date)


def main() -> None:
    argv = sys.argv[1:]
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]

    if not argv:
        # 默认：当日第一场
        m = first_match()
        if m is None:
            print("未能获取竞彩赛事列表，请检查网络或站点可用性。")
            return
        _print_match(str(m["match_id"]), as_json)
        return

    head = argv[0]

    if head == "nba":
        _run_nba(argv[1:], as_json)
        return

    if head == "list":
        date_arg = argv[1] if len(argv) > 1 else None
        matches = list_matches(date_arg)
        if not matches:
            print("无赛事数据" + (f"（{date_arg}）" if date_arg else ""))
            return
        print(f"共 {len(matches)} 场" + (f"（{date_arg}）" if date_arg else "（当日）") + "：")
        for i, mm in enumerate(matches[:30], 1):
            h, d, a = mm["lottery_home"], mm["lottery_draw"], mm["lottery_away"]
            odds = f"主{h} 平{d} 客{a}" if h else ""
            label = mm.get("label")
            tag = f"[{label}] " if label else f"#{i:03d} "
            print(f"  {tag}ID={mm['match_id']}{('  竞彩 ' + odds) if odds else ''}")
        return

    if head == "first":
        m = first_match()
        if m is None:
            print("未能获取竞彩赛事列表，请检查网络或站点可用性。")
            return
        _print_match(str(m["match_id"]), as_json)
        return

    if head == "gui":
        # 图形弹窗入口
        try:
            from src.gui import show_gui
        except ImportError as exc:
            print(f"无法加载 GUI：{exc}\n请确认当前 Python 包含 tkinter，或使用命令行版本：python main.py 周六015")
            return
        show_gui()
        return

    if head == "analyze":
        # 转发给 Typer CLI（支持 --url 等丰富选项）
        try:
            from src.cli import app
        except ImportError:
            print("analyze 子命令依赖 typer，请先安装：pip install typer")
            return
        app()
        return

    # 其余情况：oddslist 链接 / 周六015 / 周五001 / 015 / 3000426 等
    if head.startswith("http"):
        mid = match_id_from_url(head)
        print(f"解析：oddslist 链接 -> ID {mid}")
    else:
        resolved = resolve_match_ref(head)
        mid = str(resolved["match_id"])
        ctx = f"解析：{resolved['source']} -> ID {mid}"
        if resolved.get("label"):
            ctx += f"  （{resolved['label']}"
            if resolved.get("target_date"):
                ctx += f"，{resolved['target_date']}"
            ctx += "）"
        print(ctx)
        if resolved.get("note"):
            print(f"提示：{resolved['note']}")
    _print_match(mid, as_json)


if __name__ == "__main__":
    main()
