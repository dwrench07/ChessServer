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

from chesscoach import analogies, store
from chesscoach.accuracy import accuracy_from_cp, game_accuracy
from chesscoach.classify import Quality, classify
from chesscoach.coach import _is_sacrifice
from chesscoach.engine import Analyzer, find_stockfish
from chesscoach.explain import (CoachingFacts, explain, ollama_available,
                                OLLAMA_MODEL, strategic_explanation)
from chesscoach.motifs import build_motifs
from chesscoach.plot import find_plot, live_plot
from chesscoach import progress
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
        "conceptKey": analogies.concept_for_tag(tag),
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
    # Real-time glow: your loose pieces vs the opponent pieces you can win.
    from chesscoach.motifs import static_exchange_eval
    mover = board.turn
    hanging, targets = [], []
    for sq, piece in board.piece_map().items():
        if piece.piece_type == chess.KING:
            continue
        if static_exchange_eval(board, sq) > 0:
            (hanging if piece.color == mover else targets).append(_sq(sq))
    st["hanging"] = hanging
    st["targets"] = targets
    return st


_PIECE_NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
                chess.ROOK: "rook", chess.QUEEN: "queen"}

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


def api_threat(body: dict) -> dict:
    """Live read of the position: the opponent's biggest threat (null-move
    method) plus a 'pulse' — how sharp the position is, whether it's a critical
    moment, and whether the side to move has a tactic (without revealing it)."""
    board = chess.Board(body["fen"])
    if board.is_game_over():
        return {"threat": None, "pulse": None}

    with _engine_lock:
        now = get_analyzer().analyse_position(board, multipv=3)
    alts = now.alternatives
    best = alts[0]
    gap = (best.score_cp - alts[1].score_cp) if len(alts) >= 2 else 999

    # Sharpness / criticality from the spread between the best moves.
    if gap >= 150 or best.mate_in is not None:
        sharp = "sharp"
    elif gap >= 60:
        sharp = "tense"
    else:
        sharp = "quiet"
    critical = gap >= 150 and best.mate_in is None
    # Tactic for the side to move: the best move is forcing AND much better.
    forcing = board.is_capture(best.move)
    if not forcing:
        b2 = board.copy(stack=False); b2.push(best.move); forcing = b2.is_check()
    tactic = (best.mate_in is not None and best.mate_in > 0) or (gap >= 120 and best.score_cp >= 100 and forcing)
    pulse = {
        "sharpness": sharp, "critical": critical, "tactic": tactic,
        "criticalText": "Critical moment — essentially one move holds." if critical else None,
        "tacticText": "\U0001F440 There's something here — look for a tactic." if tactic else None,
        # Position eval from the side-to-move POV, for the live-plot timeline.
        "evalCp": best.score_cp,
    }

    threat = None
    if not board.is_check():
        with _engine_lock:
            az = get_analyzer()
            e_now = now.best.score_cp
            board.push(chess.Move.null())
            after = az.analyse_position(board, multipv=1)
            threat_move = after.best.move
            threat_san = board.san(threat_move)
            mate = after.best.mate_in
            e_pass = -after.best.score_cp
            tgt = board.piece_at(threat_move.to_square)
            cap_name = _PIECE_NAMES.get(tgt.piece_type) if tgt else None
            tfrom, tto = _sq(threat_move.from_square), _sq(threat_move.to_square)
            board.pop()
        threat_size = e_now - e_pass
        if (mate is not None and mate > 0) or threat_size >= 150:
            if mate is not None and mate > 0:
                text = f"They're threatening mate with {threat_san}."
            elif cap_name and cap_name != "pawn":
                text = f"They're threatening to win your {cap_name} with {threat_san}."
            elif threat_size >= 900:
                text = f"They're threatening {threat_san} — a decisive blow."
            else:
                text = f"They're threatening {threat_san}, worth about {threat_size / 100:.1f} pawns."
            threat = {"from": tfrom, "to": tto, "san": threat_san, "text": text}
    return {"threat": threat, "pulse": pulse}


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
        "conceptKey": analogies.concept_for_plan(brief.your_plan),
        "bestFrom": _sq(pre.best.move.from_square), "bestTo": _sq(pre.best.move.to_square),
        "bestSan": pre.best.san,
    }


def api_concepts(_body: dict) -> dict:
    return {"concepts": analogies.concept_list()}


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
    wa, ba = game_accuracy(white_accs), game_accuracy(black_accs)
    hc = body.get("humanColor")
    result = body.get("result", "*")
    gid = store.save_game({
        "source": "play",
        "white": body.get("white", "You" if hc == "white" else "Stockfish"),
        "black": body.get("black", "You" if hc == "black" else "Stockfish"),
        "result": result,
        "human_color": hc,
        "level": body.get("level"),
        "white_acc": wa,
        "black_acc": ba,
        "pgn": body.get("pgn"),
    }, records)

    out = {"id": gid, "whiteAcc": wa, "blackAcc": ba}

    # Progression: only finished played games with a known human side earn XP.
    human_acc = wa if hc == "white" else (ba if hc == "black" else None)
    if hc and result in ("1-0", "0-1", "1/2-1/2"):
        won = (result == "1-0") == (hc == "white")
        drew = result == "1/2-1/2"
        streak = int(body.get("streak", 0) or 0)
        earned = progress.xp_for(won, drew, human_acc)
        prof = store.add_result(earned, won, human_acc, streak)
        prog = progress.level_progress(prof["total_xp"])
        out["progress"] = {
            "earned": earned,
            "grade": progress.grade(human_acc),
            "accuracy": human_acc,
            "result": "win" if won else ("draw" if drew else "loss"),
            **prog,
        }
    return out


def api_profile(_body: dict) -> dict:
    """The learner's running progression: XP, level, kingdom, lifetime stats."""
    prof = store.get_profile()
    prog = progress.level_progress(prof["total_xp"])
    return {
        "level": prog["level"],
        "xp": prog["xp"],
        "levelFloor": prog["levelFloor"],
        "nextAt": prog["nextAt"],
        "pct": prog["pct"],
        "kingdom": progress.kingdom_for_level(prog["level"]),
        "stats": {
            "games": prof["games"],
            "wins": prof["wins"],
            "bestAcc": round(prof["best_acc"], 1),
            "bestStreak": prof["best_streak"],
        },
    }


def api_puzzles(body: dict) -> dict:
    """Mine the learner's own mistakes into a Puzzle Rush queue (no engine)."""
    from chesscoach import puzzles as _puz
    games = store.all_games_with_moves()
    order = body.get("order", "severity")
    limit = int(body.get("limit", 40))
    return {"puzzles": _puz.extract_puzzles(games, limit=limit, order=order)}


def api_puzzle_check(body: dict) -> dict:
    """Score a candidate move against the engine's best for a puzzle position.

    The engine is the source of truth: a solve is the engine's top move, or any
    move within a small centipawn tolerance of it (an equally good answer).
    """
    board = chess.Board(body["fen"])
    try:
        mv = chess.Move.from_uci(body["uci"])
    except ValueError:
        raise ValueError("Malformed move.")
    if mv not in board.legal_moves:
        raise ValueError("Illegal move for this position.")

    your_san = board.san(mv)
    with _engine_lock:
        az = get_analyzer()
        pre = az.analyse_position(board, multipv=3)
        cand = az.evaluate_after(board, mv)

    best = pre.best
    cp_loss = max(0, best.score_cp - cand.score_cp)
    solved = (mv == best.move) or (cp_loss <= 30)
    tail = (" — " + " ".join(best.pv_san[:4])) if best.pv_san else ""

    if solved and mv == best.move:
        message = f"Exactly — {your_san} is the move."
    elif solved:
        message = f"Good — {your_san} is just as strong as the engine's {best.san}."
    elif best.mate_in and best.mate_in > 0:
        # The win was a forced mate the player missed.
        message = f"Missed the finish — {best.san} forces mate{tail}."
    elif cand.mate_in and cand.mate_in < 0:
        # The candidate walks into a forced mate.
        message = f"That walks into mate. The move was {best.san}{tail}."
    elif cp_loss >= 1000:
        # Decisive material swing — a pawn figure here is meaningless noise.
        message = f"That loses decisively. The move was {best.san}{tail}."
    else:
        message = f"Not quite. {your_san} gives back {cp_loss/100:.1f}; the move was {best.san}{tail}."

    return {
        "solved": solved,
        "yourSan": your_san,
        "yourCp": cand.score_cp,
        "cpLoss": cp_loss,
        "bestUci": best.move.uci(),
        "bestSan": best.san,
        "bestFrom": _sq(best.move.from_square),
        "bestTo": _sq(best.move.to_square),
        "bestLine": best.pv_san[:5],
        "bestCp": best.score_cp,
        "message": message,
    }


def api_campaign(_body: dict) -> dict:
    """The persona ladder annotated with the learner's unlock / beaten state."""
    from chesscoach import personas
    prof = store.get_profile()
    player_level = progress.level_progress(prof["total_xp"])["level"]
    return personas.campaign_state(player_level, store.wins_by_level())


def api_plotwatch(body: dict) -> dict:
    """Live House-of-Cards callback: did the latest move land a blow a quiet
    earlier move set up? Pure eval math on the game-so-far (no engine)."""
    review = body.get("review", [])
    return live_plot(review)


def api_games(body: dict) -> dict:
    return {"games": store.list_games(int(body.get("limit", 50)))}


def api_game(body: dict) -> dict:
    g = store.get_game(int(body["id"]))
    if g is None:
        raise ValueError("Game not found.")
    return g


def api_dashboard(_body: dict) -> dict:
    from chesscoach import analytics
    data = store.dashboard()
    try:
        data.update(analytics.compute(store.all_games_with_moves()))
    except Exception:
        pass  # analytics are best-effort; never break the dashboard
    return data


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
            "review": review, "strategicSummary": summary, "plot": find_plot(review)}


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
            "review": review, "strategicSummary": summary, "plot": find_plot(review)}


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
    "/api/threat": api_threat,
    "/api/plan": api_plan,
    "/api/concepts": api_concepts,
    "/api/save": api_save,
    "/api/profile": api_profile,
    "/api/puzzles": api_puzzles,
    "/api/puzzle/check": api_puzzle_check,
    "/api/campaign": api_campaign,
    "/api/plotwatch": api_plotwatch,
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
