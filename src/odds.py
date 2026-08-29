"""解析单场百家欧指数据 JS（1x2d.titan007.com/{match_id}.js）。

``game`` 数组每行 27 个字段，管道符分隔。已验证字段含义如下（索引从 0 起）：

==== ================================= ========================
idx  含义                                说明
==== ================================= ========================
0    公司 ID
2    公司英文名
3,4,5 初盘 主/和/客 赔率
6,7,8 初盘 主胜率/和率/客胜率(%)        去水后的隐含概率
9    初盘 返还率(%)
10,11,12 即时 主/和/客 赔率
13,14,15 即时 主胜率/和率/客胜率(%)     去水后的隐含概率（核心分析用）
16   即时 返还率(%)
17,18,19 即时 凯利 主/和/客
20   更新时间
21   公司中文名
24,25,26 初盘 凯利 主/和/客
==== ================================= ========================

注意：网站给出的「主胜率/和率/客胜率」已是 ``(1/赔率)/Σ(1/赔率)`` 的去水概率，
可直接作为各公司的隐含概率使用。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime

from .client import fetch_text
from .config import LOTTERY_KEYWORDS, ODDS_JS_URL

_GAME_RE = re.compile(r"var\s+game\s*=\s*Array\((.*?)\)\s*;", re.DOTALL)


@dataclass(slots=True)
class BookmakerOdds:
    """单家博彩公司的欧指快照。"""

    company_id: int
    company_en: str
    company_cn: str
    live_home: float
    live_draw: float
    live_away: float
    live_prob_home: float  # 去水隐含概率 %
    live_prob_draw: float
    live_prob_away: float
    live_return: float  # 返还率 %
    kelly_home: float
    kelly_draw: float
    kelly_away: float
    update_time: str
    is_lottery: bool

    @property
    def name(self) -> str:
        return self.company_cn or self.company_en


@dataclass(slots=True)
class MatchOdds:
    """一场比赛的全部欧指数据。"""

    match_id: str
    hometeam: str
    guestteam: str
    match_time: str
    bookmakers: list[BookmakerOdds]
    fetched_at: str = ""  # 数据抓取时间（本地时间），用于判断数据新鲜度

    @property
    def lottery(self) -> BookmakerOdds | None:
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


def parse_game(js_text: str) -> list[BookmakerOdds]:
    """从 JS 文本中解析出所有公司的欧指。"""
    m = _GAME_RE.search(js_text)
    if not m:
        raise ValueError("未在数据中找到 game 数组，可能页面结构已变或比赛 ID 有误")
    inner = m.group(1)
    # 元素以 "," 连接，但元素内部用 | 分隔，不含逗号，故可直接按 "," 切
    items = inner.split('","')
    items[0] = items[0].lstrip('"')
    items[-1] = items[-1].rstrip('"')

    rows: list[BookmakerOdds] = []
    for it in items:
        f = it.split("|")
        if len(f) < 22:
            continue
        try:
            company_id = int(f[0])
        except ValueError:
            continue
        # 核心字段缺失则跳过该家公司
        live_home = _f(f[10])
        live_draw = _f(f[11])
        live_away = _f(f[12])
        if None in (live_home, live_draw, live_away):
            continue

        cn = f[21] if len(f) > 21 else f[2]
        is_lottery = any(kw in cn or kw in f[2] for kw in LOTTERY_KEYWORDS)

        rows.append(
            BookmakerOdds(
                company_id=company_id,
                company_en=f[2],
                company_cn=cn,
                live_home=live_home,
                live_draw=live_draw,
                live_away=live_away,
                live_prob_home=_f(f[13]) or 0.0,
                live_prob_draw=_f(f[14]) or 0.0,
                live_prob_away=_f(f[15]) or 0.0,
                live_return=_f(f[16]) or 0.0,
                kelly_home=_f(f[17]) or 0.0,
                kelly_draw=_f(f[18]) or 0.0,
                kelly_away=_f(f[19]) or 0.0,
                update_time=f[20],
                is_lottery=is_lottery,
            )
        )
    return rows


def _meta(js_text: str) -> tuple[str, str, str]:
    """提取队名与开赛时间。"""

    def _var(name: str) -> str:
        mm = re.search(rf"var\s+{name}\s*=\s*\"?([^\";\n]+)\"?\s*;", js_text)
        return mm.group(1).strip().strip('"') if mm else ""

    home = _var("hometeam_cn") or _var("hometeam")
    guest = _var("guestteam_cn") or _var("guestteam")
    match_time = _var("MatchTime")
    return home, guest, match_time


def fetch_match_odds(match_id: str) -> MatchOdds:
    """抓取并解析指定比赛的百家欧指。

    每次调用都重新发起 HTTP 请求（无本地缓存），并附带 ``?_=<时间戳>`` 参数
    以绕过任何 CDN/浏览器层面的缓存，确保拿到 titan007 服务端此时返回的最新赔率。
    """
    url = f"{ODDS_JS_URL.format(match_id=match_id)}?_={int(time.time() * 1000)}"
    js = fetch_text(url, encoding="utf-8", referer_match_id=match_id)
    bookmakers = parse_game(js)
    home, guest, match_time = _meta(js)
    lottery_update = next((b.update_time for b in bookmakers if b.is_lottery), "")
    return MatchOdds(
        match_id=match_id,
        hometeam=home,
        guestteam=guest,
        match_time=match_time,
        bookmakers=bookmakers,
        fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        # 注：lottery_update 仅用于报告展示，analyze 内部也会重新读取 lottery 行
    )
