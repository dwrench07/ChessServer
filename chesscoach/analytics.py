"""Learning analytics: deeper per-player insight from stored games.

All of this is derived from data already stored (PGNs + per-move centipawn
records), replayed statically with python-chess — no engine, no new data.

  * accuracy by game phase   — are you worse in the endgame than the opening?
  * performance by opening    — which openings you score and play well/badly in.
  * weakness trend            — is a recurring mistake getting better or worse?
"""

from __future__ import annotations

import io

import chess
import chess.pgn

from .accuracy import accuracy_from_cp, game_accuracy
from .strategy import phase as _phase

# Longest-prefix opening table (SAN). Enough to bucket a learner's repertoire;
# not a full ECO classifier.
_OPENINGS = [
    (("e4", "e5", "Nf3", "Nc6", "Bb5"), "Ruy Lopez"),
    (("e4", "e5", "Nf3", "Nc6", "Bc4"), "Italian Game"),
    (("e4", "e5", "Nf3", "Nc6", "d4"), "Scotch Game"),
    (("e4", "e5", "Nf3", "Nf6"), "Petrov Defense"),
    (("e4", "e5", "Nf3"), "Open Game"),
    (("e4", "e5", "Bc4"), "Bishop's Opening"),
    (("e4", "e5"), "King's Pawn, Open"),
    (("e4", "c5"), "Sicilian Defense"),
    (("e4", "e6"), "French Defense"),
    (("e4", "c6"), "Caro-Kann Defense"),
    (("e4", "d6"), "Pirc Defense"),
    (("e4", "g6"), "Modern Defense"),
    (("e4", "d5"), "Scandinavian Defense"),
    (("e4", "Nf6"), "Alekhine Defense"),
    (("d4", "d5", "c4"), "Queen's Gambit"),
    (("d4", "Nf6", "c4", "g6"), "King's Indian / Grünfeld"),
    (("d4", "Nf6", "c4", "e6"), "Nimzo/Queen's Indian"),
    (("d4", "Nf6", "c4"), "Indian Defense"),
    (("d4", "Nf6"), "Indian Game"),
    (("d4", "d5"), "Queen's Pawn, Closed"),
    (("d4", "f5"), "Dutch Defense"),
    (("c4",), "English Opening"),
    (("Nf3",), "Réti Opening"),
    (("d4",), "Queen's Pawn"),
    (("e4",), "King's Pawn"),
]


def name_opening(sans: list[str]) -> str:
    for prefix, name in _OPENINGS:
        if tuple(sans[:len(prefix)]) == prefix:
            return name
    return "Irregular"


def _mainline_sans(pgn: str, limit: int = 6) -> list[str]:
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return []
    out, board = [], game.board()
    for mv in game.mainline_moves():
        out.append(board.san(mv))
        board.push(mv)
        if len(out) >= limit:
            break
    return out


def _acc(move: dict):
    if move.get("cp_loss") is None or move.get("eval_cp") is None:
        return None
    return accuracy_from_cp(int(move["eval_cp"]) + int(move["cp_loss"]), int(move["eval_cp"]))


def compute(games: list[dict]) -> dict:
    """`games` are rows from store.all_games_with_moves() (each with 'moves')."""
    phase_acc = {"opening": [], "middlegame": [], "endgame": []}
    openings: dict[str, dict] = {}
    tag_recent: dict[str, int] = {}
    tag_older: dict[str, int] = {}

    # Split games into older/recent halves for the weakness trend.
    human_games = [g for g in games if g.get("human_color")]
    cutoff = len(human_games) // 2

    for idx, g in enumerate(human_games):
        hc = g["human_color"]
        moves = g.get("moves", [])
        pgn = g.get("pgn")

        # accuracy by phase (replay to know each ply's phase)
        if pgn:
            game = chess.pgn.read_game(io.StringIO(pgn))
            if game is not None:
                board = game.board()
                by_ply = {m["ply"]: m for m in moves}
                ply = 0
                for mv in game.mainline_moves():
                    ply += 1
                    side = "white" if board.turn == chess.WHITE else "black"
                    if side == hc:
                        rec = by_ply.get(ply)
                        if rec is not None:
                            a = _acc(rec)
                            if a is not None:
                                phase_acc[_phase(board)].append(a)
                    board.push(mv)

            # opening bucket
            name = name_opening(_mainline_sans(pgn))
            o = openings.setdefault(name, {"games": 0, "accs": [], "score": 0.0})
            o["games"] += 1
            ga = g["white_acc"] if hc == "white" else g["black_acc"]
            if ga is not None:
                o["accs"].append(ga)
            res = g.get("result")
            if res in ("1-0", "0-1", "1/2-1/2"):
                o["score"] += 0.5 if res == "1/2-1/2" else (1.0 if (res == "1-0") == (hc == "white") else 0.0)

        # weakness trend: tally mistake tags in older vs recent half
        bucket = tag_older if idx < cutoff else tag_recent
        for m in moves:
            if m["side"] == hc and m.get("tag") and m.get("quality") in ("inaccuracy", "mistake", "blunder"):
                bucket[m["tag"]] = bucket.get(m["tag"], 0) + 1

    by_phase = {ph: round(sum(v) / len(v), 1) for ph, v in phase_acc.items() if v}
    by_opening = []
    for name, o in sorted(openings.items(), key=lambda kv: kv[1]["games"], reverse=True):
        by_opening.append({
            "opening": name, "games": o["games"],
            "accuracy": round(sum(o["accs"]) / len(o["accs"]), 1) if o["accs"] else None,
            "score": round(100 * o["score"] / o["games"]) if o["games"] else None,
        })
    trend = []
    for tag in set(list(tag_older) + list(tag_recent)):
        trend.append({"tag": tag, "older": tag_older.get(tag, 0), "recent": tag_recent.get(tag, 0)})
    trend.sort(key=lambda t: t["older"] + t["recent"], reverse=True)

    return {"accuracyByPhase": by_phase, "byOpening": by_opening[:6], "weaknessTrend": trend[:5]}
