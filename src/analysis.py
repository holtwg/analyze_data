"""胜平负概率分析与体彩投资方向推荐。

方法论（务必如实呈现，不夸大）：
1. **市场共识概率**：对各家博彩公司的「去水隐含概率」取均值（ wisdom of crowds ）。
   网站给出的主胜率/和率/客胜率已是 ``(1/赔率)/Σ(1/赔率)``，天然去水，直接聚合即可。
   同时给出中位数作为稳健性校验。
2. **体彩隐含概率**：用体彩官*行的即时赔率同样去水得到，代表体彩自身定价。
3. **价值(edge)**：``edge_i = 市场共识概率_i − 体彩隐含概率_i``（百分点）。
   edge > 0 表示该方向被体彩「相对低估」，在体彩下注有正向价值。
4. **期望收益(EV)**：``EV_i = 市场共识概率_i × 体彩赔率_i − 1``。
   体彩存在抽水（返还率 ≈ 88%），故三项 EV 通常为负；本指标用于比较相对优劣。

重要：以上均为基于公开赔率的概率/价值估算，并非赛果预测，不构成任何投资建议。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .config import OUTCOME_LABELS
from .odds import MatchOdds
from .football_asian_odds import AsianBookmaker


def margin_removed_probs(home: float, draw: float, away: float) -> tuple[float, float, float]:
    """由十进制赔率计算去水隐含概率（%，已归一化）。"""
    inv = 1.0 / home + 1.0 / draw + 1.0 / away
    return (1.0 / home) / inv * 100, (1.0 / draw) / inv * 100, (1.0 / away) / inv * 100


def _iqr(vals: list[float]) -> float:
    """四分位距 IQR = P75 - P25（线性插值）。衡量数据离散程度。"""
    if len(vals) < 2:
        return 0.0
    s = sorted(vals)
    n = len(s)

    def _pct(p: float) -> float:
        if n == 1:
            return s[0]
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(n - 1, lo + 1)
        return s[lo] + (s[hi] - s[lo]) * (idx - lo)

    return _pct(0.75) - _pct(0.25)


def _mode_val(vals: list[float]) -> float:
    """返回数值列表的众数（按 2 位小数聚合），用于确定主流让球盘口。"""
    from collections import Counter

    c = Counter(round(v, 2) for v in vals)
    return c.most_common(1)[0][0]


def _fmt_goals(g: float) -> str:
    """数值让球 -> 中文描述（主队视角）。g>0 主让，g<0 客让。"""
    sign = "主让" if g > 0 else "客让"
    a = abs(g)
    table = {
        0: "平手", 0.25: "平手/半球", 0.5: "半球", 0.75: "半球/一球",
        1: "一球", 1.25: "一球/球半", 1.5: "球半", 1.75: "球半/两球",
        2: "两球", 2.25: "两球/两球半", 2.5: "两球半",
    }
    desc = table.get(a, f"{a}")
    return f"{sign}{desc}"


@dataclass(slots=True)
class AnalysisResult:
    match_id: str
    home: str
    away: str
    match_time: str
    n_bookmakers: int
    consensus: tuple[float, float, float]          # 均值共识 (主,平,客) %
    consensus_median: tuple[float, float, float]    # 中位数共识 %
    lottery_odds: tuple[float, float, float] | None  # 体彩即时赔率
    lottery_implied: tuple[float, float, float] | None  # 体彩去水隐含概率 %
    edge: tuple[float, float, float] | None         # 价值 edge (pp)
    ev: tuple[float, float, float] | None           # 期望收益
    market_return_rate: float                       # 市场平均返还率 %
    most_probable: tuple[str, float]                # (方向, 概率%)
    best_value: tuple[str, float] | None            # (方向, edge pp)
    fetched_at: str = ""                            # 数据抓取时间（本地）
    lottery_update: str = ""                        # 体彩赔率更新时间
    # —— 市场一致性（凯利指数 + 离散度）——
    kelly_mean: tuple[float, float, float] | None = None
    kelly_var: tuple[float, float, float] | None = None
    kelly_favored: str | None = None               # 凯利最低方向（庄家真实倾向）
    disp_std: tuple[float, float, float] | None = None
    disp_iqr: tuple[float, float, float] | None = None
    # —— 欧亚一致性 ——
    asian_handicap: float | None = None
    asian_handicap_label: str = ""
    asian_win_prob: float | None = None            # 亚盘去水赢盘概率（让球方打穿）
    asian_favored: str | None = None               # 亚盘看好方（主胜/客胜）
    eurasian_agree: bool | None = None
    eurasian_note: str = ""
    notes: list[str] = field(default_factory=list)


def analyze(match: MatchOdds, asian: list[AsianBookmaker] | None = None) -> AnalysisResult:
    """对一场比赛做完整的胜平负概率与体彩方向分析。

    ``asian`` 为可选的足球亚盘数据（各公司让球盘口），传入后额外计算
    「欧亚一致性」分析，用亚盘方向佐证欧赔胜平负方向。
    """
    rows = [b for b in match.bookmakers if b.live_prob_home > 0]
    if not rows:
        raise ValueError("没有可用的即时赔率数据，无法分析")

    homes = [b.live_prob_home for b in rows]
    draws = [b.live_prob_draw for b in rows]
    aways = [b.live_prob_away for b in rows]

    # 均值共识（wisdom of crowds）
    c_mean = (statistics.mean(homes), statistics.mean(draws), statistics.mean(aways))
    # 中位数共识（稳健性）
    c_med = (statistics.median(homes), statistics.median(draws), statistics.median(aways))
    # 归一化（聚合后可能略偏离 100）
    tot = sum(c_mean)
    c_mean = (c_mean[0] / tot * 100, c_mean[1] / tot * 100, c_mean[2] / tot * 100)

    # 市场平均返还率（效率代理）
    returns = [b.live_return for b in rows if b.live_return > 0]
    market_return = statistics.mean(returns) if returns else 0.0

    lottery = match.lottery
    lottery_odds = lottery_implied = edge = ev = None
    best_value = None
    lottery_update = lottery.update_time if lottery is not None else ""
    notes: list[str] = []

    if lottery is not None:
        lottery_odds = (lottery.live_home, lottery.live_draw, lottery.live_away)
        lottery_implied = margin_removed_probs(*lottery_odds)
        edge = (c_mean[0] - lottery_implied[0], c_mean[1] - lottery_implied[1], c_mean[2] - lottery_implied[2])
        ev = (
            c_mean[0] / 100 * lottery_odds[0] - 1,
            c_mean[1] / 100 * lottery_odds[1] - 1,
            c_mean[2] / 100 * lottery_odds[2] - 1,
        )
        # 正 edge 最大的方向 = 体彩相对最有价值的方向
        best_idx = max(range(3), key=lambda i: edge[i])
        best_value = (OUTCOME_LABELS[best_idx], edge[best_idx])
        if max(ev) < 0:
            notes.append(
                "体彩三项 EV 均为负（体彩抽水约 "
                f"{100 - market_return:.1f}%），严格意义下无正期望方向；"
                "best_value 仅表示相对最不差的方向。"
            )
    else:
        notes.append("本场数据未含体彩官*赔率，体彩价值分析跳过，推荐仅基于市场共识概率。")

    # 概率最高的方向
    prob_idx = max(range(3), key=lambda i: c_mean[i])
    most_probable = (OUTCOME_LABELS[prob_idx], c_mean[prob_idx])

    # —— 市场一致性：凯利指数 + 离散度 ——
    kelly_rows = [
        b for b in match.bookmakers
        if b.kelly_home > 0 and b.kelly_draw > 0 and b.kelly_away > 0
    ]
    kelly_mean = kelly_var = kelly_favored = None
    if kelly_rows:
        kh = [b.kelly_home for b in kelly_rows]
        kd = [b.kelly_draw for b in kelly_rows]
        ka = [b.kelly_away for b in kelly_rows]
        kelly_mean = (statistics.mean(kh), statistics.mean(kd), statistics.mean(ka))
        kelly_var = (statistics.pvariance(kh), statistics.pvariance(kd), statistics.pvariance(ka))
        kf_idx = min(range(3), key=lambda i: kelly_mean[i])
        kelly_favored = OUTCOME_LABELS[kf_idx]
    # 离散度基于各公司即时隐含概率（wisdom of crowds 的原始分布）
    disp_std = (statistics.pstdev(homes), statistics.pstdev(draws), statistics.pstdev(aways))
    disp_iqr = (_iqr(homes), _iqr(draws), _iqr(aways))

    # —— 欧亚一致性：亚盘方向佐证欧赔方向 ——
    asian_handicap = asian_handicap_label = asian_win_prob = asian_favored = None
    eurasian_agree = None
    eurasian_note = ""
    if asian:
        goals_list = [a.goals for a in asian]
        main_g = _mode_val(goals_list)
        line = [a for a in asian if abs(a.goals - main_g) < 1e-6]
        if line:
            # 让球方 = 上盘；去水后「让球方打穿盘口」概率 = 下盘水位/(上+下)
            qs = [a.down / (a.up + a.down) for a in line]
            q = statistics.mean(qs)
            asian_handicap = main_g
            asian_handicap_label = _fmt_goals(main_g)
            asian_win_prob = q
            favored_side = "主胜" if main_g > 0 else "客胜"
            asian_favored = favored_side if q > 0.5 else ("客胜" if favored_side == "主胜" else "主胜")
            eu = most_probable[0]
            if asian_favored in ("主胜", "客胜") and eu in ("主胜", "客胜"):
                eurasian_agree = (asian_favored == eu)
                eurasian_note = (
                    "欧亚方向一致，相互佐证"
                    if eurasian_agree
                    else f"欧亚方向分歧：亚盘看好{asian_favored}，欧赔最看好{eu}，谨慎对待"
                )
            else:
                eurasian_note = f"亚盘方向参考：看好{asian_favored}"

    return AnalysisResult(
        match_id=match.match_id,
        home=match.hometeam,
        away=match.guestteam,
        match_time=match.match_time,
        n_bookmakers=len(rows),
        consensus=c_mean,
        consensus_median=c_med,
        lottery_odds=lottery_odds,
        lottery_implied=lottery_implied,
        edge=edge,
        ev=ev,
        market_return_rate=market_return,
        most_probable=most_probable,
        best_value=best_value,
        fetched_at=match.fetched_at,
        lottery_update=lottery_update,
        kelly_mean=kelly_mean,
        kelly_var=kelly_var,
        kelly_favored=kelly_favored,
        disp_std=disp_std,
        disp_iqr=disp_iqr,
        asian_handicap=asian_handicap,
        asian_handicap_label=asian_handicap_label,
        asian_win_prob=asian_win_prob,
        asian_favored=asian_favored,
        eurasian_agree=eurasian_agree,
        eurasian_note=eurasian_note,
        notes=notes,
    )


def format_report(r: AnalysisResult) -> str:
    """生成人类可读的分析报告。"""
    lines: list[str] = []
    lines.append("=" * 56)
    lines.append(f"比赛 {r.match_id}：{r.home} VS {r.away}")
    lines.append(f"开赛时间：{r.match_time}    样本：{r.n_bookmakers} 家博彩公司")
    if r.fetched_at:
        lines.append(f"数据抓取时间：{r.fetched_at}（每次运行重新实时抓取）")
    lines.append("=" * 56)
    lines.append("")
    lines.append("【胜平负概率（市场共识，去水）】")
    bar_max = 40
    for label, p, pm in zip(OUTCOME_LABELS, r.consensus, r.consensus_median):
        bar = "█" * int(round(p / 100 * bar_max))
        diff = abs(p - pm)
        lines.append(f"  {label:<4} {p:5.2f}%  (中位 {pm:5.2f}%)  {bar}  +{diff:.2f}%")
    lines.append("")
    if r.lottery_odds is not None:
        lines.append("【体彩官方即时赔率】")
        lines.append(
            f"  主胜 {r.lottery_odds[0]:.2f} | 平局 {r.lottery_odds[1]:.2f} | 客胜 {r.lottery_odds[2]:.2f}"
        )
        lines.append(
            f"  体彩去水隐含概率：主 {r.lottery_implied[0]:.2f}% | 平 {r.lottery_implied[1]:.2f}% | 客 {r.lottery_implied[2]:.2f}%"
        )
        if r.lottery_update:
            lines.append(f"  体彩赔率更新时间：{r.lottery_update}")
        lines.append("")
        lines.append("【体彩投资方向研判】")
        lines.append(f"  市场平均返还率：{r.market_return_rate:.2f}%（抽水 {100 - r.market_return_rate:.2f}%）")
        for label, e, v in zip(OUTCOME_LABELS, r.edge, r.ev):
            lines.append(f"  {label:<4} edge {e:+5.2f}pp   EV {v*100:+6.2f}%")
        lines.append("")
        lines.append(f"  -> 概率最高方向（最被看好）：{r.most_probable[0]}（{r.most_probable[1]:.2f}%）")
        if r.best_value is not None:
            verdict = "有正向价值" if r.best_value[1] > 0 else "相对最不差（仍为负 EV）"
            lines.append(f"  -> 体彩相对价值最高方向：{r.best_value[0]}（edge {r.best_value[1]:+.2f}pp，{verdict}）")
    else:
        lines.append(f"  -> 概率最高方向：{r.most_probable[0]}（{r.most_probable[1]:.2f}%）")
    lines.append("")
    lines.append("【市场一致性分析（凯利指数 + 离散度）】")
    if r.kelly_mean is not None:
        lines.append(
            f"  凯利指数均值: 主 {r.kelly_mean[0]:.3f} / 平 {r.kelly_mean[1]:.3f} / 客 {r.kelly_mean[2]:.3f}"
        )
        lines.append(
            f"  凯利指数方差: 主 {r.kelly_var[0]:.4f} / 平 {r.kelly_var[1]:.4f} / 客 {r.kelly_var[2]:.4f}"
            f"  （越小越一致）"
        )
        lines.append(f"  庄家倾向(凯利最低方向): {r.kelly_favored}")
    if r.disp_std is not None:
        lines.append(
            f"  离散度(标准差): 主 {r.disp_std[0]:.2f}% / 平 {r.disp_std[1]:.2f}% / 客 {r.disp_std[2]:.2f}%"
        )
        lines.append(
            f"  离散度(IQR):    主 {r.disp_iqr[0]:.2f}% / 平 {r.disp_iqr[1]:.2f}% / 客 {r.disp_iqr[2]:.2f}%"
        )
        lines.append("   注：离散度低 = 各家公司看法集中；高 = 分歧大、风险高")
    lines.append("")
    if r.asian_handicap is not None:
        lines.append("【欧亚一致性分析】")
        lines.append(f"  主流亚盘让球: {r.asian_handicap_label}")
        lines.append(f"  亚盘去水赢盘概率(让球方打穿盘口): {r.asian_win_prob * 100:.2f}%")
        lines.append(f"  亚盘看好方: {r.asian_favored}")
        lines.append(f"  欧赔最看好方: {r.most_probable[0]}（{r.most_probable[1]:.2f}%）")
        if r.eurasian_agree is not None:
            mark = "方向一致，相互佐证" if r.eurasian_agree else "方向分歧，谨慎对待"
            lines.append(f"  -> {mark}：{r.eurasian_note}")
        else:
            lines.append(f"  -> {r.eurasian_note}")
        lines.append("")
    for n in r.notes:
        lines.append(f"  注：{n}")
    lines.append("")
    lines.append("【风险提示】以上为基于公开赔率的概率/价值估算，非赛果预测，")
    lines.append("  不构成任何投资建议。博彩有风险，请理性投注、量力而行。")
    return "\n".join(lines)
