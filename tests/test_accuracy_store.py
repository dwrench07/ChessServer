"""Tests for the accuracy model and the SQLite store (no engine needed).

Uses a temp DB via the CHESSCOACH_DB env var so it never touches real data.
Run:  python tests/test_accuracy_store.py   (or pytest)
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Point the store at a throwaway DB before importing it.
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["CHESSCOACH_DB"] = _TMP.name

from chesscoach import store                       # noqa: E402
from chesscoach.accuracy import (                   # noqa: E402
    win_percent, accuracy_from_cp, game_accuracy, move_accuracy,
)


def test_win_percent_monotonic_and_bounds():
    assert abs(win_percent(0) - 50.0) < 1e-6
    assert win_percent(1000) > win_percent(100) > win_percent(0) > win_percent(-100)
    assert 0 <= win_percent(-5000) <= 100
    assert 0 <= win_percent(5000) <= 100


def test_best_move_scores_100():
    assert accuracy_from_cp(50, 50) == 100.0          # no win% lost
    assert accuracy_from_cp(50, 80) == 100.0          # improved -> still 100


def test_worse_moves_score_lower():
    slip = accuracy_from_cp(50, -20)
    blunder = accuracy_from_cp(300, -400)
    assert 0 <= blunder < slip < 100


def test_move_accuracy_drop_relationship():
    assert move_accuracy(80, 80) == 100.0
    assert move_accuracy(80, 40) < move_accuracy(80, 70)


def test_game_accuracy_blends_and_handles_empty():
    assert game_accuracy([]) is None
    perfect = game_accuracy([100, 100, 100])
    assert perfect == 100.0
    # one blunder should pull the figure well below the arithmetic mean
    mixed = game_accuracy([100, 100, 100, 10])
    assert mixed < (100 + 100 + 100 + 10) / 4


def test_store_roundtrip_and_dashboard():
    gid = store.save_game(
        {"source": "play", "white": "You", "black": "Stockfish", "result": "1-0",
         "human_color": "white", "level": 3, "white_acc": 90.0, "black_acc": None,
         "pgn": "1. e4"},
        [{"ply": 1, "side": "white", "san": "e4", "uci": "e2e4", "quality": "best",
          "cp_loss": 0, "eval_cp": 30, "tag": None},
         {"ply": 2, "side": "white", "san": "Qh5", "uci": "d1h5", "quality": "blunder",
          "cp_loss": 500, "eval_cp": -400, "tag": "hangs_piece"}],
    )
    assert isinstance(gid, int)
    g = store.get_game(gid)
    assert g["result"] == "1-0" and len(g["moves"]) == 2

    dash = store.dashboard()
    assert dash["gameCount"] >= 1
    assert dash["record"]["wins"] >= 1
    # the human (white) blunder tagged as a hanging piece should be counted
    assert dash["mistakeTags"].get("hangs_piece", 0) >= 1
    assert dash["qualityCounts"].get("blunder", 0) >= 1


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print("PASS", fn.__name__)
        except Exception:
            failed += 1; print("FAIL", fn.__name__); traceback.print_exc()
    try:
        os.unlink(_TMP.name)
    except OSError:
        pass
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
