"""篮球胜负(主胜/客胜)概率分析与体彩方向推荐。

方法论（与足球版一致，因篮球无平局故为 2-way）：
1. **市场共识概率**：对各家「去水隐含主胜率/客胜率」取均值（wisdom of crowds）。
   网站给出的主胜率/客胜率已是 ``(1/赔率)/(1/主赔+1/客赔)``，天然去水，直接聚合即可。
   同时给中位数作稳健性校验。
2. **凯利指数与方差**：titan007 已给出每家公司即时主/客凯利指数。凯利指数越低，
   庄家对该方向的赔付控制越紧，可视为庄家真实倾向。凯利方差越小，表示各公司
   对该方向看法越一致。
3. **离散度（标准差 / IQR）**：衡量百家公司对主/客胜概率的分歧程度。
   离散度低 = 市场一致，可信度高；离散度高 = 分歧大，风险高。
4. **变盘倾向**：比较初盘共识概率与即时共识概率，判断资金/观点是否向某个方向
   移动。若即时概率显著高于初盘，视为市场向该方向升温。
5. **体彩隐含概率**：用体彩官*行即时主胜/客胜赔率同样去水得到，代表体彩自身定价。
6. **价值(edge)**：``edge_i = 市场共识概率_i − 体彩隐含概率_i``（百分点）。
   edge > 0 表示该方向被体彩相对低估，在体彩下注有正向价值。
7. **期望收益(EV)**：``EV_i = 市场共识概率_i × 体彩赔率_i − 1``。
   体彩存在抽水（返还率≈88%），故两项 EV 通常为负；本指标用于比较相对优劣。

重要：以上均为基于公开赔率的概率/价值估算，并非赛果预测，不构成任何投资建议。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .config import NBA_OUTCOME_LABELS
from .nba_odds import NbaMatchOdds


def margin_removed_probs(home: float, away: float) -> tuple[float, float]:
    """由十进制赔率计算去水隐含概率（%，已归一化）。"""
    inv = 1.0 / home + 1.0 / away
    return (1.0 / home) / inv * 100, (1.0 / away) / inv * 100


def _safe_variance(data: list[float]) -> float:
    """样本方差；样本不足时返回 0.0。"""
    if len(data) < 2:
        return 0.0
    try:
        return statistics.variance(data)
    except statistics.StatisticsError:
        return 0.0


def _safe_iqr(data: list[float]) -> float:
    """四分位距（Q3 - Q1）；样本不足时返回 0.0。"""
    if len(data) < 2:
        return 0.0
    try:
        qs = statistics.quantiles(data, n=4, method="inclusive")
        return qs[2] - qs[0]
    except statistics.StatisticsError:
        return 0.0


@dataclass(slots=True)
class NbaAnalysisResult:
    match_id: str
    home: str
    away: str
    match_time: str
    n_bookmakers: int
    consensus: tuple[float, float]                 # 即时均值共识 (主,客) %
    consensus_median: tuple[float, float]          # 中位数共识 %
    lottery_odds: tuple[float, float] | None        # 体彩即时赔率
    lottery_implied: tuple[float, float] | None     # 体彩去水隐含概率 %
    edge: tuple[float, float] | None                # 价值 edge (pp)
    ev: tuple[float, float] | None                  # 期望收益
    market_return_rate: float                       # 市场平均返还率 %
    most_probable: tuple[str, float]                # (方向, 概率%)
    best_value: tuple[str, float] | None            # (方向, edge pp)
    # 新增：市场一致性与变盘
    kelly_mean: tuple[float, float] = (0.0, 0.0)            # 凯利指数均值
    kelly_variance: tuple[float, float] = (0.0, 0.0)        # 凯利指数方差
    kelly_favored: str = ""                                # 庄家倾向方向
    prob_std: tuple[float, float] = (0.0, 0.0)              # 隐含概率标准差
    prob_iqr: tuple[float, float] = (0.0, 0.0)               # 隐含概率 IQR
    init_consensus: tuple[float, float] = (0.0, 0.0)        # 初盘共识概率
    momentum_favored: str = ""                              # 变盘升温方向
    momentum_delta: tuple[float, float] = (0.0, 0.0)       # 即时 - 初盘 (pp)
    fetched_at: str = ""
    lottery_update: str = ""
    notes: list[str] = field(default_factory=list)


def analyze_nba(match: NbaMatchOdds) -> NbaAnalysisResult:
    """对一场篮球比赛做完整的胜负概率与体彩方向分析。"""
    rows = [b for b in match.bookmakers if b.live_prob_home > 0 and b.live_prob_away > 0]
    if not rows:
        raise ValueError(
            f"比赛 {match.match_id} 暂未提供胜负赔率数据（可能尚未开盘或数据源未给出），无法分析"
        )

    homes = [b.live_prob_home for b in rows]
    aways = [b.live_prob_away for b in rows]

    c_mean = (statistics.mean(homes), statistics.mean(aways))
    c_med = (statistics.median(homes), statistics.median(aways))
    tot = sum(c_mean) or 1.0
    c_mean = (c_mean[0] / tot * 100, c_mean[1] / tot * 100)

    returns = [b.live_return for b in rows if b.live_return > 0]
    market_return = statistics.mean(returns) if returns else 0.0

    # ---- 新增：凯利指数与离散度 ----
    k_h = [b.kelly_home for b in rows if b.kelly_home > 0]
    k_a = [b.kelly_away for b in rows if b.kelly_away > 0]
    k_mean = (
        statistics.mean(k_h) if k_h else 0.0,
        statistics.mean(k_a) if k_a else 0.0,
    )
    k_var = (_safe_variance(k_h), _safe_variance(k_a))
    k_favored = NBA_OUTCOME_LABELS[min(range(2), key=lambda i: k_mean[i])]

    prob_std = (statistics.stdev(homes) if len(homes) > 1 else 0.0,
                statistics.stdev(aways) if len(aways) > 1 else 0.0)
    prob_iqr = (_safe_iqr(homes), _safe_iqr(aways))

    # ---- 新增：变盘倾向（初盘 -> 即时） ----
    init_rows = [b for b in match.bookmakers
                 if b.init_prob_home > 0 and b.init_prob_away > 0]
    init_mean = (0.0, 0.0)
    if init_rows:
        i_h = [b.init_prob_home for b in init_rows]
        i_a = [b.init_prob_away for b in init_rows]
        init_mean = (statistics.mean(i_h), statistics.mean(i_a))
        i_tot = sum(init_mean) or 1.0
        init_mean = (init_mean[0] / i_tot * 100, init_mean[1] / i_tot * 100)
    momentum_delta = (c_mean[0] - init_mean[0], c_mean[1] - init_mean[1])
    momentum_favored = NBA_OUTCOME_LABELS[max(range(2), key=lambda i: momentum_delta[i])]

    # ---- 体彩价值 ----
    lottery = match.lottery
    lottery_odds = lottery_implied = edge = ev = None
    best_value = None
    lottery_update = lottery.update_time if lottery is not None else ""
    notes: list[str] = []

    if lottery is not None:
        lottery_odds = (lottery.live_home, lottery.live_away)
        lottery_implied = margin_removed_probs(*lottery_odds)
        edge = (c_mean[0] - lottery_implied[0], c_mean[1] - lottery_implied[1])
        ev = (
            c_mean[0] / 100 * lottery_odds[0] - 1,
            c_mean[1] / 100 * lottery_odds[1] - 1,
        )
        best_idx = max(range(2), key=lambda i: edge[i])
        best_value = (NBA_OUTCOME_LABELS[best_idx], edge[best_idx])
        if max(ev) < 0:
            notes.append(
                "体彩两项 EV 均为负（体彩抽水约 "
                f"{100 - market_return:.1f}%），严格意义下无正期望方向；"
                "best_value 仅表示相对最不差的方向。"
            )
    else:
        notes.append("本场数据未含体彩官*赔率，体彩价值分析跳过，推荐仅基于市场共识概率。")

    prob_idx = max(range(2), key=lambda i: c_mean[i])
    most_probable = (NBA_OUTCOME_LABELS[prob_idx], c_mean[prob_idx])

    return NbaAnalysisResult(
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
        kelly_mean=k_mean,
        kelly_variance=k_var,
        kelly_favored=k_favored,
        prob_std=prob_std,
        prob_iqr=prob_iqr,
        init_consensus=init_mean,
        momentum_favored=momentum_favored,
        momentum_delta=momentum_delta,
        fetched_at=match.fetched_at,
        lottery_update=lottery_update,
        notes=notes,
    )


def format_nba_report(r: NbaAnalysisResult) -> str:
    """生成人类可读的篮球胜负分析报告。"""
    lines: list[str] = []
    lines.append("=" * 56)
    lines.append(f"篮球胜负 {r.match_id}：{r.home} VS {r.away}")
    lines.append(f"开赛时间：{r.match_time}    样本：{r.n_bookmakers} 家博彩公司")
    if r.fetched_at:
        lines.append(f"数据抓取时间：{r.fetched_at}（每次运行重新实时抓取）")
    lines.append("=" * 56)
    lines.append("")
    lines.append("【胜负概率（市场共识，去水）】")
    bar_max = 40
    for label, p, pm in zip(NBA_OUTCOME_LABELS, r.consensus, r.consensus_median):
        bar = "█" * int(round(p / 100 * bar_max))
        lines.append(f"  {label:<4} {p:5.2f}%  (中位 {pm:5.2f}%)  {bar}")
    lines.append("")

    # ---- 新增：市场一致性分析 ----
    lines.append("【市场一致性分析（凯利指数 + 离散度）】")
    lines.append(
        f"  凯利指数均值: 主 {r.kelly_mean[0]:.3f} / 客 {r.kelly_mean[1]:.3f}"
    )
    lines.append(
        f"  凯利指数方差: 主 {r.kelly_variance[0]:.4f} / 客 {r.kelly_variance[1]:.4f}  （越小越一致）"
    )
    lines.append(f"  庄家倾向(凯利最低方向): {r.kelly_favored}")
    lines.append(
        f"  离散度(标准差): 主 {r.prob_std[0]:.2f}% / 客 {r.prob_std[1]:.2f}%"
    )
    lines.append(
        f"  离散度(IQR)   : 主 {r.prob_iqr[0]:.2f}% / 客 {r.prob_iqr[1]:.2f}%"
    )
    lines.append("")

    # ---- 新增：变盘倾向 ----
    if r.init_consensus != (0.0, 0.0):
        lines.append("【变盘倾向（初盘 → 即时）】")
        lines.append(
            f"  初盘共识概率: 主 {r.init_consensus[0]:.2f}% / 客 {r.init_consensus[1]:.2f}%"
        )
        lines.append(
            f"  即时共识概率: 主 {r.consensus[0]:.2f}% / 客 {r.consensus[1]:.2f}%"
        )
        lines.append(
            f"  变化(即时-初盘): 主 {r.momentum_delta[0]:+.2f}pp / 客 {r.momentum_delta[1]:+.2f}pp"
        )
        lines.append(f"  变盘升温方向: {r.momentum_favored}")
        lines.append("")

    if r.lottery_odds is not None:
        lines.append("【体彩官方即时赔率（胜负）】")
        lines.append(
            f"  主胜 {r.lottery_odds[0]:.2f} | 客胜 {r.lottery_odds[1]:.2f}"
        )
        lines.append(
            f"  体彩去水隐含概率：主 {r.lottery_implied[0]:.2f}% | 客 {r.lottery_implied[1]:.2f}%"
        )
        if r.lottery_update:
            lines.append(f"  体彩赔率更新时间：{r.lottery_update}")
        lines.append("")
        lines.append("【体彩投资方向研判（胜负）】")
        lines.append(f"  市场平均返还率：{r.market_return_rate:.2f}%（抽水 {100 - r.market_return_rate:.2f}%）")
        for label, e, v in zip(NBA_OUTCOME_LABELS, r.edge, r.ev):
            lines.append(f"  {label:<4} edge {e:+5.2f}pp   EV {v*100:+6.2f}%")
        lines.append("")
        lines.append(f"  -> 概率最高方向（最被看好）：{r.most_probable[0]}（{r.most_probable[1]:.2f}%）")
        if r.best_value is not None:
            verdict = "有正向价值" if r.best_value[1] > 0 else "相对最不差（仍为负 EV）"
            lines.append(f"  -> 体彩相对价值最高方向：{r.best_value[0]}（edge {r.best_value[1]:+.2f}pp，{verdict}）")
    else:
        lines.append(f"  -> 概率最高方向：{r.most_probable[0]}（{r.most_probable[1]:.2f}%）")
    lines.append("")
    for n in r.notes:
        lines.append(f"  注：{n}")
    lines.append("")
    lines.append("【风险提示】以上为基于公开赔率的概率/价值估算，非赛果预测，")
    lines.append("  不构成任何投资建议。博彩有风险，请理性投注、量力而行。")
    return "\n".join(lines)
