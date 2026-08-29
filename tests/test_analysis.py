"""核心分析逻辑的单元测试（无需联网）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analysis import analyze, margin_removed_probs
from src.odds import BookmakerOdds, MatchOdds, parse_game

# 模拟 game 数组的一行：Bet365 风格 + 竞彩官* 行
_SAMPLE_JS = (
    'var game=Array('
    '"281|1|Bet365|3.9|3.1|1.95|23.48|29.55|46.97|91.59|4.5|3.3|1.83|20.74|28.28|50.99|93.31|0.97|0.93|0.92|2026,08-1,29,02,13,00|必发|0|0|0.84|0.87|0.98",'
    '"1129|2|Lottery Official|3.95|3.28|1.75|22.41|26.99|50.59|88.54|3.95|3.28|1.75|22.41|26.99|50.59|88.54|0.85|0.92|0.88|2026,08-1,28,01,58,00|竞彩官*|1|0|0.85|0.92|0.88"'
    ');'
)


def test_margin_removed_probs_normalized() -> None:
    h, d, a = margin_removed_probs(2.0, 3.0, 4.0)
    assert abs((h + d + a) - 100.0) < 1e-6


def test_parse_game_extracts_lottery() -> None:
    rows = parse_game(_SAMPLE_JS)
    assert len(rows) == 2
    lottery = next(b for b in rows if b.is_lottery)
    assert lottery.company_cn == "竞彩官*"
    assert lottery.live_home == 3.95


def test_analyze_consensus_and_recommendation() -> None:
    rows = parse_game(_SAMPLE_JS)
    match = MatchOdds(
        match_id="999", hometeam="A", guestteam="B", match_time="x", bookmakers=rows
    )
    r = analyze(match)
    # 共识应接近两家均值并归一化到 ~100
    assert abs(sum(r.consensus) - 100.0) < 1e-6
    # 概率最高方向应存在
    assert r.most_probable[0] in ("主胜", "平局", "客胜")
    # 体彩价值分析应完成
    assert r.lottery_odds is not None
    assert r.best_value is not None
