"""Game storage (SQLite, stdlib only).

Persists played and imported games with their per-move analysis so the app can
build a dashboard of a learner's recurring patterns. One SQLite file, no
server, no extra dependency.

Location: $CHESSCOACH_DB, else ./chesscoach_games.db.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager

_DB_PATH = os.environ.get("CHESSCOACH_DB", "chesscoach_games.db")
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at  REAL NOT NULL,
  source      TEXT NOT NULL,           -- 'play' | 'pgn' | 'lichess'
  white       TEXT,
  black       TEXT,
  result      TEXT,                    -- '1-0' | '0-1' | '1/2-1/2' | '*'
  human_color TEXT,                    -- 'white' | 'black' | null (import)
  level       INTEGER,
  white_acc   REAL,
  black_acc   REAL,
  ply_count   INTEGER NOT NULL,
  pgn         TEXT
);
CREATE TABLE IF NOT EXISTS moves (
  game_id   INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  ply       INTEGER NOT NULL,
  side      TEXT NOT NULL,             -- 'white' | 'black'
  san       TEXT NOT NULL,
  uci       TEXT,
  quality   TEXT,                      -- best/good/.../blunder, null if not analysed
  cp_loss   INTEGER,
  eval_cp   INTEGER,
  tag       TEXT                       -- primary mistake motif, e.g. 'hangs_piece'
);
CREATE INDEX IF NOT EXISTS idx_moves_game ON moves(game_id);
CREATE TABLE IF NOT EXISTS profile (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  total_xp    REAL NOT NULL DEFAULT 0,
  games       INTEGER NOT NULL DEFAULT 0,
  wins        INTEGER NOT NULL DEFAULT 0,
  best_acc    REAL NOT NULL DEFAULT 0,
  best_streak INTEGER NOT NULL DEFAULT 0
);
"""


def db_path() -> str:
    return _DB_PATH


@contextmanager
def _conn():
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.executescript(_SCHEMA)
            yield conn
            conn.commit()
        finally:
            conn.close()


def save_game(game: dict, moves: list[dict]) -> int:
    """Insert a game and its moves. Returns the new game id.

    `game` keys: source, white, black, result, human_color, level,
    white_acc, black_acc, pgn. `moves` items: ply, side, san, uci, quality,
    cp_loss, eval_cp, tag.
    """
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO games
               (created_at, source, white, black, result, human_color, level,
                white_acc, black_acc, ply_count, pgn)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                game.get("created_at", time.time()), game["source"],
                game.get("white"), game.get("black"), game.get("result"),
                game.get("human_color"), game.get("level"),
                game.get("white_acc"), game.get("black_acc"),
                len(moves), game.get("pgn"),
            ),
        )
        gid = cur.lastrowid
        conn.executemany(
            """INSERT INTO moves
               (game_id, ply, side, san, uci, quality, cp_loss, eval_cp, tag)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(gid, m["ply"], m["side"], m["san"], m.get("uci"), m.get("quality"),
              m.get("cp_loss"), m.get("eval_cp"), m.get("tag")) for m in moves],
        )
        return gid


def list_games(limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM games ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_game(game_id: int) -> dict | None:
    with _conn() as conn:
        g = conn.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if g is None:
            return None
        moves = conn.execute(
            "SELECT * FROM moves WHERE game_id=? ORDER BY ply", (game_id,)
        ).fetchall()
        out = dict(g)
        out["moves"] = [dict(m) for m in moves]
        return out


def all_games_with_moves() -> list[dict]:
    """Every game with its moves attached (two queries), for analytics."""
    with _conn() as conn:
        games = [dict(r) for r in conn.execute("SELECT * FROM games ORDER BY created_at").fetchall()]
        by_id = {g["id"]: g for g in games}
        for g in games:
            g["moves"] = []
        for m in conn.execute("SELECT * FROM moves ORDER BY game_id, ply").fetchall():
            g = by_id.get(m["game_id"])
            if g is not None:
                g["moves"].append(dict(m))
        return games


def delete_game(game_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM moves WHERE game_id=?", (game_id,))
        conn.execute("DELETE FROM games WHERE id=?", (game_id,))


def get_profile() -> dict:
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO profile(id) VALUES (1)")
        return dict(conn.execute("SELECT * FROM profile WHERE id = 1").fetchone())


def add_result(xp: float, won: bool, accuracy: float | None, streak: int = 0) -> dict:
    """Record a finished game into the running profile; returns the new profile."""
    with _conn() as conn:
        conn.execute("INSERT OR IGNORE INTO profile(id) VALUES (1)")
        conn.execute(
            """UPDATE profile SET total_xp = total_xp + ?, games = games + 1,
                   wins = wins + ?, best_acc = MAX(best_acc, ?), best_streak = MAX(best_streak, ?)
               WHERE id = 1""",
            (xp, 1 if won else 0, accuracy or 0, streak),
        )
        return dict(conn.execute("SELECT * FROM profile WHERE id = 1").fetchone())


def tag_stats(tag: str) -> dict:
    """How often the learner has made a mistake of this motif before.

    Counts only the human's side of played games, and only moves graded
    inaccuracy/mistake/blunder. Used to tell a player they are repeating a
    known pattern. The current (unsaved) game is naturally excluded.
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT m.game_id, g.created_at
                 FROM moves m JOIN games g ON g.id = m.game_id
                WHERE g.human_color IS NOT NULL AND m.side = g.human_color
                  AND m.tag = ? AND m.quality IN ('inaccuracy','mistake','blunder')""",
            (tag,),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM games WHERE human_color IS NOT NULL"
        ).fetchone()["c"]
    return {"games": len(rows), "total": total,
            "last": max((r["created_at"] for r in rows), default=None)}


def dashboard(human_only: bool = True) -> dict:
    """Aggregate stats across stored games for the dashboard.

    By default focuses on the human side of played games (where human_color is
    set), since that is the learner we are coaching.
    """
    with _conn() as conn:
        games = [dict(r) for r in conn.execute(
            "SELECT * FROM games ORDER BY created_at").fetchall()]

        # Per-game accuracy for the learner's side, plus W/D/L.
        points = []       # {t, acc, result}
        wins = draws = losses = 0
        for g in games:
            hc = g["human_color"]
            acc = None
            if hc == "white":
                acc = g["white_acc"]
            elif hc == "black":
                acc = g["black_acc"]
            if hc and g["result"] in ("1-0", "0-1", "1/2-1/2"):
                if g["result"] == "1/2-1/2":
                    draws += 1
                elif (g["result"] == "1-0") == (hc == "white"):
                    wins += 1
                else:
                    losses += 1
            if acc is not None:
                points.append({"t": g["created_at"], "acc": acc,
                               "result": g["result"], "id": g["id"]})

        # Mistake-type breakdown and quality distribution over the learner's
        # analysed moves (played games only, the human's side).
        tag_counts: dict[str, int] = {}
        quality_counts: dict[str, int] = {}
        clause = ""
        params: tuple = ()
        if human_only:
            clause = (" JOIN games g ON g.id = m.game_id "
                      " WHERE g.human_color IS NOT NULL AND g.human_color = m.side ")
        rows = conn.execute(
            "SELECT m.quality AS quality, m.tag AS tag FROM moves m" + clause, params
        ).fetchall()
        for r in rows:
            if r["quality"]:
                quality_counts[r["quality"]] = quality_counts.get(r["quality"], 0) + 1
            if r["tag"] and r["quality"] in ("inaccuracy", "mistake", "blunder"):
                tag_counts[r["tag"]] = tag_counts.get(r["tag"], 0) + 1

        return {
            "gameCount": len(games),
            "record": {"wins": wins, "draws": draws, "losses": losses},
            "accuracyTrend": points,
            "qualityCounts": quality_counts,
            "mistakeTags": tag_counts,
        }
