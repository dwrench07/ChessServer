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

from chesscoach import store, progress              # noqa: E402
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

    # recurring-mistake lookup sees the human's tagged blunder
    ts = store.tag_stats("hangs_piece")
    assert ts["games"] >= 1 and ts["total"] >= 1
    assert store.tag_stats("no_such_tag")["games"] == 0

    dash = store.dashboard()
    assert dash["gameCount"] >= 1
    assert dash["record"]["wins"] >= 1
    # the human (white) blunder tagged as a hanging piece should be counted
    assert dash["mistakeTags"].get("hangs_piece", 0) >= 1
    assert dash["qualityCounts"].get("blunder", 0) >= 1


def test_store_wins_by_level():
    # Delta-based, since the module shares one DB across tests.
    before = store.wins_by_level()
    store.save_game({"source": "play", "result": "1-0", "human_color": "white",
                     "level": 5}, [])              # win at 5
    store.save_game({"source": "play", "result": "0-1", "human_color": "white",
                     "level": 5}, [])              # loss at 5 (ignored)
    store.save_game({"source": "play", "result": "0-1", "human_color": "black",
                     "level": 5}, [])              # black wins at 5
    store.save_game({"source": "pgn", "result": "1-0", "human_color": None,
                     "level": 8}, [])              # import, no human side (ignored)
    after = store.wins_by_level()
    assert after.get(5, 0) - before.get(5, 0) == 2   # two wins added at level 5
    assert after.get(8, 0) - before.get(8, 0) == 0   # import never counts


def test_progress_xp_rewards_result_and_quality():
    # A won game pays more than a drawn one, which pays more than a loss,
    # at equal accuracy.
    assert progress.xp_for(True, False, 80) > progress.xp_for(False, True, 80) \
        > progress.xp_for(False, False, 80)
    # A well-played loss can out-earn a sloppy win's accuracy component, but the
    # result bonus still dominates; at least a clean loss beats a scrappy loss.
    assert progress.xp_for(False, False, 95) > progress.xp_for(False, False, 20)
    # Accuracy is optional (unanalysed import).
    assert progress.xp_for(True, False, None) > 0


def test_progress_levels_and_grade():
    assert progress.level_for_xp(0) == 1
    assert progress.level_for_xp(100) == 2
    assert progress.level_for_xp(10_000) == len(progress._THRESHOLDS)
    lp = progress.level_progress(150)
    assert lp["level"] == 2 and 0 <= lp["pct"] <= 100
    assert lp["nextAt"] == progress._THRESHOLDS[2]
    # top level: no next threshold, bar full
    top = progress.level_progress(1_000_000)
    assert top["nextAt"] is None and top["pct"] == 100
    assert progress.grade(96) == "A+" and progress.grade(55) == "E"
    assert progress.grade(None) == "—"


def test_progress_kingdom_unlocks_cumulatively():
    k = progress.kingdom_for_level(3)
    assert k[0]["unlocked"] and k[2]["unlocked"] and not k[3]["unlocked"]
    assert len(k) == len(progress._KINGDOM)


def test_store_profile_accumulates():
    before = store.get_profile()
    p = store.add_result(50, won=True, accuracy=88.0, streak=4)
    assert p["total_xp"] == before["total_xp"] + 50
    assert p["games"] == before["games"] + 1
    assert p["wins"] == before["wins"] + 1
    # best_acc/best_streak are high-water marks, never regress
    p2 = store.add_result(10, won=False, accuracy=40.0, streak=1)
    assert p2["best_acc"] == p["best_acc"] and p2["best_streak"] == p["best_streak"]


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
