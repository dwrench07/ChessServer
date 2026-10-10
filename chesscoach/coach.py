"""Orchestration: turn a position + a played move into coaching output.

This is the pipeline the whole project is a proof of:

    engine (truth)  ->  classify (quality)  ->  motifs (why)  ->  explain (voice)

Nothing here computes chess judgement itself; it only wires the layers.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from .classify import Quality, QualityVerdict, classify
from .engine import Analyzer, MoveEval, PositionReport
from .explain import CoachingFacts, explain
from .motifs import MotifReport, build_motifs, static_exchange_eval


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
    """Sacrifice test using Static Exchange Evaluation.

    The move truly sacrifices material only if, after it, the opponent can win
    material on the landing square (SEE > 0) -- a piece defended well enough
    (even by a pawn) is not a sacrifice. Used only to upgrade a best move to
    'brilliant'; a false negative just means we call it 'best' instead.
    """
    after = board_before.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return False  # the opponent cannot recapture a mating piece
    return static_exchange_eval(after, move.to_square) >= 2


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
    subpar = verdict.quality in (Quality.INACCURACY, Quality.MISTAKE, Quality.BLUNDER)
    motifs: MotifReport = build_motifs(board_before, move, played_eval, is_good=not subpar)

    # For a sub-par move, add the positional "why" (what the best move does that
    # this one doesn't). This is what turns "inaccuracy, -0.3" into intuition.
    if subpar and move != pre.best.move:
        from .positional import contrast
        contrast_motifs = contrast(board_before, move, pre.best.move)
        if contrast_motifs:
            tact = [m for m in motifs.motifs if m.tactical]
            pos = [m for m in motifs.motifs if not m.tactical]
            motifs.motifs = tact + contrast_motifs + pos

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
