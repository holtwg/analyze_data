"""历史篮球赛事「赛果 + 竞彩终盘」解析（实时接口的兜底数据源）。

当 titan007 的实时百家欧指 JS（``data1x2/{id}.js``）与让分 HTML 页
（``AsianOdds_n.aspx``）对已结束比赛返回 502 时，从竞彩历史汇总接口
``JcResult.aspx?d=YYYY-MM-DD&st=2`` 提取该场「竞彩终盘」与「实际赛果」做对照验证。

重要限制：该接口仅给出**竞彩官* 单家**终盘赔率（且部分场次胜负赔率字段为空），
不含百家共识，故无法做完整的概率/价值分析，只能用于赛果与终盘对照。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .client import fetch_text
from .config import NBA_HISTORY_URL_TMPL

_JC_REFERER = "https://jc.titan007.com/nba/index.aspx"


@dataclass(slots=True)
class NbaHistoryRecord:
    match_id: str
    label: str = ""
    home: str = ""
    away: str = ""
    league_id: str = ""
    home_score: int | None = None
    away_score: int | None = None
    outcome: str = ""                       # 胜负玩法赛果：胜/负
    ml_winner_odds: float | None = None     # 仅胜方一侧赔率（可能缺失）
    spread_covered: str = ""                # 让分盘口胜方：主/客
    spread_handicap: float | None = None    # 让分数（<0 客让，|值|；>0 主受让）
    spread_odds: float | None = None        # 竞彩让分赔率（HK 水位）
    ou_side: str = ""                       # 大小分：大/小
    ou_line: float | None = None            # 大小分线
    ou_odds: float | None = None            # 竞彩大小分赔率
    diff_result: str = ""                   # 分差赛果（如 客胜1-5）


def _team(raw: str) -> str:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts[0] if parts else ""


def _spread(token: str) -> tuple[str, float | None]:
    """'负(-1.5)' -> ('客', -1.5)；'胜(+5.5)' -> ('主', 5.5)。"""
    m = re.match(r"([胜负])\(([-+]?\d+(?:\.\d+)?)\)", token)
    if not m:
        return "", None
    return ("主" if m.group(1) == "胜" else "客"), float(m.group(2))


def _ou(token: str) -> tuple[str, float | None]:
    """'大(159.5)' -> ('大', 159.5)。"""
    m = re.match(r"([大小])\((\d+(?:\.\d+)?)\)", token)
    if not m:
        return "", None
    return m.group(1), float(m.group(2))


def _f(v: str) -> float | None:
    v = v.strip()
    if v in ("", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def fetch_nba_history_records(date_str: str) -> dict[str, NbaHistoryRecord]:
    """从 ``JcResult.aspx?d=日期&st=2`` 解析该日全部竞彩篮球的历史记录。

    返回 ``{match_id: NbaHistoryRecord}``。
    """
    raw = fetch_text(NBA_HISTORY_URL_TMPL.format(date=date_str), encoding="utf-8",
                     referer=_JC_REFERER)
    recs: dict[str, NbaHistoryRecord] = {}

    # 每个 ! 段内可能用 $ 串联「联赛前缀 + 比赛数据」，统一按 $ 再切。
    for seg in raw.split("!"):
        for part in seg.split("$"):
            if not part:
                continue
            f = part.split("^")
            if len(f) < 2:
                continue
            mid_raw = f[0]
            if not re.fullmatch(r"\d{6,8}", mid_raw):
                continue

            if f[1] in ("胜", "负"):
                # 结果段：$ID^胜负^胜负赔率^让分结果(线)^让分赔率^大小结果(线)^大小赔率^分差^分差赔率
                rec = recs.setdefault(mid_raw, NbaHistoryRecord(match_id=mid_raw))
                rec.outcome = f[1]
                rec.ml_winner_odds = _f(f[2]) if len(f) > 2 and f[2] else None
                if len(f) > 4:
                    sc, sh = _spread(f[3])
                    rec.spread_covered = sc
                    rec.spread_handicap = sh
                    rec.spread_odds = _f(f[4])
                if len(f) > 6:
                    os_, ol = _ou(f[5])
                    rec.ou_side = os_
                    rec.ou_line = ol
                    rec.ou_odds = _f(f[6])
                if len(f) > 7:
                    rec.diff_result = f[7].strip()
            else:
                # 比赛详情段：$ID^日期^-1^^周X00N^联赛ID^主队ID^主队名^主分^客队名^客分^...
                label_m = re.search(r"周[一二三四五六日]\d{2,3}", part)
                if not label_m:
                    continue
                lm = re.search(
                    r"周[一二三四五六日]\d{2,3}\^(\d+)\^(\d+)\^(.+?)\^(\d+)\^(.+?)\^(\d+)\^(\d+)",
                    part,
                )
                rec = recs.setdefault(mid_raw, NbaHistoryRecord(match_id=mid_raw))
                rec.label = label_m.group(0)
                if lm:
                    rec.league_id = lm.group(1)
                    rec.home = _team(lm.group(3))
                    rec.away = _team(lm.group(5))
                    rec.home_score = int(lm.group(6)) if lm.group(6).isdigit() else None
                    rec.away_score = int(lm.group(7)) if lm.group(7).isdigit() else None
    return recs


def _spread_desc(handicap: float | None, covered: str) -> str:
    if handicap is None:
        return "无数据"
    if handicap < 0:
        return f"主让{abs(handicap)}（{handicap}），{covered}队覆盖"
    return f"客让{handicap}（+{handicap}），{covered}队覆盖"


def format_nba_history_report(rec: NbaHistoryRecord) -> str:
    """生成历史赛果对照报告（兜底，无百家共识）。"""
    lines: list[str] = []
    lines.append("=" * 56)
    tag = f" {rec.label}" if rec.label else ""
    lines.append(f"篮球历史赛果对照 {rec.match_id}{tag}")
    lines.append("=" * 56)
    lines.append("")
    lines.append(f"对阵：{rec.home or '?'} VS {rec.away or '?'}")
    if rec.home_score is not None and rec.away_score is not None:
        winner = "主胜" if rec.home_score > rec.away_score else (
            "客胜" if rec.away_score > rec.home_score else "平")
        diff = abs(rec.home_score - rec.away_score)
        lines.append(f"实际比分：{rec.home_score} : {rec.away_score}  （{winner} {diff} 分）")
    lines.append("")

    if rec.outcome:
        lines.append(f"胜负玩法赛果：{'主胜' if rec.outcome == '胜' else '客胜'}")
    if rec.ml_winner_odds is not None:
        side = "主胜" if rec.outcome == "胜" else "客胜"
        lines.append(f"竞彩胜负终盘：{side} {rec.ml_winner_odds:.2f}（仅胜方一侧，无百家共识）")
    else:
        lines.append("竞彩胜负终盘：该场未记录胜负赔率")
    lines.append("")

    if rec.spread_handicap is not None:
        lines.append("竞彩让分终盘："
                     + _spread_desc(rec.spread_handicap, rec.spread_covered)
                     + (f"，赔率 {rec.spread_odds:.2f}" if rec.spread_odds is not None else ""))
    else:
        lines.append("竞彩让分终盘：无数据")
    lines.append("")

    if rec.ou_line is not None:
        lines.append(f"竞彩大小分终盘：{rec.ou_side}{rec.ou_line}"
                     + (f"，赔率 {rec.ou_odds:.2f}" if rec.ou_odds is not None else ""))
    else:
        lines.append("竞彩大小分终盘：无数据")
    if rec.diff_result:
        lines.append(f"分差赛果：{rec.diff_result}")
    lines.append("")

    lines.append("【说明】本场为已结束历史赛事，titan007 实时百家欧指/让分接口"
                 "（data1x2/*.js、AsianOdds_n.aspx）对已完赛比赛返回 502，")
    lines.append("故改用竞彩历史汇总接口（JcResult?st=2）提取「竞彩官* 终盘 + 实际赛果」做对照验证。")
    lines.append("该接口仅含竞彩单家终盘赔率（且部分场次胜负赔率缺失），"
                 "无法做完整市场共识/价值分析；结论仅供赛果对照，不构成投资建议。")
    return "\n".join(lines)
