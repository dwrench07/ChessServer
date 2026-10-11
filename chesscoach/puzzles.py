"""Puzzle Rush from your own blunders.

The most instructive puzzles a player can face are the ones drawn from their
own mistakes: the exact positions where *they* went wrong. This module mines
stored games for the learner's mistakes and blunders and reconstructs the
position *before* each one, so the app can hand it back as "you went wrong
here — find the move you missed."

Reconstruction replays the stored UCI move list (no engine, no PGN parsing),
so puzzle *listing* is cheap and instant. The solution itself is computed by
the engine at solve time (see webapp.server.api_puzzle_check) — the engine
remains the single source of truth; this layer never invents a best move.
"""

from __future__ import annotations

import chess

# Only mistakes and blunders make puzzles — an inaccuracy rarely has a single
# clean "right answer" to find, which is what a puzzle needs.
_PUZZLE_QUALITIES = ("mistake", "blunder")

# A puzzle needs a real, findable improvement. Below this the "mistake" is
# often just engine noise and there is nothing satisfying to spot.
_MIN_CP_LOSS = 80


def _theme(tag: str | None) -> str:
    """A short, human label for the kind of mistake, shown on the puzzle."""
    return {
        "hangs_piece": "Don't hang it",
        "allows_fork": "Spot the fork",
        "missed_fork": "Spot the fork",
        "allows_capture": "Count the trade",
        "missed_mate": "Finish the attack",
        "allows_mate": "Stop the mate",
        "missed_win": "Find the win",
    }.get(tag or "", "Find the better move")


def extract_puzzles(games: list[dict], *, limit: int = 40,
                    order: str = "severity") -> list[dict]:
    """Mine the learner's own mistakes into solvable puzzles.

    `games` are rows from store.all_games_with_moves(). Only played games with
    a known human side are mined, and only the human's own mistakes/blunders.
    Positions are deduplicated by FEN (keeping the most severe), so the same
    recurring blunder does not flood the queue.

    order: 'severity' (biggest blunders first, most instructive) or
           'recency' (most recent games first).
    """
    seen: dict[str, dict] = {}
    for g in games:
        hc = g.get("human_color")
        if hc not in ("white", "black"):
            continue
        board = chess.Board()
        for m in g.get("moves", []):
            uci = m.get("uci")
            if not uci:
                break  # cannot reconstruct further without the move
            try:
                mv = chess.Move.from_uci(uci)
            except ValueError:
                break
            if mv not in board.legal_moves:
                break  # stored data is inconsistent; stop replaying this game

            is_human = m.get("side") == hc
            quality = m.get("quality")
            cp_loss = m.get("cp_loss")
            if (is_human and quality in _PUZZLE_QUALITIES
                    and cp_loss is not None and cp_loss >= _MIN_CP_LOSS):
                fen_before = board.fen()
                puzzle = {
                    "fen": fen_before,
                    "sideToMove": "white" if board.turn == chess.WHITE else "black",
                    "playedUci": uci,
                    "playedSan": m.get("san"),
                    "quality": quality,
                    "cpLoss": cp_loss,
                    "tag": m.get("tag"),
                    "theme": _theme(m.get("tag")),
                    "gameId": g.get("id"),
                    "ply": m.get("ply"),
                    "createdAt": g.get("created_at"),
                }
                prev = seen.get(fen_before)
                # Keep the most severe instance of a repeated position.
                if prev is None or cp_loss > prev["cpLoss"]:
                    seen[fen_before] = puzzle

            board.push(mv)

    puzzles = list(seen.values())
    if order == "recency":
        puzzles.sort(key=lambda p: (-(p["createdAt"] or 0), -p["cpLoss"]))
    else:  # severity
        puzzles.sort(key=lambda p: (-p["cpLoss"], -(p["createdAt"] or 0)))
    return puzzles[:limit]
