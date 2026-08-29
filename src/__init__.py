"""足球欧指分析工具包：抓取 titan007 百家欧指，估算胜平负概率并给出体彩方向研判。"""
from __future__ import annotations

from .analysis import AnalysisResult, analyze, format_report, margin_removed_probs
from .odds import BookmakerOdds, MatchOdds, fetch_match_odds, parse_game
from .schedule import first_match, list_matches, match_id_from_url

__all__ = [
    "AnalysisResult",
    "analyze",
    "format_report",
    "margin_removed_probs",
    "BookmakerOdds",
    "MatchOdds",
    "fetch_match_odds",
    "parse_game",
    "first_match",
    "list_matches",
    "match_id_from_url",
]
