"""篮球让分方向概率与体彩价值分析。

核心输出：给定让分盘口，市场（百家）对「主队覆盖让分」的共识概率，
并对照竞彩官方让分盘的隐含概率，给出体彩价值研判。

同时与篮球胜负盘（moneyline）做交叉验证：让分盘看好方向应与胜负盘
最看好方向一致；若方向相反，提示存在矛盾信号。

盘口惯例：titan007 让分页全部以香港盘(水位)显示，去水概率使用
``p_主 = 1/(1+O_上) / (1/(1+O_上) + 1/(1+O_下))``。
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean

from .nba_analysis import NbaAnalysisResult
from .nba_spread_odds import NbaSpreadBookmaker, NbaSpreadMatch


def _hk_cover(up: float, down: float) -> float:
    """香港盘下，上盘(主队侧)覆盖让分的概率（去水）。up/down 为水位。"""
    if up <= 0 or down <= 0:
        return 0.0
    a = 1.0 / (1.0 + up)
    b = 1.0 / (1.0 + down)
    s = a + b
    return a / s if s > 0 else 0.0


def _fmt_handicap(h: float) -> str:
    """让分数 -> 中文方向描述。"""
    if h > 0:
        return f"主让{h}"
    if h < 0:
        return f"客让{abs(h)}"
    return "无让分(平手)"


@dataclass(slots=True)
class NbaSpreadAnalysis:
    match_id: str
    hometeam: str
    guestteam: str
    match_time: str
    fetched_at: str
    main_handicap: float                 # 主流即时让分（mode）
    main_handicap_label: str             # 中文方向
    n_companies: int
    consensus_home_cover: float          # 全部公司均值：主覆盖概率
    consensus_away_cover: float
    main_line_home_cover: float          # 主流让分线下的均值
    main_line_away_cover: float
    main_line_n: int                     # 主流线公司数
    # 新增：离散度
    cover_std: float = 0.0               # 主覆盖概率标准差
    cover_iqr: float = 0.0                # 主覆盖概率 IQR
    cover_away_std: float = 0.0           # 客覆盖概率标准差（数学上等于主，但单独展示更完整）
    cover_away_iqr: float = 0.0           # 客覆盖概率 IQR
    # 新增：与胜负盘一致性
    ml_consensus_home: float | None = None
    ml_consensus_away: float | None = None
    spread_favored: str = ""             # 让分盘看好方向
    ml_favored: str | None = None        # 胜负盘最看好方向
    consistency_note: str = ""            # 一致性结论
    lottery_handicap: float | None = None
    lottery_handicap_label: str = ""
    lottery_up: float | None = None
    lottery_down: float | None = None
    lottery_home_cover: float | None = None
    lottery_away_cover: float | None = None
    lottery_edge: float | None = None   # 体彩隐含 - 市场共识（同线近似）
    companies: list[dict] = field(default_factory=list)
    is_historical: bool = False


def _bookmaker_line(b: NbaSpreadBookmaker):
    """选择盘口线：统一使用页面有效盘口（赛前终盘/当前即时盘）。

    解析阶段已优先取 ``wholeOdds`` 列，因此历史比赛为赛前封盘盘口，
    未开赛为当前即时盘口。仅在有效盘缺失时回退到初盘。
    """
    if b.live_up > 0 and b.live_down > 0:
        return b.live_handicap, b.live_up, b.live_down
    if b.is_lottery:
        return b.init_handicap, b.init_up, b.init_down
    return b.init_handicap, b.init_up, b.init_down


def _safe_std(data: list[float]) -> float:
    if len(data) < 2:
        return 0.0
    try:
        return statistics.stdev(data)
    except statistics.StatisticsError:
        return 0.0


def _safe_iqr(data: list[float]) -> float:
    if len(data) < 2:
        return 0.0
    try:
        qs = statistics.quantiles(data, n=4, method="inclusive")
        return qs[2] - qs[0]
    except statistics.StatisticsError:
        return 0.0


def analyze_nba_spread(match: NbaSpreadMatch, ml_result: NbaAnalysisResult | None = None) -> NbaSpreadAnalysis:
    rows = []
    for b in match.bookmakers:
        h, up, down = _bookmaker_line(b)
        if up > 0 and down > 0 and h != 0:
            rows.append(b)
    if not rows:
        raise ValueError(
            f"比赛 {match.match_id} 暂未提供让分盘口数据"
            f"（可能尚未开盘或数据源未给出让分盘）"
        )

    covers = []
    for b in rows:
        _, up, down = _bookmaker_line(b)
        c = _hk_cover(up, down)
        covers.append((b, c))

    consensus_home = mean(c for _, c in covers)
    consensus_away = 1.0 - consensus_home

    # 让分盘离散度
    cover_values = [c for _, c in covers]
    cover_std = _safe_std(cover_values)
    cover_iqr = _safe_iqr(cover_values)
    cover_away_std = _safe_std([1.0 - c for c in cover_values])
    cover_away_iqr = _safe_iqr([1.0 - c for c in cover_values])

    # 主流让分（mode）
    cnt = Counter(_bookmaker_line(b)[0] for b, _ in covers)
    main_h = cnt.most_common(1)[0][0]
    main_line = [(b, c) for b, c in covers if _bookmaker_line(b)[0] == main_h]
    main_home = mean(c for _, c in main_line)
    main_away = 1.0 - main_home

    lottery = match.lottery
    lot = None
    if lottery:
        lh, lup, ldown = _bookmaker_line(lottery)
        if lup > 0 and ldown > 0:
            cover = _hk_cover(lup, ldown)
            # 体彩价值：以主流线共识为参照（注意竞彩让分线可能与市场主流不同）
            edge = (cover - consensus_home) * 100.0
            lot = {
                "handicap": lh,
                "label": _fmt_handicap(lh),
                "up": lup,
                "down": ldown,
                "home_cover": cover,
                "away_cover": 1.0 - cover,
                "edge": edge,
            }

    # 展示用：取主流线上的公司 + 体彩官*
    disp = []
    for b, c in main_line:
        h, up, down = _bookmaker_line(b)
        disp.append({
            "name": b.name,
            "handicap": h,
            "up": up,
            "down": down,
            "home_cover": c,
            "is_lottery": b.is_lottery,
        })
    disp.sort(key=lambda d: (not d["is_lottery"], -d["home_cover"]))

    # 与胜负盘（moneyline）一致性校验
    ml_consensus_home = ml_consensus_away = None
    spread_favored = ml_favored = ""
    consistency_note = "未提供胜负盘数据，无法做让分-胜负一致性校验。"
    if ml_result is not None:
        ml_consensus_home = ml_result.consensus[0]
        ml_consensus_away = ml_result.consensus[1]
        diff = abs(consensus_home - consensus_away)
        if diff <= 0.02:
            spread_favored = "接近均衡"
        elif consensus_home > consensus_away:
            spread_favored = "主胜"
        else:
            spread_favored = "客胜"
        ml_favored = ml_result.most_probable[0]
        if spread_favored == "接近均衡":
            consistency_note = (
                f"让分盘接近均衡（主/客覆盖差距 {diff*100:.1f}pp），"
                f"胜负盘更看好【{ml_favored}】，让分盘对胜负方向指引有限。"
            )
        elif spread_favored == ml_favored:
            consistency_note = f"方向一致：让分盘与胜负盘均看好【{spread_favored}】，相互佐证。"
        else:
            consistency_note = (
                f"方向分歧：让分盘看好【{spread_favored}】，"
                f"胜负盘看好【{ml_favored}】，两个市场信号不一致，谨慎对待。"
            )

    return NbaSpreadAnalysis(
        match_id=match.match_id,
        hometeam=match.hometeam,
        guestteam=match.guestteam,
        match_time=match.match_time,
        fetched_at=match.fetched_at,
        main_handicap=main_h,
        main_handicap_label=_fmt_handicap(main_h),
        n_companies=len(rows),
        consensus_home_cover=consensus_home,
        consensus_away_cover=consensus_away,
        main_line_home_cover=main_home,
        main_line_away_cover=main_away,
        main_line_n=len(main_line),
        cover_std=cover_std,
        cover_iqr=cover_iqr,
        cover_away_std=cover_away_std,
        cover_away_iqr=cover_away_iqr,
        ml_consensus_home=ml_consensus_home,
        ml_consensus_away=ml_consensus_away,
        spread_favored=spread_favored,
        ml_favored=ml_favored,
        consistency_note=consistency_note,
        lottery_handicap=lot["handicap"] if lot else None,
        lottery_handicap_label=lot["label"] if lot else "",
        lottery_up=lot["up"] if lot else None,
        lottery_down=lot["down"] if lot else None,
        lottery_home_cover=lot["home_cover"] if lot else None,
        lottery_away_cover=lot["away_cover"] if lot else None,
        lottery_edge=lot["edge"] if lot else None,
        companies=disp,
        is_historical=match.is_historical,
    )


def format_nba_spread_report(r: NbaSpreadAnalysis) -> str:
    L = []
    L.append("=" * 60)
    L.append(f"篮球让分(盘口)方向概率分析  [{r.match_id}]")
    L.append("=" * 60)
    L.append(f"对阵   : {r.hometeam} VS {r.guestteam}")
    L.append(f"开赛时间: {r.match_time}")
    L.append(f"数据抓取: {r.fetched_at}")
    if r.is_historical:
        L.append("[历史比赛] 百家公司按赛前封盘盘口计算；竞彩官方无滚球盘，使用页面最新数据")
    else:
        L.append("[未开赛] 百家公司按当前即时盘口计算；竞彩官方无滚球盘，使用页面最新数据")
    L.append("")
    L.append(f"主流让分: {r.main_handicap_label}  （{r.main_line_n}/{r.n_companies} 家公司）")
    L.append("")
    L.append("【市场共识：主队覆盖让分概率】")
    L.append(f"  主流线({r.main_handicap_label})下: 主 {r.main_line_home_cover*100:.1f}% / 客 {r.main_line_away_cover*100:.1f}%")
    L.append(f"  全部公司均值        : 主 {r.consensus_home_cover*100:.1f}% / 客 {r.consensus_away_cover*100:.1f}%")
    L.append("")
    L.append("【让分盘离散度】")
    L.append(f"  主覆盖概率标准差: {r.cover_std*100:.2f}%")
    L.append(f"  主覆盖概率 IQR   : {r.cover_iqr*100:.2f}%")
    L.append(f"  客覆盖概率标准差: {r.cover_away_std*100:.2f}%")
    L.append(f"  客覆盖概率 IQR   : {r.cover_away_iqr*100:.2f}%")
    L.append(f"  市场一致性判断: {'高' if r.cover_iqr*100 < 5 else ('中等' if r.cover_iqr*100 < 10 else '低')}（IQR 越小越一致）")
    L.append("")
    if r.ml_consensus_home is not None:
        L.append("【让分盘与胜负盘一致性校验】")
        L.append(f"  让分盘看好方  : {r.spread_favored}（主覆盖 {r.consensus_home_cover*100:.1f}%）")
        L.append(f"  胜负盘最看好方: {r.ml_favored}（主胜 {r.ml_consensus_home:.2f}%）")
        L.append(f"  -> {r.consistency_note}")
        L.append("")
    if r.lottery_handicap is not None:
        L.append("【竞彩官方让分盘】")
        L.append(f"  竞彩让分: {r.lottery_handicap_label}  上盘(主队侧) {r.lottery_up} / 下盘(客队侧) {r.lottery_down}")
        L.append(f"  竞彩隐含主覆盖: {r.lottery_home_cover*100:.1f}%  客覆盖: {r.lottery_away_cover*100:.1f}%")
        if abs(r.lottery_handicap - r.main_handicap) > 1e-6:
            L.append(f"  [提示] 竞彩让分线({r.lottery_handicap_label})与市场主流({r.main_handicap_label})不同，")
            L.append(f"         以下 edge 为近似对照（非同线直接比较）：")
        edge = r.lottery_edge or 0.0
        better = "主队覆盖" if edge > 0 else ("客队覆盖" if edge < 0 else "均衡")
        L.append(f"  体彩价值(隐含-共识): {edge:+.1f}pp  -> 相对市场，竞彩更看好【{better}】")
        L.append("")
    L.append("【各公司盘口(主流线，按主覆盖降序，前 12 家)】")
    L.append(f"  {'公司':<10}{'让分':>8}{'上盘':>8}{'下盘':>8}{'主覆盖%':>10}")
    for d in r.companies[:12]:
        tag = "*" if d["is_lottery"] else " "
        L.append(f"  {tag}{d['name']:<9}{d['handicap']:>8}{d['up']:>8}{d['down']:>8}{d['home_cover']*100:>9.1f}")
    L.append("")
    L.append("说明：概率为基于百家香港盘口去水后的市场共识，非赛果预测；")
    L.append("竞彩官* 行为体彩让分胜负赔率。结论仅供量化参考，不构成投资建议。")
    L.append("=" * 60)
    return "\n".join(L)
