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
from .config import BF_JC_URL, JC_RESULT_URL, JC_SCHEDULE_URL

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


def _parse_odds_jc_lottery(raw: str) -> dict[str, tuple[float | None, float | None, float | None]]:
    """从 odds_jc.txt 提取竞彩官方赔率，按 ScheduleID 索引。"""
    out: dict[str, tuple[float | None, float | None, float | None]] = {}
    for block in _SPLIT_RE.split(raw.strip()):
        if not block:
            continue
        fields = block.split("^")
        if not fields or not fields[0]:
            continue
        match_id = fields[0].strip()
        try:
            home = float(fields[1]) if len(fields) > 1 and fields[1].strip() else None
            draw = float(fields[2]) if len(fields) > 2 and fields[2].strip() else None
            away = float(fields[3]) if len(fields) > 3 and fields[3].strip() else None
        except ValueError:
            continue
        out[match_id] = (home, draw, away)
    return out


def _parse_bf_jc(raw: str) -> list[dict[str, object]]:
    """解析 bf_jc.txt，返回带官方编号（周X00N）的赛事列表。

    该文件是 jc.titan007.com 首页/赛程页实际使用的数据源，字段格式为：
    ``ScheduleID^MatchTime^UpdateTime^status^Label^LeagueID^...^HomeTeam^HomeID^AwayTeam^AwayID^...``
    以 ``!`` 分隔记录。只保留含 ``周X00N`` 标签的场次。
    """
    matches: list[dict[str, object]] = []
    for seg in raw.split("!"):
        if not seg:
            continue
        fields = seg.split("^")
        if len(fields) < 11:
            continue
        label_m = _LABEL_RE.search(fields[4]) if len(fields) > 4 else None
        if not label_m:
            continue
        label = label_m.group(0)
        match_id = fields[0].strip()
        home_names = fields[8].split(",") if len(fields) > 8 and fields[8] else [""]
        away_names = fields[10].split(",") if len(fields) > 10 and fields[10] else [""]
        matches.append(
            {
                "match_id": match_id,
                "label": label,
                "hometeam": home_names[0].strip(),
                "guestteam": away_names[0].strip(),
                "match_time": fields[1].strip() if len(fields) > 1 else "",
            }
        )
    return matches


def _list_today() -> list[dict[str, object]]:
    """获取今日竞彩足球列表。

    合并两个官方数据源：
    - ``bf_jc.txt``：titan007 赛程页实时数据源，带官方编号、对阵、联赛等信息；
      但**已完赛的前几场**（如周六001-005）会从这里消失。
    - ``JcResult.aspx?d=今天``：返回今日已完赛场次（含周六001-005）。

    两者按官方编号（周X00N）合并、去重，再用 ``odds_jc.txt`` 补竞彩官方赔率。
    同时按 ``bf_jc.txt`` 中的真实开赛日期过滤，避免把下周同一天（如下周六）的赛事混入。
    若两个官方源均不可用，回退到旧的 odds_jc.txt 顺序列表（无官方标签）。
    """
    today_dt = _today()
    today_wd = _WEEKDAY_LABELS[today_dt.weekday()]
    today_date_str = today_dt.strftime("%Y-%m-%d")

    def _match_date(match_time: str) -> str | None:
        """把 titan007 时间串 ``YYYY,M,D,H,M,S``（月份从0开始）转为 ``YYYY-MM-DD``。"""
        if not match_time:
            return None
        parts = match_time.split(",")
        if len(parts) < 3:
            return None
        try:
            year, month0, day = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{year}-{month0 + 1:02d}-{day:02d}"
        except ValueError:
            return None

    matches_by_label: dict[str, dict[str, object]] = {}

    # 数据源 1：bf_jc.txt（官方编号、对阵、开赛时间）
    try:
        raw_bf = fetch_text(BF_JC_URL, encoding="utf-8")
        for m in _parse_bf_jc(raw_bf):
            label = str(m.get("label") or "")
            if not label.startswith(today_wd):
                continue
            # 按真实日期过滤，防止混入下周同一天
            if _match_date(str(m.get("match_time") or "")) != today_date_str:
                continue
            matches_by_label[label] = m
    except Exception:
        pass

    # 数据源 2：JcResult.aspx（补充已完赛的场次，如周六001-005）
    try:
        referer = f"https://jc.titan007.com/schedule.aspx?d={today_date_str}"
        raw_jc = fetch_text(JC_RESULT_URL.format(date=today_date_str), encoding="utf-8", referer=referer)
        for m in _parse_jc_result(raw_jc):
            label = str(m.get("label") or "")
            if not label.startswith(today_wd):
                continue
            # JcResult 优先级高于 bf_jc（已完赛场次更权威），覆盖同标签
            matches_by_label[label] = m
    except Exception:
        pass

    # 两个官方源都失败时，回退旧的 odds_jc.txt 顺序列表
    if not matches_by_label:
        raw = fetch_text(JC_SCHEDULE_URL, encoding="gbk")
        matches: list[dict[str, object]] = []
        for block in _SPLIT_RE.split(raw.strip()):
            if not block:
                continue
            fields = block.split("^")
            if not fields or not fields[0]:
                continue
            match_id = fields[0].strip()
            try:
                matches.append(
                    {
                        "match_id": match_id,
                        "label": None,
                        "lottery_home": float(fields[1]) if len(fields) > 1 and fields[1].strip() else None,
                        "lottery_draw": float(fields[2]) if len(fields) > 2 and fields[2].strip() else None,
                        "lottery_away": float(fields[3]) if len(fields) > 3 and fields[3].strip() else None,
                    }
                )
            except ValueError:
                continue
        return matches

    # 按官方编号排序
    def _label_sort_key(m: dict[str, object]) -> int:
        label = str(m.get("label") or "")
        return int(label[2:]) if len(label) > 2 and label[2:].isdigit() else 0

    matches = sorted(matches_by_label.values(), key=_label_sort_key)

    # 补竞彩官方赔率（按 ScheduleID 合并）
    try:
        raw_odds = fetch_text(JC_SCHEDULE_URL, encoding="gbk")
        odds_map = _parse_odds_jc_lottery(raw_odds)
    except Exception:
        odds_map = {}

    for m in matches:
        home, draw, away = odds_map.get(str(m["match_id"]), (None, None, None))
        m.setdefault("lottery_home", home)
        m.setdefault("lottery_draw", draw)
        m.setdefault("lottery_away", away)

    return matches


def _parse_jc_result(raw: str) -> list[dict[str, object]]:
    """解析 JcResult.aspx 返回的文本，提取带官方编号、对阵的赛事列表。

    每场比赛以 ``!`` 分隔。数据有两种形态：
    - 首个比赛段通常有 29 个字段，ScheduleID 嵌在 ``subleague.aspx?sclassid={联赛ID}${ID}``
      （字段 5）里，队名分别在字段 13（主队）和 15（客队）。
    - 后续比赛段通常有 24 个字段，ScheduleID 在字段 0，队名在字段 8 / 10。
    """
    matches: list[dict[str, object]] = []
    for seg in raw.split("!"):
        if not seg:
            continue
        label_m = _LABEL_RE.search(seg)
        if not label_m:
            continue
        label = label_m.group(0)
        fields = seg.split("^")

        # 优先从 league URL 里取 ScheduleID（首个比赛段）
        url_m = _SUBLEAGUE_URL_RE.search(seg)
        if url_m:
            match_id = url_m.group(1)
        else:
            # 取 segment 中第一个 6-8 位数字（大多数比赛 ScheduleID 在字段 0）
            num_m = _MATCH_ID_RE.search(seg)
            if not num_m:
                continue
            match_id = num_m.group(1)

        # 队名：首个比赛段与其他段字段位置不同
        hometeam: str | None = None
        guestteam: str | None = None
        match_time = ""
        if len(fields) >= 16 and fields[5].startswith("subleague.aspx"):
            # 首个比赛段：字段 13/15 为队名，字段 6 为开赛时间
            hometeam = fields[13].split(",")[0].strip() if fields[13] else None
            guestteam = fields[15].split(",")[0].strip() if fields[15] else None
            match_time = fields[6].strip() if len(fields) > 6 else ""
        elif len(fields) >= 11:
            hometeam = fields[8].split(",")[0].strip() if fields[8] else None
            guestteam = fields[10].split(",")[0].strip() if fields[10] else None
            match_time = fields[1].strip() if len(fields) > 1 else ""

        matches.append(
            {
                "match_id": match_id,
                "label": label,
                "hometeam": hometeam,
                "guestteam": guestteam,
                "match_time": match_time,
            }
        )
    return matches


def _list_by_date(date_str: str) -> list[dict[str, object]]:
    """通过 JcResult.aspx 获取指定历史日期的赛事（含周X00N 标签与对阵）。"""
    referer = f"https://jc.titan007.com/schedule.aspx?d={date_str}"
    url = JC_RESULT_URL.format(date=date_str)
    raw = fetch_text(url, encoding="utf-8", referer=referer)
    matches = _parse_jc_result(raw)
    for m in matches:
        m.setdefault("lottery_home", None)
        m.setdefault("lottery_draw", None)
        m.setdefault("lottery_away", None)
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
          官方编号场次（标签精确匹配；历史日期走 JcResult.aspx，当天走 bf_jc.txt 官方编号源）。
        - ``015`` / ``15``：优先按「今天星期 + 序号」的官方编号定位（如今天周六则 015=周六015）；
          未命中时回退到当日列表第 N 位（可能与官网编号不一致，会给出提示）。
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

        # 优先按官方编号标签精确匹配；未命中再回退顺序索引
        hit = next((x for x in matches if x.get("label") == label), None)
        if hit is not None:
            note = f"已按官方编号定位到 {label}（{date_str}）"
        else:
            idx = index - 1
            if 0 <= idx < len(matches):
                hit = matches[idx]
                note = f"注意：未找到官方编号 {label}，已按列表第 {index} 位返回（可能与官网编号不一致）"

        if hit is None:
            raise ValueError(f"未找到 {label}（{date_str} 共 {len(matches)} 场）")

        return {
            "match_id": str(hit["match_id"]),
            "source": "weekday_number",
            "index": index,
            "weekday": _WEEKDAY_LABELS[target_weekday],
            "target_date": date_str,
            "label": label,
            "note": note,
        }

    # 3) 仅序号 → 当日列表，优先按「今天星期+序号」的官方标签定位
    m = _NUMBER_RE.search(ref)
    if m:
        index = int(m.group(1))
        matches = list_matches()
        if not matches:
            raise ValueError("当前竞彩列表为空")

        today_wd = _WEEKDAY_LABELS[today.weekday()]
        label = f"{today_wd}{index:03d}"
        hit = next((x for x in matches if x.get("label") == label), None)
        if hit is not None:
            return {
                "match_id": str(hit["match_id"]),
                "source": "number",
                "index": index,
                "weekday": today_wd,
                "target_date": _today_str(),
                "label": label,
                "note": f"已按官方编号定位到 {label}",
            }

        # 标签未命中时回退到顺序索引（旧行为），并给出提示
        idx = index - 1
        if idx < 0 or idx >= len(matches):
            raise ValueError(f"未找到 {label}，当前共 {len(matches)} 场")
        return {
            "match_id": str(matches[idx]["match_id"]),
            "source": "number",
            "index": index,
            "weekday": today_wd,
            "target_date": _today_str(),
            "label": None,
            "note": f"注意：未找到官方编号 {label}，已按列表第 {index} 位返回（可能与官网编号不一致）",
        }

    raise ValueError(f"无法识别输入：{ref}")
