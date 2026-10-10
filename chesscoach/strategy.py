"""Strategic (long-term) analysis — plans, not just the next move.

Chess understanding is about imbalances and plans across many moves, but an
engine *searches*; it does not think in plans and cannot state one. So we infer
plans two ways, and stay honest that it is inference:

  1. Static imbalance analysis (Silman-style): detect the position's lasting
     features — pawn majorities, outposts, open files, weak pawns, the bishop
     pair, space, king safety — and map each to the standard correct plan.
  2. Theme from the engine's line: read the principal variation a few moves
     deep and name what it is actually doing (a pawn break, a knight
     manoeuvre, trading into an endgame, a king attack).

These are heuristics. The engine's evaluation remains the authority on who is
better; this module explains the *character* of the position and the plans that
character implies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from .motifs import PIECE_VALUE
from .positional import king_danger, mobility

_NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
         chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}


@dataclass
class Brief:
    phase: str
    side: str                       # side to move, "White"/"Black"
    character: str                  # one-line description of the position type
    your_plan: list[str] = field(default_factory=list)
    opponent_plan: list[str] = field(default_factory=list)
    pawn_breaks: list[str] = field(default_factory=list)
    improve: str | None = None
    line_theme: str | None = None   # filled from the engine PV when available


# ---------------------------------------------------------------- phase
def phase(board: chess.Board) -> str:
    npm = 0  # non-pawn, non-king material, both sides
    queens = 0
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        cnt = len(board.pieces(pt, chess.WHITE)) + len(board.pieces(pt, chess.BLACK))
        npm += cnt * PIECE_VALUE[pt]
        if pt == chess.QUEEN:
            queens = cnt
    if npm <= 16 or (queens == 0 and npm <= 24):
        return "endgame"
    both_castled = _castled(board, chess.WHITE) and _castled(board, chess.BLACK)
    developed = _developed(board, chess.WHITE) + _developed(board, chess.BLACK)
    if board.fullmove_number <= 10 and developed < 6 and not both_castled:
        return "opening"
    return "middlegame"


def _castled(board, color):
    ksq = board.king(color)
    return ksq is not None and chess.square_file(ksq) in (2, 6)


def _developed(board, color):
    back = 0 if color == chess.WHITE else 7
    return sum(1 for pt in (chess.KNIGHT, chess.BISHOP)
               for sq in board.pieces(pt, color) if chess.square_rank(sq) != back)


# ---------------------------------------------------------------- helpers
QUEENSIDE = (0, 1, 2)
KINGSIDE = (5, 6, 7)


def _pawn_files(board, color):
    files = [0] * 8
    for sq in board.pieces(chess.PAWN, color):
        files[chess.square_file(sq)] += 1
    return files


def _wing_majority(board, color, wing):
    me = sum(_pawn_files(board, color)[f] for f in wing)
    opp = sum(_pawn_files(board, not color)[f] for f in wing)
    return me - opp


def _open_files(board):
    wp, bp = _pawn_files(board, chess.WHITE), _pawn_files(board, chess.BLACK)
    return [f for f in range(8) if wp[f] == 0 and bp[f] == 0]


def _semi_open_files(board, color):
    mine = _pawn_files(board, color)
    opp = _pawn_files(board, not color)
    return [f for f in range(8) if mine[f] == 0 and opp[f] > 0]


def _weak_enemy_pawns(board, color):
    """Return file letters of enemy isolated/doubled pawns (targets)."""
    opp = not color
    files = _pawn_files(board, opp)
    weak = []
    for f in range(8):
        if files[f] == 0:
            continue
        isolated = not (f > 0 and files[f - 1]) and not (f < 7 and files[f + 1])
        if isolated or files[f] > 1:
            weak.append(chess.FILE_NAMES[f])
    return weak


def _space(board, color):
    """Squares in the enemy half controlled by our pawns (a space proxy)."""
    ranks = range(4, 8) if color == chess.WHITE else range(0, 4)
    score = 0
    for sq in board.pieces(chess.PAWN, color):
        for tsq in board.attacks(sq):
            if chess.square_rank(tsq) in ranks:
                score += 1
    return score


def _outpost(board, color):
    """A protected square in the enemy camp no enemy pawn can attack.

    Returns the square name of the best such square (central files), or None.
    """
    opp = not color
    opp_pawn_files = [chess.square_file(s) for s in board.pieces(chess.PAWN, opp)]
    rel_ranks = (4, 5) if color == chess.WHITE else (3, 2)  # 5th/6th from our side
    best = None
    for sq in chess.SQUARES:
        if chess.square_rank(sq) not in rel_ranks:
            continue
        f = chess.square_file(sq)
        if f in (0, 7):
            continue
        # protected by one of our pawns?
        if not any(board.piece_at(a) and board.piece_at(a).piece_type == chess.PAWN
                   and board.piece_at(a).color == color for a in board.attackers(color, sq)):
            continue
        # can any enemy pawn ever attack it? (enemy pawn on an adjacent file, behind it)
        attackable = False
        for af in (f - 1, f + 1):
            if af in opp_pawn_files:
                for ps in board.pieces(chess.PAWN, opp):
                    if chess.square_file(ps) == af:
                        ahead = (chess.square_rank(ps) > chess.square_rank(sq)) if color == chess.WHITE \
                                else (chess.square_rank(ps) < chess.square_rank(sq))
                        if ahead:
                            attackable = True
        if not attackable:
            best = chess.square_name(sq)
            if f in (3, 4):   # prefer d/e files
                return best
    return best


def _pawn_breaks(board, color):
    """Pawn pushes that strike the enemy pawn chain (candidate breaks)."""
    breaks = []
    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)
        if piece is None or piece.piece_type != chess.PAWN:
            continue
        # a break either captures, or advances to a square attacked by an enemy pawn
        if board.is_capture(move):
            breaks.append(board.san(move))
            continue
        b2 = board.copy(stack=False)
        tgt = move.to_square
        b2.push(move)
        if any(board.piece_at(s) and board.piece_at(s).piece_type == chess.PAWN
               and board.piece_at(s).color != color for s in board.attackers(not color, tgt)):
            breaks.append(board.san(move))
    # keep the most thematic (central / contact) few
    return breaks[:3]


def _worst_piece(board, color):
    """The least active minor/rook and a suggestion to improve it."""
    worst, worst_mob = None, 99
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK):
        for sq in board.pieces(pt, color):
            m = len(board.attacks(sq))
            if m < worst_mob:
                worst_mob, worst = m, (pt, sq)
    if worst and worst_mob <= 3:
        pt, sq = worst
        return f"your {_NAME[pt]} on {chess.square_name(sq)} is passive — find it a better square"
    return None


# ---------------------------------------------------------------- brief
def strategic_brief(board: chess.Board) -> Brief:
    mover = board.turn
    side = "White" if mover == chess.WHITE else "Black"
    ph = phase(board)
    br = Brief(phase=ph, side=side, character="")

    def plans_for(color, bucket):
        # Plans are phrased neutrally (no "your") so they read correctly for
        # both the mover ("Your plan: …") and the opponent ("Watch for … to …").
        for wing, name in ((QUEENSIDE, "queenside"), (KINGSIDE, "kingside")):
            if _wing_majority(board, color, wing) >= 1:
                bucket.append(f"advance the {name} pawn majority to create a passed pawn")
                break
        of = _open_files(board)
        sf = _semi_open_files(board, color)
        if board.pieces(chess.ROOK, color):
            if of:
                bucket.append(f"seize the open {chess.FILE_NAMES[of[0]]}-file with a rook")
            elif sf:
                bucket.append(f"use the semi-open {chess.FILE_NAMES[sf[0]]}-file to pressure enemy pawns")
        op = _outpost(board, color)
        if op:
            bucket.append(f"plant a knight on the {op} outpost")
        weak = _weak_enemy_pawns(board, color)
        if weak:
            bucket.append(f"pile up on the weak {weak[0]}-pawn")
        # bishop pair — only an edge if the opponent does NOT also have two.
        if len(board.pieces(chess.BISHOP, color)) >= 2 and len(board.pieces(chess.BISHOP, not color)) < 2:
            bucket.append("open the position to make the bishop pair count")
        if _space(board, color) - _space(board, not color) >= 3:
            bucket.append("use the space advantage and avoid trades")
        if king_danger(board, not color) >= 5:
            bucket.append("attack the exposed enemy king")

    plans_for(mover, br.your_plan)
    plans_for(not mover, br.opponent_plan)
    br.pawn_breaks = _pawn_breaks(board, mover)
    br.improve = _worst_piece(board, mover)

    # character line
    bits = []
    if _space(board, mover) - _space(board, not mover) >= 3:
        bits.append("you have a space advantage")
    if len(board.pieces(chess.BISHOP, mover)) >= 2 and len(board.pieces(chess.BISHOP, not mover)) < 2:
        bits.append("you hold the bishop pair")
    of = _open_files(board)
    if of:
        bits.append(f"the {chess.FILE_NAMES[of[0]]}-file is open")
    br.character = (ph.capitalize() + " position" + (": " + ", ".join(bits) if bits else "") + ".")
    return br


# ---------------------------------------------------------------- PV theme
def plan_from_line(board: chess.Board, pv: list[chess.Move]) -> str | None:
    """Name the theme of the engine's principal variation (best-play line)."""
    if not pv:
        return None
    mover = board.turn
    b = board.copy(stack=False)
    queens_before = len(b.pieces(chess.QUEEN, chess.WHITE)) + len(b.pieces(chess.QUEEN, chess.BLACK))
    our_breaks = []
    knight_dests = {}
    for i, mv in enumerate(pv[:10]):
        if mv not in b.legal_moves:
            break
        piece = b.piece_at(mv.from_square)
        if piece and piece.color == mover:
            if piece.piece_type == chess.PAWN and (b.is_capture(mv) or True):
                if b.is_capture(mv):
                    our_breaks.append(b.san(mv))
            if piece.piece_type == chess.KNIGHT:
                knight_dests[mv.from_square] = mv.to_square
        b.push(mv)
    queens_after = len(b.pieces(chess.QUEEN, chess.WHITE)) + len(b.pieces(chess.QUEEN, chess.BLACK))

    if queens_before > queens_after:
        return "the engine's plan is to trade queens and head for a favourable endgame"
    if our_breaks:
        return f"the engine's plan is the {our_breaks[0]} pawn break to open lines"
    if knight_dests:
        dst = chess.square_name(list(knight_dests.values())[-1])
        return f"the engine's plan is to manoeuvre a knight toward {dst}"
    # king attack: many of our pieces pointing at the enemy king in the line
    if king_danger(b, not mover) >= king_danger(board, not mover) + 2:
        return "the engine's plan is to build an attack on the enemy king"
    return None
