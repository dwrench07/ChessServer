"""Orchestration: turn a position + a played move into coaching output.

This is the pipeline the whole project is a proof of:

    engine (truth)  ->  classify (quality)  ->  motifs (why)  ->  explain (voice)

Nothing here computes chess judgement itself; it only wires the layers.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from .classify import QualityVerdict, classify
from .engine import Analyzer, MoveEval, PositionReport
from .explain import CoachingFacts, explain
from .motifs import PIECE_VALUE, MotifReport, build_motifs


@dataclass
class Coaching:
    move_san: str
    verdict: QualityVerdict
    motifs: MotifReport
    best: MoveEval
    explanation: str
    explanation_source: str
    facts: CoachingFacts


def _is_sacrifice(board_before: chess.Board, move: chess.Move) -> bool:
    """Rough sacrifice test: a non-capture (or uneven capture) that offers
    material the opponent can take. Used only to upgrade a best move to
    'brilliant'; a false negative just means we call it 'best' instead."""
    mover = board_before.turn
    after = board_before.copy(stack=False)
    moved_piece = board_before.piece_at(move.from_square)
    if moved_piece is None:
        return False
    captured_val = 0
    if board_before.is_capture(move):
        if board_before.is_en_passant(move):
            captured_val = PIECE_VALUE[chess.PAWN]
        else:
            cap = board_before.piece_at(move.to_square)
            captured_val = PIECE_VALUE[cap.piece_type] if cap else 0
    after.push(move)
    # A mating move is not a "sacrifice" -- the opponent cannot recapture.
    if after.is_checkmate():
        return False
    attackers = after.attackers(not mover, move.to_square)
    if not attackers:
        return False
    moved_val = PIECE_VALUE[moved_piece.piece_type]
    # Offered piece is worth more than what it captured and is attacked.
    return moved_val - captured_val >= 2


def coach_move(
    analyzer: Analyzer,
    board_before: chess.Board,
    move: chess.Move,
    *,
    use_llm: bool = True,
    model: str | None = None,
    multipv: int = 3,
) -> Coaching:
    """Produce coaching for `move` played from `board_before`."""
    if move not in board_before.legal_moves:
        raise ValueError(f"{board_before.san(move) if move else move} is not a legal move here.")

    pre: PositionReport = analyzer.analyse_position(board_before, multipv=multipv)
    played_eval: MoveEval = analyzer.evaluate_after(board_before, move)

    verdict = classify(
        pre.best,
        played_eval,
        is_sacrifice=_is_sacrifice(board_before, move),
    )
    motifs: MotifReport = build_motifs(board_before, move, played_eval)

    mover = "White" if board_before.turn == chess.WHITE else "Black"
    facts = CoachingFacts(
        mover=mover,
        move_san=played_eval.san,
        quality=verdict,
        best_move_san=pre.best.san,
        best_line_san=pre.best.pv_san,
        refutation_san=played_eval.pv_san,
        motif_report=motifs,
        eval_before_cp=pre.best.score_cp,
        eval_after_cp=played_eval.score_cp,
    )
    text, source = explain(facts, use_llm=use_llm, model=model)

    return Coaching(
        move_san=played_eval.san,
        verdict=verdict,
        motifs=motifs,
        best=pre.best,
        explanation=text,
        explanation_source=source,
        facts=facts,
    )
