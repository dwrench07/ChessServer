"""Unit tests for the engine-independent layers.

These run without Stockfish or Ollama: they exercise the classification
thresholds and the template explainer, which are the parts that must stay
deterministic and hallucination-proof.

Run with:  python -m pytest tests/ -q      (or plain: python tests/test_logic.py)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chess

from chesscoach.classify import Quality, classify
from chesscoach.engine import MoveEval
from chesscoach.explain import CoachingFacts, template_explanation
from chesscoach.motifs import MotifReport, build_motifs


def _me(uci, cp, mate=None, pv=()):
    mv = chess.Move.from_uci(uci)
    return MoveEval(move=mv, san=uci, score_cp=cp, mate_in=mate, pv=list(pv), pv_san=[])


def test_best_move_is_best():
    best = _me("g1f3", 30)
    played = _me("g1f3", 30)
    v = classify(best, played)
    assert v.quality is Quality.BEST
    assert v.is_best_move
    assert v.cp_loss == 0


def test_blunder_threshold():
    best = _me("d2d4", 50)
    played = _me("d1h5", 50 - 400)  # 400cp worse
    v = classify(best, played)
    assert v.quality is Quality.BLUNDER
    assert v.cp_loss == 400


def test_inaccuracy_threshold():
    best = _me("d2d4", 20)
    played = _me("b1c3", 20 - 70)  # 70cp worse -> inaccuracy band [50,100)
    v = classify(best, played)
    assert v.quality is Quality.INACCURACY


def test_sacrifice_upgrades_to_brilliant():
    best = _me("c1h6", 300)
    played = _me("c1h6", 300)
    v = classify(best, played, is_sacrifice=True)
    assert v.quality is Quality.BRILLIANT


def test_decisive_swing_detected():
    best = _me("d2d4", 300)       # winning
    played = _me("d1h5", -300)    # losing
    v = classify(best, played)
    assert v.swung_the_game


def test_hanging_piece_motif():
    # White queen moves to d7, adjacent to the Black king, undefended.
    board = chess.Board("4k3/8/8/8/8/8/3Q4/4K3 w - - 0 1")
    move = chess.Move.from_uci("d2d7")
    played = _me("d2d7", -900, pv=[chess.Move.from_uci("e8d7")])
    # pv_san needs real SAN for the refutation text; build it here.
    played.pv_san = ["Kxd7"]
    report = build_motifs(board, move, played)
    kinds = {m.kind for m in report.motifs}
    assert "hangs_piece" in kinds
    assert report.tactical  # at least one concrete fact


def test_positional_contrast_explains_quiet_inaccuracy():
    # After 1.e4 e5 2.Nf3 Nc6 3.Bc4, a slow move (a6) vs developing (Nf6):
    # the contrast should produce a positional reason, tagged non-tactical.
    from chesscoach.positional import contrast
    board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3")
    played = board.parse_san("a6")
    best = board.parse_san("Nf6")
    motifs = contrast(board, played, best)
    assert motifs, "expected at least one positional reason"
    assert all(not m.tactical for m in motifs)
    assert all(m.kind == "positional_contrast" for m in motifs)
    # identical moves -> no contrast
    assert contrast(board, best, best) == []


def test_template_never_empty():
    board = chess.Board("4k3/8/8/8/8/8/3Q4/4K3 w - - 0 1")
    move = chess.Move.from_uci("d2d7")
    played = _me("d2d7", -900, pv=[chess.Move.from_uci("e8d7")])
    played.pv_san = ["Kxd7"]
    report = build_motifs(board, move, played)
    best = _me("d2d6", 100000)
    v = classify(best, played)
    facts = CoachingFacts(
        mover="White", move_san="Qd7+", quality=v,
        best_move_san="Qd6", best_line_san=["Qd6"], refutation_san=["Kxd7"],
        motif_report=report, eval_before_cp=100000, eval_after_cp=-900,
    )
    text = template_explanation(facts)
    assert "Qd7+" in text and len(text) > 20


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
