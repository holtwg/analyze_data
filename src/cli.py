"""命令行入口（Typer）。

示例：
    python -m src.cli analyze 3000426
    python -m src.cli analyze --url https://op1.titan007.com/oddslist/3000426.htm
    python -m src.cli first            # 分析当日竞彩列表第一场
    python -m src.cli list             # 列出当日竞彩赛事
    python -m src.cli analyze 3000426 --json
"""
from __future__ import annotations

import json
import locale
import sys

# 输出编码匹配终端（GBK/UTF-8 自适应），避免中文乱码。
try:
    _enc = locale.getpreferredencoding(False) or "utf-8"
    sys.stdout.reconfigure(encoding=_enc)
    sys.stderr.reconfigure(encoding=_enc)
except Exception:
    pass

import typer

from .analysis import analyze, format_report
from .odds import fetch_match_odds
from .schedule import first_match, list_matches, match_id_from_url

app = typer.Typer(help="足球百家欧指 → 胜平负概率与体彩方向分析", add_completion=False)


@app.command("analyze")
def analyze_cmd(
    match_id: str = typer.Argument("", help="比赛 ScheduleID，如 3000426"),
    url: str = typer.Option("", "--url", "-u", help="oddslist 完整 URL，自动提取 ID"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """分析单场比赛的胜平负概率与体彩方向。"""
    mid = match_id
    if not mid and url:
        mid = match_id_from_url(url)
    if not mid:
        typer.echo("请提供 match_id 或 --url", err=True)
        raise typer.Exit(code=1)

    match = fetch_match_odds(mid)
    result = analyze(match)
    if as_json:
        typer.echo(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        typer.echo(format_report(result))


@app.command("first")
def first_cmd(as_json: bool = typer.Option(False, "--json")) -> None:
    """分析当日竞彩列表中的第一场比赛。"""
    m = first_match()
    if m is None:
        typer.echo("未能获取竞彩赛事列表", err=True)
        raise typer.Exit(code=1)
    match = fetch_match_odds(str(m["match_id"]))
    result = analyze(match)
    if as_json:
        typer.echo(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        typer.echo(format_report(result))


@app.command("list")
def list_cmd() -> None:
    """列出当日竞彩足球赛事（ScheduleID + 竞彩胜平负赔率）。"""
    matches = list_matches()
    if not matches:
        typer.echo("无赛事数据")
        return
    typer.echo(f"共 {len(matches)} 场：")
    for i, m in enumerate(matches[:30], 1):
        h, d, a = m["lottery_home"], m["lottery_draw"], m["lottery_away"]
        odds = f"主{h} 平{d} 客{a}" if h else "（未开售）"
        typer.echo(f"  {i:>2}. ID={m['match_id']}  竞彩 {odds}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
