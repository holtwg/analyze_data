"""解析竞彩篮球赛事列表与场次输入。

数据源（球探体育 titan007，竞彩官方）：
- 当日竞彩篮球列表：``bf_jc_lq.txt``（UTF-8），仅含竞彩开售场次，编号 周六301 起。
- 历史/指定日期：``JcResult.aspx?d=YYYY-MM-DD&st=2``（UTF-8），
  返回当日全部竞彩（足球+篮球混合），需按联赛筛选篮球场次。

``list_nba_matches()`` 返回当日竞彩篮球（按竞彩统一编号 301+）。
``resolve_nba_ref(ref)`` 解析「周六301 / 301 / 728077」为 ScheduleID。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .client import fetch_text
from .config import NBA_LOTTERY_LIST_URL, NBA_HISTORY_URL_TMPL
from .nba_odds import fetch_nba_meta

_WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_WEEKDAY_CHAR_MAP = {
    **{name[-1]: i for i, name in enumerate(_WEEKDAY_LABELS)},
    **{str(i): i - 1 for i in range(1, 8)},
}
_WEEKDAY_RE = re.compile(r"(?:周|星期|礼拜)\s*([一二三四五六日1234567])\s*(\d{1,3})")
_DIRECT_ID_RE = re.compile(r"\b(\d{6,})\b")
_NUMBER_RE = re.compile(r"(?:^|[^\d])(\d{1,3})(?:[^\d]|$)")
_SEG_RE = re.compile(r"(?:^|[\$!])(\d{6,8})")   # 单场 ScheduleID 标记（段首或 $/! 后）
_LABEL_RE = re.compile(r"周[一二三四五六日]\s*\d{2,3}")
_LEAGUE_PREFIX_RE = re.compile(r"(?:^|!|\$)(\d+)\^#?[0-9A-Fa-f]*\^([^!$\^]+?)\^")
# 篮球联赛关键词 + 已知联赛 ID 白名单（用于从历史混合列表中筛篮球）。
# 世亚预/世欧预/世女杯等杯赛名称不含"篮"字，但属于篮球赛事，需按 ID 识别。
_BASKET_KEYWORDS = ("篮", "WNBA", "NBA", "美职篮", "Basketball", "Basket")
_BASKETBALL_LEAGUE_IDS = {"2", "219", "406", "408"}

NUMBER_BASE = 301
_JC_REFERER = "https://jc.titan007.com/nba/index.aspx"


def _today() -> datetime:
    return datetime.now()


def _last_weekday_date(weekday_idx: int) -> datetime:
    """返回最近一个指定星期几的日期（可为今天，或过去最近）。"""
    today = _today()
    days_back = (today.weekday() - weekday_idx) % 7
    return today - timedelta(days=days_back)


def _iter_matches(raw: str):
    """从原始文本产出每场比赛 {match_id, label, league_id}。"""
    for seg in raw.split("!"):
        m = _SEG_RE.search(seg)
        if not m:
            continue
        sid = m.group(1)
        label_m = _LABEL_RE.search(seg)
        label = label_m.group(0).replace(" ", "") if label_m else None
        league_id = None
        if label_m:
            after = seg[label_m.end():]
            lm = re.search(r"\^(\d+)\^", after)
            if lm:
                league_id = lm.group(1)
        yield {"match_id": sid, "label": label, "league_id": league_id}


def _collect_leagues(raw: str) -> dict[str, str]:
    """扫描联赛前缀段，返回 {league_id: league_name}。"""
    out: dict[str, str] = {}
    for m in _LEAGUE_PREFIX_RE.finditer(raw):
        out[m.group(1)] = m.group(2)
    return out


def _is_basketball(league_id: str | None, leagues: dict[str, str]) -> bool:
    if not league_id:
        return False
    if league_id in _BASKETBALL_LEAGUE_IDS:
        return True
    name = leagues.get(league_id, "")
    return any(kw in name for kw in _BASKET_KEYWORDS)


def list_nba_matches(verbose: bool = True) -> list[dict[str, object]]:
    """当日竞彩篮球赛事列表（已为竞彩开售场次，编号 周六301 起）。"""
    raw = fetch_text(NBA_LOTTERY_LIST_URL, encoding="utf-8", referer=_JC_REFERER)
    out: list[dict[str, object]] = []
    for i, m in enumerate(_iter_matches(raw)):
        number = NUMBER_BASE + i
        item: dict[str, object] = {
            "match_id": m["match_id"],
            "number": number,
            "label": m["label"] or f"周六{number:03d}",
        }
        if verbose:
            try:
                home, away, mt = fetch_nba_meta(m["match_id"])
            except Exception:
                home = away = mt = ""
            item["home"] = home
            item["away"] = away
            item["match_time"] = mt
        out.append(item)
    return out


def first_nba_match() -> dict[str, object] | None:
    matches = list_nba_matches(verbose=False)
    return matches[0] if matches else None


def list_nba_matches_by_date(date_str: str) -> list[dict[str, object]]:
    """按指定日期列出当日竞彩篮球（用于往期赛事浏览/验证）。

    ``date_str`` 形如 ``2026-08-28``。返回 [{match_id, number, label, ...}]。
    数据来自 ``JcResult.aspx?d=日期&st=2``，按联赛关键词筛选「篮球」场次。

    注意：``label`` 即竞彩统一编号（周五301、周五302…），不区分足球/篮球，
    本函数已通过联赛关键词 + 已知篮球联赛 ID 白名单过滤出篮球场次。
    """
    raw = fetch_text(NBA_HISTORY_URL_TMPL.format(date=date_str), encoding="utf-8",
                     referer=_JC_REFERER)
    leagues = _collect_leagues(raw)
    out: list[dict[str, object]] = []
    for m in _iter_matches(raw):
        if not _is_basketball(m["league_id"], leagues):
            continue
        label = m["label"] or f"篮球{m['match_id']}"
        number = int(label[-3:]) if label[-3:].isdigit() else 0
        out.append({
            "match_id": m["match_id"],
            "number": number,
            "label": label,
            "league_id": m["league_id"],
        })
    out.sort(key=lambda x: x["number"])
    return out


def match_id_from_nba_url(url: str) -> str:
    m = re.search(r"/1x2/oddslist/(\d+)\.htm", url)
    if not m:
        raise ValueError(f"无法从 URL 解析比赛 ID: {url}")
    return m.group(1)


def _resolve_by_label(raw: str, target_label: str, *, source: str,
                      target_date: str | None = None) -> dict[str, object]:
    """在当日 bf_jc_lq.txt 文本中按竞彩场次号标签定位单场。"""
    found = None
    for m in _iter_matches(raw):
        if m["label"] == target_label:
            found = m
            break
    if found is None:
        avail = [m["label"] for m in _iter_matches(raw) if m["label"]]
        raise ValueError(
            f"未找到竞彩场次 {target_label}"
            + (f"（该日竞彩篮球场次：{', '.join(avail)}）" if avail else "（该日无竞彩篮球场次）")
        )
    note = f"已按竞彩场次号定位到 {target_label}"
    if target_date:
        note += f"（{target_date}）"
    return {
        "match_id": found["match_id"],
        "source": source,
        "number": int(target_label[-3:]) if target_label[-3:].isdigit() else None,
        "weekday": target_label[:2],
        "label": target_label,
        "target_date": target_date,
        "note": note,
    }


def _resolve_historical_by_date(date_str: str, target_label: str, *, source: str) -> dict[str, object]:
    """按日期解析篮球历史场次号（竞彩统一编号，如周五301）。"""
    matches = list_nba_matches_by_date(date_str)
    if not matches:
        raise ValueError(f"{date_str} 暂无竞彩篮球赛事记录。")

    found = next((m for m in matches if m.get("label") == target_label), None)
    if found is None:
        avail = ", ".join(str(m.get("label")) for m in matches)
        raise ValueError(
            f"未找到 {target_label}。\n"
            f"该日竞彩篮球场次：{avail}\n"
            f"也可直接输入比赛 ID（如 728077）。"
        )

    note = f"已定位到 {target_label}（{date_str}）"
    return {
        "match_id": found["match_id"],
        "source": source,
        "number": int(target_label[-3:]) if target_label[-3:].isdigit() else None,
        "weekday": target_label[:2],
        "label": str(found["label"]),
        "target_date": date_str,
        "note": note,
    }


def resolve_nba_ref(ref: str) -> dict[str, object]:
    """解析用户输入为 ScheduleID。

    支持：
        - ``周六301`` / ``星期6 1``：竞彩统一编号（当日从 bf_jc_lq.txt 定位；
          非今日从 JcResult?st=2 按篮球联赛过滤后定位）。
        - ``301``：当日竞彩场次号（周六301 等）。
        - ``728077`` / ``705225``：直接 ScheduleID（亦适用于历史比赛）。
    """
    ref = ref.strip()
    if not ref:
        raise ValueError("输入为空")

    # 1) 直接 ScheduleID
    m = _DIRECT_ID_RE.search(ref)
    if m:
        return {
            "match_id": m.group(1),
            "source": "direct",
            "number": None,
            "weekday": None,
            "label": None,
            "target_date": None,
            "note": None,
        }

    # 2) 星期 + 序号
    m = _WEEKDAY_RE.search(ref)
    if m:
        wt, num_str = m.group(1), m.group(2)
        target_wd = _WEEKDAY_CHAR_MAP.get(wt)
        if target_wd is None:
            raise ValueError(f"无法识别星期：{wt}")
        num = int(num_str)
        target_label = f"{_WEEKDAY_LABELS[target_wd]}{num:03d}"
        today_wd = _today().weekday()
        if target_wd == today_wd:
            raw = fetch_text(NBA_LOTTERY_LIST_URL, encoding="utf-8", referer=_JC_REFERER)
            return _resolve_by_label(raw, target_label, source="weekday_number")
        date = _last_weekday_date(target_wd).strftime("%Y-%m-%d")
        return _resolve_historical_by_date(date, target_label, source="weekday_number")

    # 3) 仅序号（当日）
    m = _NUMBER_RE.search(ref)
    if m:
        num = int(m.group(1))
        target_label = f"{_WEEKDAY_LABELS[_today().weekday()]}{num:03d}"
        raw = fetch_text(NBA_LOTTERY_LIST_URL, encoding="utf-8", referer=_JC_REFERER)
        return _resolve_by_label(raw, target_label, source="number")

    raise ValueError(f"无法识别输入：{ref}")
