"""解析单场篮球让分(亚洲盘/盘口)数据。

数据来源：``nba.titan007.com/odds/AsianOdds_n.aspx?id={match_id}&l=0``（HTML 表格，UTF-8）。

该页以 HTML <tr> 表格展示各公司让分盘口，每行按固定位置排列：
    初盘(上盘赔率, 让分数, 下盘赔率) + 即时(上盘赔率, 让分数, 下盘赔率) + 盘2...
每个公司行含 ``companyID`` 标记，单元格文本依次为：公司名、空(标记位)、数值...

让分数 H：``H>0`` 表示「主让 H」，``H<0`` 表示「客让 |H|」。
上盘 = 主队一侧（主队 - H 或 主队 + |H|），下盘 = 客队一侧。

盘口惯例（重要）：titan007 让分页全部以**香港盘(水位)**显示，即数值 O 表示
「下注 1 单位、若赢则获利 O 单位（共返还 1+O）」。因此去水隐含概率使用
``p_上 = 1/(1+O_上) / (1/(1+O_上) + 1/(1+O_下))``（含本金口径），
**不能直接用欧洲盘 1/O 口径**（会让分盘数值均 <1，欧洲盘不可能 <1）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .client import fetch_text
from .config import LOTTERY_KEYWORDS, NBA_SPREAD_URL_TMPL
from .nba_odds import fetch_nba_meta


@dataclass(slots=True)
class NbaSpreadBookmaker:
    """单家博彩公司的篮球让分快照。"""

    company_cn: str
    company_en: str
    init_handicap: float          # 初盘让分数（>0 主让, <0 客让）
    init_up: float                # 初盘 上盘(主队侧)赔率（HK 水位）
    init_down: float              # 初盘 下盘(客队侧)赔率
    live_handicap: float          # 即时让分数
    live_up: float                # 即时 上盘赔率
    live_down: float              # 即时 下盘赔率
    is_lottery: bool

    @property
    def name(self) -> str:
        return self.company_cn or self.company_en


@dataclass(slots=True)
class NbaSpreadMatch:
    """一场篮球比赛的让分数据。"""

    match_id: str
    hometeam: str
    guestteam: str
    match_time: str
    bookmakers: list[NbaSpreadBookmaker]
    fetched_at: str = ""
    is_historical: bool = False  # 已开赛/已结束的历史比赛

    @property
    def lottery(self) -> NbaSpreadBookmaker | None:
        for b in self.bookmakers:
            if b.is_lottery:
                return b
        return None


def _f(v: str) -> float | None:
    v = v.strip()
    if v in ("", "-", "—"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_spread_html(html: str) -> list[NbaSpreadBookmaker]:
    """从让分 HTML 表格解析各公司让分盘口。

    titan007 让分页每家公司行同时包含多组盘口：
      - 初盘（页面固定列，无 oddstype 属性）
      - ``wholeLastOdds``（页面默认显示的"即时"列；历史比赛时可能是赛后/滚球盘）
      - ``wholeOdds``（select 下拉中的"终盘"列；未开赛即当前盘口，历史比赛即赛前最终盘）

    为避免历史比赛混入赛后滚球盘口，本解析器优先取 ``wholeOdds`` 列作为有效盘口；
    仅在该列缺失时才回退到 ``wholeLastOdds``。
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    out: list[NbaSpreadBookmaker] = []
    for row in rows:
        if "companyID" not in row and 'id="td_' not in row:
            continue

        # 提取每个 td 的完整 HTML 与 oddstype 属性
        td_matches = re.findall(r'<td[^>]*>.*?</td>', row, re.DOTALL)
        tds: list[dict[str, str]] = []
        for td_html in td_matches:
            text = re.sub(r"<[^>]+>", "", td_html).strip()
            ot_match = re.search(r'oddstype=["\']?([^"\'>]+)["\']?', td_html, re.IGNORECASE)
            oddstype = ot_match.group(1).strip().lower() if ot_match else ""
            tds.append({"text": text, "oddstype": oddstype})

        if not tds:
            continue
        name = tds[0]["text"]
        if not name or name in ("公司", "多盘"):
            continue

        # 初盘：前几个无 oddstype 的数值单元格
        init_floats: list[float] = []
        for td in tds:
            if td["oddstype"]:
                continue
            fv = _f(td["text"])
            if fv is not None:
                init_floats.append(fv)
        if len(init_floats) < 3:
            continue
        iu, ih, idn = init_floats[:3]

        # 按 oddstype 分组收集有效盘口
        type_floats: dict[str, list[float]] = {}
        for td in tds:
            if not td["oddstype"]:
                continue
            fv = _f(td["text"])
            if fv is not None:
                type_floats.setdefault(td["oddstype"], []).append(fv)

        whole_odds = type_floats.get("wholeodds", [])
        last_odds = type_floats.get("wholelastodds", [])

        # 优先 wholeOdds（赛前终盘/当前即时盘），缺失则回退 wholeLastOdds
        if len(whole_odds) >= 3:
            lu, lh, ldn = whole_odds[:3]
        elif len(last_odds) >= 3:
            lu, lh, ldn = last_odds[:3]
        else:
            # 兜底：按顺序取初盘后的前 3 个浮点数
            all_floats: list[float] = []
            for td in tds:
                fv = _f(td["text"])
                if fv is not None:
                    all_floats.append(fv)
            if len(all_floats) < 6:
                continue
            lu, lh, ldn = all_floats[3], all_floats[4], all_floats[5]

        # 合理性校验：让分在 [-50,50]，赔率在 (0.3, 5) 区间
        if not (-50 <= ih <= 50 and -50 <= lh <= 50):
            continue
        if not (0.3 < iu < 5 and 0.3 < idn < 5 and 0.3 < lu < 5 and 0.3 < ldn < 5):
            continue
        en = ""
        cn = name
        is_lottery = any(kw in cn or kw in en for kw in LOTTERY_KEYWORDS)
        out.append(
            NbaSpreadBookmaker(
                company_cn=cn,
                company_en=en,
                init_handicap=ih,
                init_up=iu,
                init_down=idn,
                live_handicap=lh,
                live_up=lu,
                live_down=ldn,
                is_lottery=is_lottery,
            )
        )
    return out


def _is_historical_match(match_time: str, fetched_at: datetime | None = None) -> bool:
    """根据开赛时间判断是否已开赛（历史比赛）。

    使用数据抓取时间作为参照，避免本地时钟/时区波动导致未开赛赛事被误判。
    """
    if not match_time:
        return False
    try:
        dt = datetime.strptime(match_time, "%Y-%m-%d %H:%M:%S")
        ref = fetched_at or datetime.now()
        return ref >= dt
    except ValueError:
        return False


def fetch_nba_spread(match_id: str) -> NbaSpreadMatch:
    """抓取并解析指定篮球比赛的让分数据。

    让分页面包含多组盘口（初盘、wholeLastOdds、wholeOdds）。解析器优先取
    ``wholeOdds`` 列：未开赛即当前即时盘口，历史比赛即赛前封盘盘口，从而
    避免赛后滚球盘口混入历史比赛的分析结果。
    """
    url = NBA_SPREAD_URL_TMPL.format(match_id=match_id)
    try:
        html = fetch_text(url, encoding="utf-8",
                          referer="https://nba.titan007.com/nba/index.aspx")
    except Exception as exc:
        msg = str(exc)
        if "502" in msg or "503" in msg or "504" in msg or "500" in msg:
            raise RuntimeError(
                f"该比赛让分盘口页暂不可用（服务端返回错误）。\n"
                f"可能原因：① 历史比赛 titan007 未保留让分盘口数据（可用「胜负」分析做往期验证）；"
                f"② 该场尚未开盘让分盘。\n原始信息：{msg}"
            )
        raise

    bookmakers = parse_spread_html(html)
    home, guest, match_time = fetch_nba_meta(match_id)
    fetched_at = datetime.now()
    return NbaSpreadMatch(
        match_id=str(match_id),
        hometeam=home,
        guestteam=guest,
        match_time=match_time,
        bookmakers=bookmakers,
        fetched_at=fetched_at.strftime("%Y-%m-%d %H:%M:%S"),
        is_historical=_is_historical_match(match_time, fetched_at),
    )
