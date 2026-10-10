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
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chess

from chesscoach.classify import Quality, classify
from chesscoach.coach import _is_sacrifice
from chesscoach.engine import Analyzer, find_stockfish
from chesscoach.explain import CoachingFacts, explain, ollama_available, OLLAMA_MODEL
from chesscoach.motifs import build_motifs

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

    payload = {
        "san": san,
        "quality": verdict.quality.value,
        "glyph": verdict.quality.glyph,
        "cpLoss": verdict.cp_loss,
        "evalAfter": round(played.score_cp / 100.0, 1),
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


def api_move(body: dict) -> dict:
    board = chess.Board(body["fen"])
    move = _parse_move(board, body)
    return coach_payload(board, move, bool(body.get("useLlm", True)))


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
