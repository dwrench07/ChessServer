"""Motif / feature extraction -- the concrete hooks for "why".

A raw centipawn number says *that* a move is bad; it does not say *why* in
human terms. This module extracts the human-recognisable concepts a coach
would name: hanging pieces, forks, checks, lost castling, the refutation
line, and so on.

Two kinds of signal, with very different reliability -- and we keep them
labelled as such, because being honest about that distinction is what makes
a teacher trustworthy:

  * TACTICAL  -- concrete and verifiable from forcing lines (hanging piece,
                 fork, the refutation PV). These are reliable.
  * POSITIONAL-- softer heuristics (space, development, king exposure).
                 These are hints, not proofs; NNUE engines cannot explain
                 their positional judgement, so neither can we with certainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from .engine import MoveEval

PIECE_VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}
_NAME = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}


@dataclass
class Motif:
    kind: str          # machine tag, e.g. "hangs_piece"
    tactical: bool     # True = concrete/reliable, False = positional hint
    text: str          # short human phrase

    def __str__(self) -> str:
        return self.text


@dataclass
class MotifReport:
    move_san: str
    motifs: list[Motif] = field(default_factory=list)

    @property
    def tactical(self) -> list[Motif]:
        return [m for m in self.motifs if m.tactical]

    @property
    def positional(self) -> list[Motif]:
        return [m for m in self.motifs if not m.tactical]


def _square_name(sq: int) -> str:
    return chess.square_name(sq)


def static_exchange_eval(board: chess.Board, square: int) -> int:
    """Static Exchange Evaluation on `square` (in pawns).

    Returns the net material the side NOT occupying the square wins by
    initiating captures there, assuming both sides recapture with their least
    valuable piece and each stops when continuing would lose material. A
    positive result means the occupant is effectively hanging (or is a
    material sacrifice); 0 or negative means the capture doesn't win material.

    This is the standard swap algorithm. It ignores x-ray/discovered
    attackers and pins -- good enough to tell a real hang from a defended
    piece, which is what trips up naive attacker/defender counting.
    """
    occupant = board.piece_at(square)
    if occupant is None:
        return 0
    b = board.copy(stack=False)
    side = not occupant.color            # the side that captures first
    standing = PIECE_VALUE[occupant.piece_type]  # value sitting on the square now
    gains: list[int] = []
    while True:
        attackers = b.attackers(side, square)
        if not attackers:
            break
        from_sq = min(attackers, key=lambda s: PIECE_VALUE[b.piece_at(s).piece_type])
        mover_val = PIECE_VALUE[b.piece_at(from_sq).piece_type]
        gains.append(standing)           # `side` captures whatever stands there
        standing = mover_val             # the capturer now stands on the square
        b.set_piece_at(square, b.piece_at(from_sq))
        b.remove_piece_at(from_sq)
        side = not side
    # Negamax resolution with stand-pat: each side captures only if it helps.
    acc = 0
    for g in reversed(gains):
        acc = max(0, g - acc)
    return acc


def detect_hanging(board_after: chess.Board, mover: chess.Color) -> list[Motif]:
    """Find mover's pieces the opponent can actually win material on.

    Uses Static Exchange Evaluation, so a piece defended adequately (even by
    a pawn) is NOT flagged, and a piece attacked by a cheaper piece IS.
    """
    out: list[tuple[int, Motif]] = []
    for sq, piece in board_after.piece_map().items():
        if piece.color != mover or piece.piece_type == chess.KING:
            continue
        gain = static_exchange_eval(board_after, sq)
        if gain > 0:
            defenders = board_after.attackers(mover, sq)
            how = "undefended" if not defenders else "inadequately defended"
            out.append((gain, Motif(
                kind="hangs_piece",
                tactical=True,
                text=f"the {_NAME[piece.piece_type]} on {_square_name(sq)} is {how} "
                     f"(loses ~{gain})",
            )))
    # Report the costliest hang first.
    out.sort(key=lambda t: t[0], reverse=True)
    return [m for _, m in out[:2]]


def detect_fork(board_after: chess.Board, move: chess.Move, mover: chess.Color) -> list[Motif]:
    """Detect a simple fork: the moved piece attacks 2+ valuable targets.

    Skipped if the forking piece is itself hanging (SEE > 0) -- a "fork" that
    the opponent answers by just capturing the forker is not a real fork.
    """
    piece = board_after.piece_at(move.to_square)
    if piece is None or piece.color != mover:
        return []
    if static_exchange_eval(board_after, move.to_square) > 0:
        return []  # the forking piece can simply be taken
    opp = not mover
    targets = []
    for tsq in board_after.attacks(move.to_square):
        tp = board_after.piece_at(tsq)
        if tp and tp.color == opp and PIECE_VALUE[tp.piece_type] >= 3:
            if tp.piece_type == chess.KING or PIECE_VALUE[tp.piece_type] > PIECE_VALUE[piece.piece_type]:
                targets.append(_NAME[tp.piece_type])
    if len(targets) >= 2:
        return [
            Motif(
                kind="fork",
                tactical=True,
                text=f"the {_NAME[piece.piece_type]} forks {', '.join(targets)}",
            )
        ]
    return []


def material_swing_on_line(board_before_reply: chess.Board, pv: list[chess.Move], mover: chess.Color) -> int:
    """Net material the mover loses over the first plies of the refutation PV.

    Positive result = mover loses that many points of material in the forced
    line. This is the concrete, countable punishment behind a tactical error.
    """
    b = board_before_reply.copy(stack=False)
    gained = {chess.WHITE: 0, chess.BLACK: 0}
    for mv in pv[:6]:
        if mv not in b.legal_moves:
            break
        if b.is_capture(mv):
            captured_sq = mv.to_square
            if b.is_en_passant(mv):
                cap_piece_type = chess.PAWN
            else:
                cap = b.piece_at(captured_sq)
                cap_piece_type = cap.piece_type if cap else None
            if cap_piece_type is not None:
                gained[b.turn] += PIECE_VALUE[cap_piece_type]
        b.push(mv)
    return gained[not mover] - gained[mover]


def static_features(board_before: chess.Board, move: chess.Move) -> list[Motif]:
    """Positional hints derived from the move itself (soft signals)."""
    out: list[Motif] = []
    mover = board_before.turn
    piece = board_before.piece_at(move.from_square)
    if piece is None:
        return out

    # Lost castling rights by moving king/rook while still allowed to castle.
    if piece.piece_type == chess.KING and not board_before.is_castling(move):
        if board_before.has_castling_rights(mover):
            out.append(Motif("loses_castling", False, "it gives up the right to castle"))
    if piece.piece_type == chess.ROOK and board_before.has_castling_rights(mover):
        out.append(Motif("loses_castling_rook", False, "it may forfeit castling on that side"))

    # Castling = king safety (positive).
    if board_before.is_castling(move):
        out.append(Motif("castles", False, "it tucks the king to safety and connects the rooks"))

    # Central pawn push / space.
    central = {chess.D4, chess.E4, chess.D5, chess.E5}
    if piece.piece_type == chess.PAWN and move.to_square in central:
        out.append(Motif("central_pawn", False, "it stakes a claim in the centre"))

    # Development of a minor piece off the back rank.
    back_rank = 0 if mover == chess.WHITE else 7
    if piece.piece_type in (chess.KNIGHT, chess.BISHOP):
        if chess.square_rank(move.from_square) == back_rank:
            out.append(Motif("develops", False, f"it develops a {_NAME[piece.piece_type]}"))

    return out


def build_motifs(
    board_before: chess.Board,
    move: chess.Move,
    played_eval: MoveEval,
    *,
    is_good: bool = False,
) -> MotifReport:
    """Assemble the full motif report for a played move.

    `played_eval.pv` is the opponent's refutation line (the PV of the position
    *after* the move), used for the material-swing and refutation text.

    `is_good` says the engine rated this move best/excellent. When true we do
    NOT narrate it with blunder motifs (a hanging piece / lost material is then
    an intentional, sound sacrifice), which would otherwise read as if a good
    move were a mistake.
    """
    mover = board_before.turn
    san = board_before.san(move)
    board_after = board_before.copy(stack=False)
    board_after.push(move)

    # Checkmate dominates everything else and makes "hanging"/"recapture"
    # reasoning meaningless (the game is over), so report it on its own.
    if board_after.is_checkmate():
        return MotifReport(move_san=san, motifs=[
            Motif("checkmate", True, "it delivers checkmate")
        ])

    motifs: list[Motif] = []

    if is_good:
        # Positive framing only. If the engine's best move gives up material,
        # name it as a sound sacrifice and show the line it justifies.
        sac = static_exchange_eval(board_after, move.to_square)
        if sac >= 2 and played_eval.pv_san:
            line = " ".join(played_eval.pv_san[:4])
            motifs.append(Motif(
                "sound_sacrifice", True,
                f"it soundly sacrifices ~{sac} point(s); the engine's line is {line}",
            ))
        motifs += detect_fork(board_after, move, mover)
        if board_after.is_check():
            motifs.append(Motif("gives_check", True, "it gives check"))
        if board_before.is_capture(move) and sac <= 0:
            motifs.append(Motif("captures", True, "it wins material"))
        motifs += static_features(board_before, move)
        return MotifReport(move_san=san, motifs=motifs)

    # --- a sub-par move: explain the concrete downside first ---

    # Allowing a forced mate is the most important thing to say.
    if played_eval.mate_in is not None and played_eval.mate_in < 0 and played_eval.pv_san:
        n = abs(played_eval.mate_in)
        line = " ".join(played_eval.pv_san[:4])
        motifs.append(Motif(
            "allows_mate", True,
            f"it allows a forced mate in {n} ({line})",
        ))

    motifs += detect_fork(board_after, move, mover)
    motifs += detect_hanging(board_after, mover)

    # The refutation: the concrete material the opponent wins in the main line.
    allows_mate = any(m.kind == "allows_mate" for m in motifs)
    loss = material_swing_on_line(board_after, played_eval.pv, mover)
    if loss > 0 and played_eval.pv_san and not allows_mate:
        line = " ".join(played_eval.pv_san[:4])
        motifs.append(
            Motif(
                "refuted",
                True,
                f"the opponent wins ~{loss} point(s) of material with {line}",
            )
        )

    # --- secondary tactical facts about the move itself ---
    if board_after.is_check():
        motifs.append(Motif("gives_check", True, "it gives check"))
    if board_before.is_capture(move):
        motifs.append(Motif("captures", True, "it captures material"))

    # --- positional hints ---
    motifs += static_features(board_before, move)

    return MotifReport(move_san=san, motifs=motifs)
