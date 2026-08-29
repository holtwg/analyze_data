"""解析单场篮球胜负(moneyline)数据 JS。

数据来源：``nba.titan007.com/1x2/data1x2/{a}/{b}/{match_id}.js``（UTF-8）。

``game`` 数组每行以 ``|`` 分隔，已验证字段含义（2-way，无平局）：

==== ================================= ========================
idx  含义                                说明
==== ================================= ========================
0    公司 ID
1    变化 ID
2    (空 / 标记位)
3    即时 主胜赔率
4    即时 客胜赔率
5    即时 主胜率(%)                        去水后的隐含概率
6    即时 客胜率(%)                        去水后的隐含概率
7    即时 返还率(%)
8    初盘 主胜赔率
9    初盘 客胜赔率
10   初盘 主胜率(%)
11   初盘 客胜率(%)
12   初盘 返还率(%)
13   即时 主凯利
14   即时 客凯利
15   更新时间
16   公司中文名
17   (标记位)
18   (标记位)
19   公司英文名
==== ================================= ========================

注意：
- 网站给出的「主胜率/客胜率」已是 ``(1/赔率)/(1/主赔+1/客赔)`` 的去水概率，可直接聚合求市场共识。
- 竞彩官* 行即体彩胜负赔率（主胜/客胜），用于体彩价值分析。
- ``MatchTime`` 形如 ``2026,08-1,29,17,00,00``，月份字段带 ``-1`` 后缀（站点显示偏移），
  解析时取 ``-`` 之前的部分作为 1 索引月份。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime

from .client import fetch_text
from .config import (
    LOTTERY_KEYWORDS,
    NBA_1X2_JS_TMPL,
    NBA_ODDS_LIST_PAGE,
)


def nba_1x2_js_url(match_id: str) -> str:
    """由 ScheduleID 构造胜负数据 JS 地址。"""
    mid = str(match_id)
    return NBA_1X2_JS_TMPL.format(a=mid[0], b=mid[1:3], match_id=mid)


_GAME_RE = re.compile(r"var\s+game\s*=\s*Array\((.*?)\)\s*;", re.DOTALL)


@dataclass(slots=True)
class NbaBookmakerOdds:
    """单家博彩公司的篮球胜负快照。"""

    company_id: int
    company_en: str
    company_cn: str
    live_home: float          # 即时主胜赔率
    live_away: float          # 即时客胜赔率
    live_prob_home: float     # 去水隐含主胜率 %
    live_prob_away: float     # 去水隐含客胜率 %
    live_return: float        # 返还率 %
    kelly_home: float
    kelly_away: float
    update_time: str
    is_lottery: bool

    @property
    def name(self) -> str:
        return self.company_cn or self.company_en


@dataclass(slots=True)
class NbaMatchOdds:
    """一场篮球比赛的全部胜负数据。"""

    match_id: str
    hometeam: str
    guestteam: str
    match_time: str
    bookmakers: list[NbaBookmakerOdds]
    fetched_at: str = ""

    @property
    def lottery(self) -> NbaBookmakerOdds | None:
        for b in self.bookmakers:
            if b.is_lottery:
                return b
        return None


def _f(v: str) -> float | None:
    v = v.strip()
    if v == "" or v == "-":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_nba_game(js_text: str) -> list[NbaBookmakerOdds]:
    """从 JS 解析所有公司的篮球胜负赔率。"""
    m = _GAME_RE.search(js_text)
    if not m:
        raise ValueError("未在数据中找到 game 数组，可能页面结构已变或比赛 ID 有误")
    inner = m.group(1)
    items = inner.split('","')
    items[0] = items[0].lstrip('"')
    items[-1] = items[-1].rstrip('"')

    rows: list[NbaBookmakerOdds] = []
    for it in items:
        f = it.split("|")
        if len(f) < 17:
            continue
        try:
            company_id = int(f[0])
        except ValueError:
            continue
        live_home = _f(f[3])
        live_away = _f(f[4])
        if None in (live_home, live_away):
            continue

        cn = f[16] if len(f) > 16 else ""
        en = f[19] if len(f) > 19 else ""
        is_lottery = any(kw in cn or kw in en for kw in LOTTERY_KEYWORDS)

        rows.append(
            NbaBookmakerOdds(
                company_id=company_id,
                company_en=en,
                company_cn=cn,
                live_home=live_home,
                live_away=live_away,
                live_prob_home=_f(f[5]) or 0.0,
                live_prob_away=_f(f[6]) or 0.0,
                live_return=_f(f[7]) or 0.0,
                kelly_home=_f(f[13]) or 0.0,
                kelly_away=_f(f[14]) or 0.0,
                update_time=f[15] if len(f) > 15 else "",
                is_lottery=is_lottery,
            )
        )
    return rows


def _parse_match_time(raw: str) -> str:
    """解析 MatchTime（兼容 ``2026,08-1,29,17,00,00`` 这种月份带 -1 后缀的格式）。"""
    raw = raw.strip().strip('"')
    if not raw:
        return ""
    parts = raw.split(",")
    if len(parts) < 6:
        return raw
    year = parts[0].strip()
    month_raw = parts[1].strip()           # 形如 08-1
    # 取 -/+ 之前的部分作为 1 索引月份（去除站点显示偏移后缀）
    month = re.split(r"[-+]", month_raw)[0]
    day = parts[2].strip()
    hh, mm, ss = parts[3].strip(), parts[4].strip(), parts[5].strip()
    return f"{year}-{month.zfill(2)}-{day.zfill(2)} {hh}:{mm}:{ss}"


def _meta(js_text: str) -> tuple[str, str, str]:
    """提取队名（优先中文）与开赛时间。"""

    def _var(name: str) -> str:
        mm = re.search(rf"var\s+{name}\s*=\s*\"?([^\";\n]+)\"?\s*;", js_text)
        return mm.group(1).strip().strip('"') if mm else ""

    home = _var("hometeam_cn") or _var("hometeam")
    guest = _var("guestteam_cn") or _var("guestteam")
    match_time = _parse_match_time(_var("MatchTime"))
    return home, guest, match_time


def fetch_nba_match_odds(match_id: str) -> NbaMatchOdds:
    """抓取并解析指定篮球比赛的胜负数据（每次重新实时抓取，带防缓存时间戳）。"""
    base = nba_1x2_js_url(match_id)
    url = f"{base}?_={int(time.time() * 1000)}"
    referer = NBA_ODDS_LIST_PAGE.format(match_id=match_id)
    js = fetch_text(url, encoding="utf-8", referer=referer)
    bookmakers = parse_nba_game(js)
    home, guest, match_time = _meta(js)
    return NbaMatchOdds(
        match_id=str(match_id),
        hometeam=home,
        guestteam=guest,
        match_time=match_time,
        bookmakers=bookmakers,
        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def fetch_nba_meta(match_id: str) -> tuple[str, str, str]:
    """仅抓取队名与开赛时间（用于赛事列表展示，避免拉取整份 game 数组）。"""
    base = nba_1x2_js_url(match_id)
    url = f"{base}?_={int(time.time() * 1000)}"
    referer = NBA_ODDS_LIST_PAGE.format(match_id=match_id)
    js = fetch_text(url, encoding="utf-8", referer=referer)
    return _meta(js)
