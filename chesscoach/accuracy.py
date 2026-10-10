"""Accuracy scoring from engine evaluations.

Uses the win-percentage model popularised by Lichess: a centipawn score is
first mapped to an expected win percentage, and a move's accuracy is a function
of how much win% it gave up versus the best move. This yields the familiar
0-100 "accuracy" figure, which is far more intuitive to a learner than raw
centipawns.

These are approximations of Lichess's exact pipeline (which adds volatility
weighting); results can differ by a point or two near boundaries. We label the
number "approx." in the UI rather than implying parity.
"""

from __future__ import annotations

import math


def win_percent(cp: int) -> float:
    """Expected win percentage (0-100) for the side to move, from its own
    centipawn score. Saturating S-curve; +/- large cp approaches 100/0."""
    cp = max(-2000, min(2000, cp))
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-0.00368208 * cp)) - 1.0)


def move_accuracy(win_before: float, win_after: float) -> float:
    """Accuracy (0-100) for one move, from win% before and after it.

    `win_before` is the win% the mover could expect (best move); `win_after`
    is the win% after the move actually played, both from the mover's view.
    A move that does not drop win% scores 100.
    """
    drop = win_before - win_after
    if drop <= 0:
        return 100.0            # lost no win% -> perfectly accurate
    acc = 103.1668 * math.exp(-0.04354 * drop) - 3.1669
    return max(0.0, min(100.0, acc))


def game_accuracy(accuracies: list[float]) -> float | None:
    """Combine per-move accuracies into a single game figure.

    Blends the arithmetic and harmonic means: the harmonic mean punishes the
    occasional terrible move (so one blunder is not hidden by many fine moves),
    while the arithmetic mean keeps it from collapsing. Returns None for an
    empty list (no moves by that side).
    """
    vals = [a for a in accuracies if a is not None]
    if not vals:
        return None
    mean = sum(vals) / len(vals)
    # Harmonic mean, guarding against zeros.
    denom = sum(1.0 / max(a, 1.0) for a in vals)
    harmonic = len(vals) / denom
    return round(0.5 * mean + 0.5 * harmonic, 1)


def accuracy_from_cp(eval_before_cp: int, eval_after_cp: int) -> float:
    """Convenience: per-move accuracy directly from mover-POV cp scores."""
    return move_accuracy(win_percent(eval_before_cp), win_percent(eval_after_cp))
