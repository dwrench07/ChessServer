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


def test_strategy_phase_and_brief():
    from chesscoach.strategy import phase, strategic_brief
    # start position is opening
    assert phase(chess.Board()) == "opening"
    # a bare king-and-pawn ending is an endgame
    assert phase(chess.Board("8/5pk1/6p1/8/8/1R6/5PPP/6K1 w - - 0 1")) == "endgame"
    # a middlegame with an open file yields a concrete plan
    board = chess.Board("r1bq1rk1/pp3ppp/2n1pn2/8/2BP4/2N1PN2/PP3PPP/R1BQ1RK1 b - - 0 10")
    br = strategic_brief(board)
    assert br.phase == "middlegame"
    assert br.your_plan, "expected at least one plan"
    assert isinstance(br.character, str) and br.character


def test_plot_detects_seed_and_strike():
    from chesscoach.plot import find_plot

    def ply(p, side, num, san, frm, to, cp):
        return {"ply": p, "side": side, "moveNumber": num, "san": san,
                "playedFrom": frm, "playedTo": to, "evalCp": cp, "fenBefore": None,
                "quality": "best"}

    # White quietly lifts a rook to d1 (ply 3), then mates with it on d8 (ply 13).
    review = [
        ply(1, "white", 1, "e4", "e2", "e4", 20),
        ply(2, "black", 1, "e5", "e7", "e5", -20),
        ply(3, "white", 2, "Rd1", "a1", "d1", 30),      # the seed (quiet)
        ply(4, "black", 2, "Nc6", "b8", "c6", -30),
        ply(5, "white", 3, "h3", "h2", "h3", 35),
        ply(6, "black", 3, "a6", "a7", "a6", -35),
        ply(7, "white", 4, "c3", "c2", "c3", 40),
        ply(8, "black", 4, "b6", "b7", "b6", -40),
        ply(9, "white", 5, "g3", "g2", "g3", 45),
        ply(10, "black", 5, "h6", "h7", "h6", -45),
        ply(11, "white", 6, "Kg2", "g1", "g2", 50),
        ply(12, "black", 6, "Qe7", "d8", "e7", -50),
        ply(13, "white", 7, "Rd8#", "d1", "d8", 100000),  # the strike (mate)
    ]
    p = find_plot(review)
    assert p["hasPlot"] is True
    assert p["winner"] == "White"
    assert p["seed"]["san"] == "Rd1"
    assert p["strike"]["san"] == "Rd8#"

    # A balanced game has no plot, honestly.
    flat = [ply(i + 1, "white" if i % 2 == 0 else "black", i // 2 + 1,
                "Nf3", "g1", "f3", 10 if i % 2 == 0 else -10) for i in range(12)]
    assert find_plot(flat)["hasPlot"] is False


def test_analogies_mapping():
    from chesscoach import analogies
    assert analogies.concept_for_tag("hangs_piece") == "hanging_piece"
    assert analogies.concept_for_tag(None) is None
    assert analogies.concept_for_plan(["plant a knight on the d5 outpost"]) == "outpost"
    assert analogies.concept_for_plan(["seize the open c-file with a rook"]) == "open_file"
    # every concept has the three teaching fields
    for c in analogies.concept_list():
        assert c["title"] and c["definition"] and c["analogy"]


def test_opening_classifier():
    from chesscoach.analytics import name_opening
    assert name_opening(["e4", "e5", "Nf3", "Nc6", "Bb5"]) == "Ruy Lopez"
    assert name_opening(["e4", "e5", "Nf3", "Nc6", "Bc4"]) == "Italian Game"
    assert name_opening(["e4", "c5"]) == "Sicilian Defense"
    assert name_opening(["d4", "d5", "c4"]) == "Queen's Gambit"
    assert name_opening(["g4"]) == "Irregular"


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


def test_puzzles_extracted_from_human_mistakes_only():
    from chesscoach.puzzles import extract_puzzles

    board = chess.Board()
    ucis = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6"]
    moves = []
    for i, u in enumerate(ucis, 1):
        mv = chess.Move.from_uci(u)
        side = "white" if board.turn == chess.WHITE else "black"
        q = cl = tag = None
        if i == 6:                       # black's 6th: a blunder (allows mate)
            q, cl, tag = "blunder", 900, "allows_mate"
        if i == 3:                       # white's 3rd: a big mistake
            q, cl, tag = "mistake", 200, None
        moves.append({"ply": i, "side": side, "san": board.san(mv), "uci": u,
                      "quality": q, "cp_loss": cl, "tag": tag})
        board.push(mv)
    game = {"id": 7, "human_color": "black", "created_at": 1.0, "moves": moves}

    pz = extract_puzzles([game])
    # Only the human's (black) blunder becomes a puzzle, not white's mistake.
    assert len(pz) == 1
    p = pz[0]
    assert p["sideToMove"] == "black" and p["playedSan"] == "Nf6"
    assert p["cpLoss"] == 900 and p["gameId"] == 7
    # The FEN is the position *before* the blunder (black to move, before Nf6).
    assert chess.Board(p["fen"]).turn == chess.BLACK

    # Below-threshold mistakes and imports (no human side) yield nothing.
    tiny = {"id": 8, "human_color": "white", "created_at": 2.0,
            "moves": [{"ply": 1, "side": "white", "san": "e4", "uci": "e2e4",
                       "quality": "mistake", "cp_loss": 40, "tag": None}]}
    imported = {"id": 9, "human_color": None, "created_at": 3.0, "moves": moves}
    assert extract_puzzles([tiny]) == []
    assert extract_puzzles([imported]) == []


def test_live_plot_fires_on_seeded_mate():
    from chesscoach.plot import live_plot

    def m(ply, side, san, frm, to, mn, ev):
        return {"ply": ply, "side": side, "san": san, "playedFrom": frm,
                "playedTo": to, "moveNumber": mn, "evalCp": ev}

    # Legall's Mate: 4.Nc3 (seed) sets the knight toward d5; 7.Nd5# (strike).
    review = [
        m(1, "white", "e4", "e2", "e4", 1, 20), m(2, "black", "e5", "e7", "e5", 1, 0),
        m(3, "white", "Nf3", "g1", "f3", 2, 20), m(4, "black", "d6", "d7", "d6", 2, 10),
        m(5, "white", "Bc4", "f1", "c4", 3, 30), m(6, "black", "Bg4", "c8", "g4", 3, 20),
        m(7, "white", "Nc3", "b1", "c3", 4, 25), m(8, "black", "g6", "g7", "g6", 4, 20),
        m(9, "white", "Nxe5", "f3", "e5", 5, 120), m(10, "black", "Bxd1", "g4", "d1", 5, -300),
        m(11, "white", "Bxf7+", "c4", "f7", 6, 400), m(12, "black", "Ke7", "e8", "e7", 6, -500),
        m(13, "white", "Nd5#", "c3", "d5", 7, 100000),
    ]
    r = live_plot(review)
    assert r["fired"] and r["kind"] == "mate" and r["piece"] == "knight"
    assert r["seed"]["san"] == "Nc3" and r["seed"]["moveNumber"] == 4
    assert r["strike"]["san"] == "Nd5#"

    # The same timeline minus the final strike has not paid off yet.
    assert live_plot(review[:-1])["fired"] is False
    # A balanced, quiet game never fires.
    quiet = [m(i, "white" if i % 2 else "black", "Nf3", "g1", "f3", i // 2 + 1, 10)
             for i in range(1, 13)]
    assert live_plot(quiet)["fired"] is False


def test_campaign_unlock_and_beaten_logic():
    from chesscoach import personas

    # Fresh player: level 1, no wins -> only the level-1 personas unlocked,
    # none beaten, the first is the current quest.
    cs = personas.campaign_state(player_level=1, wins_by_level={})
    assert cs["beaten"] == 0 and not cs["complete"]
    assert cs["personas"][0]["unlocked"] and cs["personas"][0]["current"]
    assert not cs["personas"][-1]["unlocked"]

    # A win at level 4 subsumes every rung at level <= 4 as beaten.
    cs2 = personas.campaign_state(player_level=4, wins_by_level={4: 1})
    beaten = [p["name"] for p in cs2["personas"] if p["beaten"]]
    assert "The Baron" in beaten and "The Novice" in beaten
    assert not any(p["beaten"] for p in cs2["personas"] if p["level"] > 4)
    # The current quest is the first unlocked, unbeaten persona.
    cur = next(p for p in cs2["personas"] if p["current"])
    assert cur["level"] == 5  # The General


def test_puzzles_dedupe_keeps_most_severe():
    from chesscoach.puzzles import extract_puzzles

    def game(gid, cp_loss, created):
        b = chess.Board()
        mv = chess.Move.from_uci("g1f3")
        rec = {"ply": 1, "side": "white", "san": b.san(mv), "uci": "g1f3",
               "quality": "blunder", "cp_loss": cp_loss, "tag": None}
        return {"id": gid, "human_color": "white", "created_at": created,
                "moves": [rec]}

    # Same starting position blundered twice; keep the worse instance.
    pz = extract_puzzles([game(1, 150, 1.0), game(2, 500, 2.0)])
    assert len(pz) == 1 and pz[0]["cpLoss"] == 500


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
