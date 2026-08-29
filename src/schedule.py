"""解析竞彩赛事列表。

两个数据来源（球探体育 titan007）：
- 当日列表：``jc.titan007.com/xml/odds_jc.txt``（GBK）。每场以 ``!`` 分隔，字段以 ``^`` 分隔，
  首段字段为 ``ScheduleID ^ 竞彩胜 ^ 竞彩平 ^ 竞彩负 ^ ...``。**不含「周X00N」标签字段**，
  但当日列表顺序天然对应 周X001、周X002……（按序号定位即可）。
- 指定日期列表：``jc.titan007.com/handle/JcResult.aspx?d=YYYY-MM-DD``（**UTF-8**）。
  由 schedule.aspx 内部加载，返回该日期的赛事，每条记录**自带「周X00N」标签**，可用于定位历史比赛。
  ⚠️ 该接口返回的「开赛时间」字段有 -1 个月的显示偏移，真实时间以单场欧指 JS 的 MatchTime 为准。

``list_matches(date=None)`` 据此自动路由：未给日期或当天 → 用 odds_jc.txt；历史日期 → 用 JcResult.aspx。
``resolve_match_ref(ref)`` 把「周六015 / 周五001 / 015 / 3000426」等解析为 ScheduleID，
其中「周X+序号」会按真实日历日期定位到对应那一天的那一场。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .client import fetch_text
from .config import JC_RESULT_URL, JC_SCHEDULE_URL

_SPLIT_RE = re.compile(r"\s*\!\s*")

_WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
# 单字/数字到 weekday 索引（周一=0 ... 周日=6）
_WEEKDAY_CHAR_MAP = {
    **{name[-1]: i for i, name in enumerate(_WEEKDAY_LABELS)},  # 一..日
    **{str(i): i - 1 for i in range(1, 8)},  # 1..7（周一=1）
}

_WEEKDAY_RE = re.compile(r"(?:周|星期|礼拜)\s*([一二三四五六日1234567])\s*(\d{1,3})")
_NUMBER_RE = re.compile(r"(?:^|[^\d])(\d{1,3})(?:[^\d]|$)")
_DIRECT_ID_RE = re.compile(r"\b(\d{6,})\b")
_LABEL_RE = re.compile(r"周[一二三四五六日]\d{1,3}")
# JcResult.aspx 中每场比赛以 "!" 分隔；第一个比赛把 ScheduleID 放在
# subleague.aspx?sclassid={联赛ID}${ScheduleID} 里，其余比赛 ScheduleID 在字段 0。
_SUBLEAGUE_URL_RE = re.compile(r"subleague\.aspx\?sclassid=\d+\$(\d{6,8})")
_MATCH_ID_RE = re.compile(r"\b(\d{6,8})\b")


def _today() -> datetime:
    return datetime.now()


def _today_str() -> str:
    return _today().strftime("%Y-%m-%d")


def _most_recent_weekday(today: datetime, weekday: int) -> datetime:
    """返回不晚于 today 的最近一个 weekday（today 本身若匹配也算）。"""
    days_back = (today.weekday() - weekday) % 7
    return today - timedelta(days=days_back)


def list_matches(date: str | None = None) -> list[dict[str, object]]:
    """获取竞彩赛事列表。

    Args:
        date: ``YYYY-MM-DD`` 格式的目标日期。``None`` 或当天 → 取当日列表（odds_jc.txt）；
            其它历史日期 → 取该日期列表（JcResult.aspx，含周X00N 标签）。

    Returns:
        列表，每项至少含 ``match_id``；当日项含 ``lottery_home/draw/away``，
        历史项含 ``label``（周X00N）。赔率可能为空字符串（未开售），对应值为 ``None``。
    """
    if date is None or date == _today_str():
        return _list_today()
    return _list_by_date(date)


def _list_today() -> list[dict[str, object]]:
    raw = fetch_text(JC_SCHEDULE_URL, encoding="gbk")
    matches: list[dict[str, object]] = []
    for block in _SPLIT_RE.split(raw.strip()):
        if not block:
            continue
        fields = block.split("^")
        if not fields or not fields[0]:
            continue
        match_id = fields[0].strip()

        def _to_float(v: str) -> float | None:
            v = v.strip()
            return float(v) if v else None

        try:
            matches.append(
                {
                    "match_id": match_id,
                    "label": None,
                    "lottery_home": _to_float(fields[1]) if len(fields) > 1 else None,
                    "lottery_draw": _to_float(fields[2]) if len(fields) > 2 else None,
                    "lottery_away": _to_float(fields[3]) if len(fields) > 3 else None,
                }
            )
        except ValueError:
            continue
    return matches


def _list_by_date(date_str: str) -> list[dict[str, object]]:
    """通过 JcResult.aspx 获取指定历史日期的赛事（含周X00N 标签）。

    数据结构：每场比赛以 ``!`` 分隔；每个 segment 中自带 ``周X00N`` 标签。
    第一个比赛较特殊，ScheduleID 嵌入在 ``subleague.aspx?sclassid={联赛ID}${ID}``
    链接里；其余比赛 ScheduleID 通常位于 segment 首字段。

    注：该接口 Content-Type 为 UTF-8（与当日 odds_jc.txt 的 GBK 不同），须用 UTF-8 解码。
    """
    referer = f"https://jc.titan007.com/schedule.aspx?d={date_str}"
    url = JC_RESULT_URL.format(date=date_str)
    raw = fetch_text(url, encoding="utf-8", referer=referer)
    matches: list[dict[str, object]] = []
    for seg in raw.split("!"):
        if not seg:
            continue
        label_m = _LABEL_RE.search(seg)
        if not label_m:
            continue
        label = label_m.group(0)

        # 优先从 league URL 里取 ScheduleID（周五001这种情况）
        url_m = _SUBLEAGUE_URL_RE.search(seg)
        if url_m:
            match_id = url_m.group(1)
        else:
            # 取 segment 中第一个 6-8 位数字（大多数比赛 ScheduleID 在字段 0）
            num_m = _MATCH_ID_RE.search(seg)
            if not num_m:
                continue
            match_id = num_m.group(1)

        matches.append(
            {
                "match_id": match_id,
                "label": label,
                "lottery_home": None,
                "lottery_draw": None,
                "lottery_away": None,
            }
        )
    return matches


def first_match() -> dict[str, object] | None:
    """返回当日列表中的第一场比赛（即用户说的「第一场比赛」）。"""
    matches = list_matches()
    return matches[0] if matches else None


def match_id_from_url(url: str) -> str:
    """从 oddslist URL 中提取 ScheduleID。

    Example:
        ``https://op1.titan007.com/oddslist/3000426.htm`` -> ``"3000426"``
    """
    m = re.search(r"/oddslist/(\d+)\.htm", url)
    if not m:
        raise ValueError(f"无法从 URL 解析比赛 ID: {url}")
    return m.group(1)


def resolve_match_ref(ref: str, today: datetime | None = None) -> dict[str, object]:
    """把用户输入的场次描述解析为 ScheduleID。

    支持格式：
        - ``周六015`` / ``星期6 15`` / ``周五001``：按真实日历日期定位到「该星期最近一次出现那天」的
          第 N 场（标签精确匹配；历史日期走 JcResult.aspx，当天走当日列表按序号）。
        - ``015`` / ``15``：直接用**当日**列表第 N 场。
        - ``3000426``：直接按 ScheduleID 分析。
        - 自由文本中会自动提取上述任意一种标识，例如 ``@image#1:xxx.png 周五001``。

    Returns:
        ``{"match_id": str, "source": str, "index": int|None, "weekday": str|None,
           "target_date": str|None, "label": str|None, "note": str|None}``
    """
    ref = ref.strip()
    if not ref:
        raise ValueError("输入为空")

    today = today or _today()

    # 1) 直接 ScheduleID（6 位及以上数字）
    m = _DIRECT_ID_RE.search(ref)
    if m:
        match_id = m.group(1)
        matches = list_matches()
        in_list = any(str(mm["match_id"]) == match_id for mm in matches)
        note: str | None = None
        if not in_list:
            note = f"ID {match_id} 不在当日竞彩列表中，将直接按该 ID 抓取分析（也适用于历史比赛）。"
        return {
            "match_id": match_id,
            "source": "direct",
            "index": None,
            "weekday": None,
            "target_date": None,
            "label": None,
            "note": note,
        }

    # 2) 星期 + 序号（如 周五001 / 周六015）
    m = _WEEKDAY_RE.search(ref)
    if m:
        weekday_token, num_str = m.group(1), m.group(2)
        target_weekday = _WEEKDAY_CHAR_MAP.get(weekday_token)
        if target_weekday is None:
            raise ValueError(f"无法识别星期：{weekday_token}")
        index = int(num_str)
        target_date = _most_recent_weekday(today, target_weekday)
        date_str = target_date.strftime("%Y-%m-%d")
        label = f"{_WEEKDAY_LABELS[target_weekday]}{index:03d}"

        matches = list_matches(date_str)
        if not matches:
            raise ValueError(f"{label}（{date_str}）未获取到赛事列表，可能该日无竞彩或接口不可用。")

        # 优先按标签精确匹配（历史日期自带标签；当天列表无标签则回退序号）
        hit = next((x for x in matches if x.get("label") == label), None)
        if hit is None:
            idx = index - 1
            if 0 <= idx < len(matches):
                hit = matches[idx]

        if hit is None:
            raise ValueError(f"未找到 {label}（{date_str} 共 {len(matches)} 场）")

        note = f"已按标签定位到 {label}（{date_str}）"
        return {
            "match_id": str(hit["match_id"]),
            "source": "weekday_number",
            "index": index,
            "weekday": _WEEKDAY_LABELS[target_weekday],
            "target_date": date_str,
            "label": label,
            "note": note,
        }

    # 3) 仅序号 → 当日列表
    m = _NUMBER_RE.search(ref)
    if m:
        index = int(m.group(1))
        matches = list_matches()
        if not matches:
            raise ValueError("当前竞彩列表为空")
        idx = index - 1
        if idx < 0 or idx >= len(matches):
            raise ValueError(f"序号 {index} 超出范围，当前共 {len(matches)} 场")
        return {
            "match_id": str(matches[idx]["match_id"]),
            "source": "number",
            "index": index,
            "weekday": None,
            "target_date": None,
            "label": None,
            "note": None,
        }

    raise ValueError(f"无法识别输入：{ref}")
