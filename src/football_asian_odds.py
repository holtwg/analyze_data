"""解析单场足球亚洲盘(让球)数据。

数据来源：``vip.titan007.com/AsianOdds_n.aspx?id={match_id}&l=0``（HTML 表格，UTF-8）。
该页以 HTML ``<tr>`` 表格展示各公司让球盘口，每行含：

- 公司名（``companyID`` 标记位之前的 td）
- 初盘：上盘水位 / ``goals`` 让球描述 / 下盘水位
- 即时盘：``oddstype="wholeLastOdds"`` 的三个 td
- 终盘：``oddstype="wholeOdds"`` 的三个 td（隐藏 ``display:none``）

``goals`` 属性直接给出数值化让球（主队视角，``>0`` 主让、``<0`` 客让），
无需解析中文描述。优先取终盘（赛前封盘/赛后终盘），缺失时回退即时盘，
与篮球让分逻辑保持一致。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .client import fetch_text
from .config import FOOTBALL_ASIAN_URL_TMPL, LOTTERY_KEYWORDS


@dataclass(slots=True)
class AsianBookmaker:
    """单家博彩公司的足球亚盘快照。"""

    company_cn: str
    company_en: str
    goals: float          # 让球（主队视角，>0 主让，<0 客让）
    up: float             # 上盘(让球方)水位
    down: float           # 下盘(受让方)水位
    is_lottery: bool

    @property
    def name(self) -> str:
        return self.company_cn or self.company_en


def _text(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t).strip()


def _f(v: str) -> float | None:
    v = v.strip()
    if v in ("", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_asian_html(html: str) -> list[AsianBookmaker]:
    """从亚盘 HTML 表格解析各公司让球盘口。

    ``goals``（数值让球）与 ``oddstype`` 都在 ``<td>`` 标签属性上，不在 td 文本内，
    因此需从标签属性提取。每行带 oddstype 的 td 共 3 个（上盘水位 / 让球描述 /
    下盘水位），其中中间的 td 带 ``goals`` 属性。
    """
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    out: list[AsianBookmaker] = []
    for row in rows:
        if "companyID" not in row:
            continue
        # 提取每个带 oddstype 的 td：(oddstype, goals, 文本)
        tds = re.findall(r"<td\b([^>]*)>(.*?)</td>", row, re.DOTALL)
        odds: list[tuple[str, str | None, str]] = []
        for attrs, body in tds:
            ot = re.search(r'oddstype="(\w+)"', attrs)
            if not ot:
                continue
            gm = re.search(r'goals="([-\d.]+)"', attrs)
            odds.append((ot.group(1), gm.group(1) if gm else None, body))
        if not odds:
            continue
        whole = [x for x in odds if x[0] == "wholeOdds"]
        last = [x for x in odds if x[0] == "wholeLastOdds"]
        use = whole if whole else last  # 优先终盘
        if len(use) < 3:
            continue
        up = _f(_text(use[0][2]))
        down = _f(_text(use[2][2]))
        goals = float(use[1][1]) if use[1][1] else None
        if up is None or down is None or goals is None:
            continue
        # 水位合理性校验（香港盘水位区间）
        if not (0.3 < up < 5 and 0.3 < down < 5):
            continue
        tds_all = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        name = _text(tds_all[1]) if len(tds_all) > 1 else ""
        is_lottery = any(kw in name for kw in LOTTERY_KEYWORDS)
        out.append(
            AsianBookmaker(
                company_cn=name,
                company_en="",
                goals=goals,
                up=up,
                down=down,
                is_lottery=is_lottery,
            )
        )
    return out


def fetch_football_asian(match_id: str) -> list[AsianBookmaker]:
    """抓取并解析指定比赛的足球亚盘数据。"""
    url = FOOTBALL_ASIAN_URL_TMPL.format(match_id=match_id)
    html = fetch_text(
        url, encoding="utf-8", referer=f"https://op1.titan007.com/oddslist/{match_id}.htm"
    )
    return parse_asian_html(html)
