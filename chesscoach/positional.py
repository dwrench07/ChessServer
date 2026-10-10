"""Positional contrast — the "why" for quiet, non-tactical mistakes.

An inaccuracy usually has no hanging piece or forcing refutation; the engine
simply prefers another move for positional reasons. Telling a learner "that's
an inaccuracy, it costs 0.3 pawns" builds no intuition.

This module compares the position *after the move played* with the position
*after the engine's best move*, on concepts a coach actually names, and reports
the ones that differ most: king safety, central control, development, pawn
structure, the bishop pair, and piece activity. The result is a human reason
("Bb5 develops and pins; your move is slower and cedes the centre") instead of
a number.

Everything here is static (no engine), so it is cheap. These are heuristics,
not ground truth — they are offered as the *likely* reason, and the engine's
eval remains the authority on whether the move was actually worse.
"""

from __future__ import annotations

import chess

from .motifs import PIECE_VALUE, Motif

CENTER = [chess.D4, chess.E4, chess.D5, chess.E5]
BIG_CENTER = CENTER + [chess.C3, chess.D3, chess.E3, chess.F3,
                       chess.C6, chess.D6, chess.E6, chess.F6]


def king_danger(board: chess.Board, color: chess.Color) -> int:
    """Enemy attack pressure on and around our king (higher = more exposed)."""
    ksq = board.king(color)
    if ksq is None:
        return 0
    zone = chess.SquareSet(chess.BB_KING_ATTACKS[ksq]) | chess.SquareSet(chess.BB_SQUARES[ksq])
    opp = not color
    danger = 0
    for sq in zone:
        danger += len(board.attackers(opp, sq))
    # Open/half-open files next to the king add to the danger.
    kf = chess.square_file(ksq)
    for f in (kf - 1, kf, kf + 1):
        if 0 <= f <= 7 and not _has_pawn_on_file(board, color, f):
            danger += 1
    return danger


def center_control(board: chess.Board, color: chess.Color) -> int:
    """Occupation + attacks of the four central squares."""
    score = 0
    for sq in CENTER:
        p = board.piece_at(sq)
        if p and p.color == color:
            score += 2 if p.piece_type == chess.PAWN else 1
        score += len(board.attackers(color, sq))
    return score


def development(board: chess.Board, color: chess.Color) -> int:
    """Minor pieces off the back rank, plus a bonus for a safely tucked king."""
    back = 0 if color == chess.WHITE else 7
    dev = 0
    for pt in (chess.KNIGHT, chess.BISHOP):
        for sq in board.pieces(pt, color):
            if chess.square_rank(sq) != back:
                dev += 1
    ksq = board.king(color)
    if ksq is not None and chess.square_file(ksq) in (2, 6):  # c- or g-file => castled-ish
        dev += 1
    return dev


def pawn_weaknesses(board: chess.Board, color: chess.Color) -> int:
    """Count of doubled + isolated pawns (rough structural health)."""
    files = [0] * 8
    for sq in board.pieces(chess.PAWN, color):
        files[chess.square_file(sq)] += 1
    doubled = sum(max(0, c - 1) for c in files)
    isolated = 0
    for f in range(8):
        if files[f] and not (f > 0 and files[f - 1]) and not (f < 7 and files[f + 1]):
            isolated += files[f]
    return doubled + isolated


def has_bishop_pair(board: chess.Board, color: chess.Color) -> bool:
    return len(board.pieces(chess.BISHOP, color)) >= 2


def mobility(board: chess.Board, color: chess.Color) -> int:
    """Activity proxy: total squares our pieces attack (turn-independent)."""
    total = 0
    for sq, piece in board.piece_map().items():
        if piece.color == color and piece.piece_type != chess.PAWN:
            total += len(board.attacks(sq))
    return total


def _has_pawn_on_file(board: chess.Board, color: chess.Color, f: int) -> bool:
    for sq in board.pieces(chess.PAWN, color):
        if chess.square_file(sq) == f:
            return True
    return False


def contrast(board_before: chess.Board, played: chess.Move, best: chess.Move) -> list[Motif]:
    """Positional reasons the engine's `best` is preferred over `played`.

    Returns up to two phrases, strongest difference first. Empty if the two
    moves are the same or no concept differs meaningfully.
    """
    if played == best:
        return []
    mover = board_before.turn
    bp = board_before.copy(stack=False); bp.push(played)
    bb = board_before.copy(stack=False); bb.push(best)

    # Each candidate: (magnitude, text). The text names the move's shortcoming
    # (relative to the best move) without repeating the best move's name, which
    # the explanation adds separately.
    cands: list[tuple[int, str]] = []

    ks_p, ks_b = king_danger(bp, mover), king_danger(bb, mover)
    if ks_p - ks_b >= 2:
        cands.append((ks_p - ks_b, "it leaves your king more exposed"))

    c_p, c_b = center_control(bp, mover), center_control(bb, mover)
    if c_b - c_p >= 2:
        cands.append((c_b - c_p, "it doesn't contest the centre"))

    d_p, d_b = development(bp, mover), development(bb, mover)
    if d_b - d_p >= 1:
        cands.append((2 * (d_b - d_p), "it's slow to develop and loses time"))

    w_p, w_b = pawn_weaknesses(bp, mover), pawn_weaknesses(bb, mover)
    if w_p - w_b >= 1:
        cands.append((2 * (w_p - w_b), "it concedes a weak pawn (doubled or isolated)"))

    if has_bishop_pair(bb, mover) and not has_bishop_pair(bp, mover):
        cands.append((3, "it gives up the bishop pair"))

    m_p, m_b = mobility(bp, mover), mobility(bb, mover)
    if m_b - m_p >= 6:
        cands.append((max(1, (m_b - m_p) // 4), "it leaves your pieces passive"))

    cands.sort(key=lambda t: t[0], reverse=True)
    return [Motif("positional_contrast", False, text) for _, text in cands[:2]]
