"""chesscoach local web server.

A dependency-light (stdlib only) HTTP server that serves the board UI and a
small JSON API wrapping the chesscoach pipeline. One Stockfish process is
shared across requests and guarded by a lock, because UCI engines are not
concurrency-safe and this is a single-user local tool.

Run:
    python -m webapp.server            # then open http://localhost:8000
    python -m webapp.server --port 9000 --host 0.0.0.0
Environment (same as the CLI):
    CHESSCOACH_STOCKFISH, CHESSCOACH_MODEL, OLLAMA_URL
"""

from __future__ import annotations

import argparse
import io
import json
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chess
import chess.pgn

from chesscoach import store
from chesscoach.accuracy import accuracy_from_cp, game_accuracy
from chesscoach.classify import Quality, classify
from chesscoach.coach import _is_sacrifice
from chesscoach.engine import Analyzer, find_stockfish
from chesscoach.explain import (CoachingFacts, explain, ollama_available,
                                OLLAMA_MODEL, strategic_explanation)
from chesscoach.motifs import build_motifs
from chesscoach.strategy import strategic_brief, plan_from_line, phase as game_phase

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
GOOD = (Quality.BRILLIANT, Quality.BEST, Quality.EXCELLENT)

# --- single shared engine, serialized -------------------------------------
_engine_lock = threading.Lock()
_analyzer: Analyzer | None = None
_movetime = 0.4


def get_analyzer() -> Analyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = Analyzer(movetime_s=_movetime)
    return _analyzer


def _sq(i: int) -> str:
    return chess.square_name(i)


def _game_state(board: chess.Board) -> dict:
    over = board.is_game_over()
    status = None
    if over:
        outcome = board.outcome()
        if outcome and outcome.winner is not None:
            status = ("White" if outcome.winner == chess.WHITE else "Black") + " wins"
        elif outcome:
            status = "Draw"
        if outcome and outcome.termination:
            status = f"{status} ({outcome.termination.name.lower().replace('_', ' ')})"
    return {
        "fen": board.fen(),
        "turn": "White" if board.turn == chess.WHITE else "Black",
        "inCheck": board.is_check(),
        "gameOver": over,
        "status": status,
    }


def coach_payload(board: chess.Board, move: chess.Move, use_llm: bool) -> dict:
    """Full coaching for `move` played from `board` (engine is the truth)."""
    mover = "White" if board.turn == chess.WHITE else "Black"
    with _engine_lock:
        az = get_analyzer()
        pre = az.analyse_position(board, multipv=3)
        played = az.evaluate_after(board, move)
    verdict = classify(pre.best, played, is_sacrifice=_is_sacrifice(board, move))
    good = verdict.quality in GOOD
    motifs = build_motifs(board, move, played, is_good=good)
    facts = CoachingFacts(
        mover=mover, move_san=played.san, quality=verdict,
        best_move_san=pre.best.san, best_line_san=pre.best.pv_san,
        refutation_san=played.pv_san, motif_report=motifs,
        eval_before_cp=pre.best.score_cp, eval_after_cp=played.score_cp,
    )
    text, source = explain(facts, use_llm=use_llm)

    after = board.copy(stack=False)
    san = board.san(move)
    after.push(move)
    refute_from = refute_to = None
    if played.pv:
        refute_from, refute_to = _sq(played.pv[0].from_square), _sq(played.pv[0].to_square)
    # Primary mistake motif (the leading concrete fact), used for dashboard tags.
    tag = next((m.kind for m in motifs.motifs if m.tactical), None)

    payload = {
        "san": san,
        "fenBefore": board.fen(),
        "quality": verdict.quality.value,
        "glyph": verdict.quality.glyph,
        "cpLoss": verdict.cp_loss,
        "evalAfter": round(played.score_cp / 100.0, 1),
        "evalCp": played.score_cp,
        "tag": tag,
        "isBest": verdict.is_best_move,
        "playedFrom": _sq(move.from_square),
        "playedTo": _sq(move.to_square),
        "bestSan": pre.best.san,
        "bestFrom": _sq(pre.best.move.from_square),
        "bestTo": _sq(pre.best.move.to_square),
        "bestLine": pre.best.pv_san[:5],
        "refuteFrom": refute_from,
        "refuteTo": refute_to,
        "refuteLine": played.pv_san[:5],
        "explanation": text,
        "explanationSource": source,
    }
    payload.update(_game_state(after))
    return payload


# --- API handlers ----------------------------------------------------------
def api_health(_body: dict) -> dict:
    ok = True
    try:
        find_stockfish()
    except Exception:
        ok = False
    return {"engine": ok, "ollama": ollama_available(), "model": OLLAMA_MODEL}


def api_legal(body: dict) -> dict:
    board = chess.Board(body["fen"])
    st = _game_state(board)
    st["ucis"] = [mv.uci() for mv in board.legal_moves]
    return st


TAG_PHRASES = {
    "hangs_piece": "left a piece hanging", "allows_mate": "allowed a forced mate",
    "refuted": "lost material to a tactic", "fork": "walked into a fork",
    "gives_check": "played a loose check", "captures": "made a bad capture",
}


def api_move(body: dict) -> dict:
    board = chess.Board(body["fen"])
    move = _parse_move(board, body)
    # In Play, every /api/move is the human's own move, so personalise it.
    c = coach_payload(board, move, bool(body.get("useLlm", True)))
    if c["quality"] in ("inaccuracy", "mistake", "blunder") and c.get("tag"):
        st = store.tag_stats(c["tag"])
        if st["games"] >= 1:
            phrase = TAG_PHRASES.get(c["tag"], "made this kind of mistake")
            c["recurring"] = {
                "games": st["games"], "total": st["total"],
                "text": f"You've {phrase} in {st['games']} of your last "
                        f"{st['total']} game{'s' if st['total'] != 1 else ''} — a recurring pattern.",
            }
    return c


def api_engine(body: dict) -> dict:
    board = chess.Board(body["fen"])
    level = int(body.get("level", 3))
    skill = max(0, min(20, level * 2))
    with _engine_lock:
        move = get_analyzer().best_reply(board, skill_level=skill, movetime=_movetime)
    san = board.san(move)
    board.push(move)
    st = _game_state(board)
    st.update({"san": san, "from": _sq(move.from_square), "to": _sq(move.to_square)})
    return st


def api_hint(body: dict) -> dict:
    """Explain the engine's best move in the current position."""
    board = chess.Board(body["fen"])
    with _engine_lock:
        pre = get_analyzer().analyse_position(board, multipv=1)
    best = pre.best
    return coach_payload(board, best.move, bool(body.get("useLlm", True)))


def api_plan(body: dict) -> dict:
    """Strategic brief for the current position: the long-term plan, not a move."""
    board = chess.Board(body["fen"])
    if board.is_game_over():
        raise ValueError("The game is over — no plan to make.")
    with _engine_lock:
        pre = get_analyzer().analyse_position(board, multipv=1)
    brief = strategic_brief(board)
    brief.line_theme = plan_from_line(board, pre.best.pv)
    text, source = strategic_explanation(brief, use_llm=bool(body.get("useLlm", True)))
    return {
        "phase": brief.phase, "character": brief.character,
        "yourPlan": brief.your_plan, "opponentPlan": brief.opponent_plan,
        "pawnBreaks": brief.pawn_breaks, "improve": brief.improve,
        "lineTheme": brief.line_theme, "text": text, "source": source,
        "bestFrom": _sq(pre.best.move.from_square), "bestTo": _sq(pre.best.move.to_square),
        "bestSan": pre.best.san,
    }


def api_save(body: dict) -> dict:
    """Save a played game. The client sends the move list it already has;
    accuracy is computed here from the per-move evals."""
    moves_in = body.get("moves", [])
    white_accs, black_accs, records = [], [], []
    for m in moves_in:
        acc = None
        if m.get("cpLoss") is not None and m.get("evalCp") is not None:
            acc = accuracy_from_cp(int(m["evalCp"]) + int(m["cpLoss"]), int(m["evalCp"]))
            (white_accs if m["side"] == "white" else black_accs).append(acc)
        records.append({
            "ply": m["ply"], "side": m["side"], "san": m["san"], "uci": m.get("uci"),
            "quality": m.get("quality"), "cp_loss": m.get("cpLoss"),
            "eval_cp": m.get("evalCp"), "tag": m.get("tag"),
        })
    gid = store.save_game({
        "source": "play",
        "white": body.get("white", "You" if body.get("humanColor") == "white" else "Stockfish"),
        "black": body.get("black", "You" if body.get("humanColor") == "black" else "Stockfish"),
        "result": body.get("result", "*"),
        "human_color": body.get("humanColor"),
        "level": body.get("level"),
        "white_acc": game_accuracy(white_accs),
        "black_acc": game_accuracy(black_accs),
        "pgn": body.get("pgn"),
    }, records)
    return {"id": gid, "whiteAcc": game_accuracy(white_accs), "blackAcc": game_accuracy(black_accs)}


def api_games(body: dict) -> dict:
    return {"games": store.list_games(int(body.get("limit", 50)))}


def api_game(body: dict) -> dict:
    g = store.get_game(int(body["id"]))
    if g is None:
        raise ValueError("Game not found.")
    return g


def api_dashboard(_body: dict) -> dict:
    return store.dashboard()


def api_review(body: dict) -> dict:
    """Re-analyse a stored game (by id) from its saved PGN, for rich replay."""
    g = store.get_game(int(body["id"]))
    if g is None:
        raise ValueError("Game not found.")
    if not g.get("pgn"):
        raise ValueError("This game has no stored PGN to review.")
    h, review, _records, wa, ba, summary = _analyze_pgn(g["pgn"])
    return {"id": g["id"], "white": g["white"], "black": g["black"],
            "result": g["result"], "whiteAcc": wa, "blackAcc": ba,
            "review": review, "strategicSummary": summary}


def api_delete(body: dict) -> dict:
    store.delete_game(int(body["id"]))
    return {"ok": True}


def _analyze_pgn(pgn_text: str, movetime: float = 0.18):
    """Analyse every ply of a game. Returns (headers, review, records,
    white_acc, black_acc) without storing anything."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Could not parse any game from that PGN.")
    board = game.board()
    white_accs, black_accs, records, review = [], [], [], []
    ply = 0
    for move in game.mainline_moves():
        ply += 1
        side = "white" if board.turn == chess.WHITE else "black"
        num = board.fullmove_number
        c = coach_payload_fast(board, move, movetime)
        eval_cp = c["evalCp"]
        acc = accuracy_from_cp(eval_cp + c["cpLoss"], eval_cp)
        (white_accs if side == "white" else black_accs).append(acc)
        records.append({"ply": ply, "side": side, "san": c["san"], "uci": move.uci(),
                        "quality": c["quality"], "cp_loss": c["cpLoss"],
                        "eval_cp": eval_cp, "tag": c["tag"]})
        c.update({"ply": ply, "side": side, "moveNumber": num, "accuracy": round(acc, 1),
                  "phase": game_phase(board)})
        review.append(c)
        board.push(move)
    return (game.headers, review, records, game_accuracy(white_accs),
            game_accuracy(black_accs), _strategic_summary(review))


def _strategic_summary(review: list[dict]) -> dict:
    """Whole-game strategic story from the per-move review: accuracy by phase,
    the turning point, and a one-line narrative."""
    phases = {"opening": {"white": [], "black": []},
              "middlegame": {"white": [], "black": []},
              "endgame": {"white": [], "black": []}}
    for c in review:
        phases[c["phase"]][c["side"]].append(c["accuracy"])
    phase_acc = {}
    for ph, sides in phases.items():
        entry = {}
        for s in ("white", "black"):
            if sides[s]:
                entry[s] = round(sum(sides[s]) / len(sides[s]), 1)
        if entry:
            phase_acc[ph] = entry

    turning = None
    worst = -1
    for c in review:
        if c["quality"] in ("mistake", "blunder") and c["cpLoss"] > worst:
            worst = c["cpLoss"]
            turning = {"moveNumber": c["moveNumber"], "side": c["side"], "san": c["san"],
                       "quality": c["quality"], "phase": c["phase"]}

    bits = []
    for ph in ("opening", "middlegame", "endgame"):
        if ph in phase_acc:
            vals = phase_acc[ph]
            bits.append(f"{ph} " + "/".join(f"{vals[s]:.0f}%" for s in ("white", "black") if s in vals))
    text = "Accuracy by phase — " + "; ".join(bits) + "." if bits else ""
    if turning:
        text += (f" The turning point was {turning['side']}'s {turning['quality']} "
                 f"{turning['san']} ({turning['phase']}).")
    return {"phaseAccuracy": phase_acc, "turningPoint": turning, "text": text.strip()}


def _review_pgn(pgn_text: str, source: str, movetime: float = 0.18,
                human_name: str | None = None) -> dict:
    h, review, records, wa, ba, summary = _analyze_pgn(pgn_text, movetime)
    # If we know which player is the learner, tag their side for the dashboard.
    human_color = None
    if human_name:
        low = human_name.lower()
        if h.get("White", "").lower() == low:
            human_color = "white"
        elif h.get("Black", "").lower() == low:
            human_color = "black"
    gid = store.save_game({
        "source": source, "white": h.get("White", "?"), "black": h.get("Black", "?"),
        "result": h.get("Result", "*"), "human_color": human_color, "level": None,
        "white_acc": wa, "black_acc": ba, "pgn": pgn_text,
    }, records)
    return {"id": gid, "white": h.get("White", "?"), "black": h.get("Black", "?"),
            "result": h.get("Result", "*"), "whiteAcc": wa, "blackAcc": ba,
            "review": review, "strategicSummary": summary}


def coach_payload_fast(board: chess.Board, move: chess.Move, movetime: float) -> dict:
    """Like coach_payload but at a lower movetime for bulk game review."""
    global _movetime
    prev = _movetime
    try:
        _movetime = movetime
        with _engine_lock:
            get_analyzer().movetime_s = movetime
        return coach_payload(board, move, use_llm=False)
    finally:
        _movetime = prev
        with _engine_lock:
            get_analyzer().movetime_s = prev


def api_import_pgn(body: dict) -> dict:
    pgn = (body.get("pgn") or "").strip()
    if not pgn:
        raise ValueError("Paste a PGN first.")
    return _review_pgn(pgn, "pgn")


def api_import_lichess(body: dict) -> dict:
    user = (body.get("username") or "").strip()
    if not user:
        raise ValueError("Enter a Lichess username.")
    n = max(1, min(5, int(body.get("max", 1))))
    url = f"https://lichess.org/api/games/user/{user}?max={n}&pgnInJson=false"
    req = urllib.request.Request(url, headers={"Accept": "application/x-chess-pgn",
                                               "User-Agent": "chesscoach/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            pgn_text = resp.read().decode("utf-8")
    except Exception as e:
        raise ValueError(f"Could not fetch from Lichess: {e}")
    if not pgn_text.strip():
        raise ValueError(f"No public games found for '{user}'.")
    # Import just the most recent game for now (one review per request).
    first = chess.pgn.read_game(io.StringIO(pgn_text))
    if first is None:
        raise ValueError("Lichess returned no parseable game.")
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    return _review_pgn(first.accept(exporter), "lichess", human_name=user)


def _parse_move(board: chess.Board, body: dict) -> chess.Move:
    if body.get("uci"):
        move = chess.Move.from_uci(body["uci"])
    elif body.get("san"):
        move = board.parse_san(body["san"])
    else:
        raise ValueError("No move provided.")
    if move not in board.legal_moves:
        raise ValueError("Illegal move.")
    return move


ROUTES = {
    "/api/health": api_health,
    "/api/legal": api_legal,
    "/api/move": api_move,
    "/api/engine": api_engine,
    "/api/hint": api_hint,
    "/api/plan": api_plan,
    "/api/save": api_save,
    "/api/games": api_games,
    "/api/game": api_game,
    "/api/dashboard": api_dashboard,
    "/api/review": api_review,
    "/api/delete": api_delete,
    "/api/import/pgn": api_import_pgn,
    "/api/import/lichess": api_import_lichess,
}

_CONTENT_TYPES = {".html": "text/html", ".js": "application/javascript",
                  ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "chesscoach/0.1"

    def log_message(self, *args):  # quieter console
        pass

    def _send_json(self, obj: dict, code: int = 200) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("/")
        full = os.path.join(STATIC_DIR, safe)
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self.send_error(404, "Not found")
            return
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        handler = ROUTES.get(self.path.split("?", 1)[0])
        if handler is None:
            self.send_error(404, "Unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send_json(handler(body))
        except (ValueError, KeyError) as e:
            self._send_json({"error": str(e)}, code=400)
        except Exception as e:  # engine or unexpected
            self._send_json({"error": f"{type(e).__name__}: {e}"}, code=500)


def main(argv=None) -> int:
    global _movetime
    p = argparse.ArgumentParser(description="chesscoach local web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--movetime", type=float, default=0.4,
                   help="engine seconds per analysis (default 0.4)")
    args = p.parse_args(argv)
    _movetime = args.movetime

    try:
        find_stockfish()
    except FileNotFoundError as e:
        print(str(e))
        return 3

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}"
    print(f"chesscoach web UI running at {url}")
    print(f"  engine : {find_stockfish()}")
    print(f"  ollama : {'available' if ollama_available() else 'not running (template explainer)'}")
    print("Press Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        if _analyzer is not None:
            _analyzer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
