"""Move-quality classification.

The *quality* of a move is derived purely from the engine's numbers, never
from the language model. We measure "centipawn loss": how much worse the
move played is than the engine's best move, from the mover's point of view.

Thresholds follow the widely used Lichess-style convention. They are a
pragmatic convention, not ground truth -- positional judgement at the margins
is genuinely fuzzy, so treat the boundary cases as approximate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .engine import MoveEval


class Quality(str, Enum):
    BRILLIANT = "brilliant"      # best (or near-best) AND a sound sacrifice
    BEST = "best"                # matched the engine's top choice
    EXCELLENT = "excellent"      # practically as good as best
    GOOD = "good"
    INACCURACY = "inaccuracy"    # ?!
    MISTAKE = "mistake"          # ?
    BLUNDER = "blunder"          # ??

    @property
    def glyph(self) -> str:
        return {
            Quality.BRILLIANT: "!!",
            Quality.BEST: "",
            Quality.EXCELLENT: "",
            Quality.GOOD: "",
            Quality.INACCURACY: "?!",
            Quality.MISTAKE: "?",
            Quality.BLUNDER: "??",
        }[self]


# Centipawn-loss thresholds (inclusive lower bound).
_THRESHOLDS = [
    (10, Quality.EXCELLENT),
    (50, Quality.GOOD),
    (100, Quality.INACCURACY),
    (250, Quality.MISTAKE),
]


@dataclass
class QualityVerdict:
    quality: Quality
    cp_loss: int               # how many centipawns worse than best (>= 0)
    is_best_move: bool
    swung_the_game: bool       # crossed a decisive threshold (e.g. winning -> losing)


def _winning_bucket(cp: int) -> int:
    """Coarse game-state bucket, for detecting a decisive swing.

    -1 = losing, 0 = roughly equal, +1 = winning.
    """
    if cp > 150:
        return 1
    if cp < -150:
        return -1
    return 0


def classify(
    best: MoveEval,
    played: MoveEval,
    *,
    is_sacrifice: bool = False,
) -> QualityVerdict:
    """Classify `played` relative to the engine's `best` move.

    Both scores must already be expressed from the mover's point of view
    (see `Analyzer.evaluate_after`).
    """
    cp_loss = max(0, best.score_cp - played.score_cp)
    is_best = played.move == best.move or cp_loss <= 2

    if is_best:
        quality = Quality.BRILLIANT if is_sacrifice else Quality.BEST
    else:
        quality = Quality.BLUNDER  # default for the worst bucket
        for bound, q in _THRESHOLDS:
            if cp_loss < bound:
                quality = q
                break

    swung = _winning_bucket(best.score_cp) > _winning_bucket(played.score_cp)
    return QualityVerdict(
        quality=quality,
        cp_loss=cp_loss,
        is_best_move=is_best,
        swung_the_game=swung,
    )
