#!/usr/bin/env python3
"""chesscoach CLI -- prove the engine->motif->explanation pipeline.

Examples
--------
Analyse one move from a position:
    python coach_cli.py move --fen "rnbqkbnr/pppp1ppp/8/4p3/6P1/8/PPPPPP1P/RNBQKBNR b KQkq - 0 1" --san Qh4

Analyse an entire game (PGN file or '-' for stdin):
    python coach_cli.py pgn game.pgn

Play against Stockfish and get coached on every one of your moves:
    python coach_cli.py play --level 3

Environment
-----------
    CHESSCOACH_STOCKFISH   path to the Stockfish binary (else PATH is searched)
    CHESSCOACH_MODEL       Ollama model name (default qwen2.5:7b-instruct)
    OLLAMA_URL             default http://localhost:11434
"""

from __future__ import annotations

import argparse
import sys

import chess
import chess.pgn

from chesscoach.coach import Coaching, coach_move
from chesscoach.engine import Analyzer, find_stockfish
from chesscoach.explain import ollama_available

# ANSI colours by verdict (degrade gracefully if piped).
_COLOR = {
    "brilliant": "\033[95m",
    "best": "\033[92m",
    "excellent": "\033[92m",
    "good": "\033[96m",
    "inaccuracy": "\033[93m",
    "mistake": "\033[33m",
    "blunder": "\033[91m",
}
_RESET = "\033[0m"


def _render(c: Coaching, use_color: bool) -> str:
    q = c.verdict.quality.value
    tag = q.upper()
    if use_color:
        tag = f"{_COLOR.get(q, '')}{tag}{_RESET}"
    src = "" if c.explanation_source == "ollama" else "  [template]"
    return f"  {tag}{src}\n  {c.explanation}"


def _llm_flags(args) -> bool:
    if args.no_llm:
        return False
    if not ollama_available():
        print(
            "  (Ollama not reachable -> using the grounded template explainer. "
            "Start Ollama and `ollama pull qwen2.5:7b-instruct` for richer prose.)",
            file=sys.stderr,
        )
        return False
    return True


def cmd_move(args) -> int:
    board = chess.Board(args.fen)
    try:
        move = board.parse_san(args.san) if args.san else board.parse_uci(args.uci)
    except ValueError as e:
        print(f"Could not parse move: {e}", file=sys.stderr)
        return 2
    use_llm = _llm_flags(args)
    with Analyzer(movetime_s=args.movetime, depth=args.depth) as az:
        c = coach_move(az, board, move, use_llm=use_llm, model=args.model)
    print(f"\nPosition: {args.fen}")
    print(f"Move:     {c.move_san}")
    print(_render(c, sys.stdout.isatty()))
    return 0


def cmd_pgn(args) -> int:
    stream = sys.stdin if args.path == "-" else open(args.path)
    game = chess.pgn.read_game(stream)
    if game is None:
        print("No game found in input.", file=sys.stderr)
        return 2
    use_llm = _llm_flags(args)
    board = game.board()
    color = sys.stdout.isatty()
    moves = list(game.mainline_moves())
    with Analyzer(movetime_s=args.movetime, depth=args.depth) as az:
        for i, move in enumerate(moves, 1):
            mover = "White" if board.turn == chess.WHITE else "Black"
            num = (i + 1) // 2
            # Only coach the side requested (default: both).
            do = (
                args.side == "both"
                or (args.side == "white" and board.turn == chess.WHITE)
                or (args.side == "black" and board.turn == chess.BLACK)
            )
            if do:
                c = coach_move(az, board, move, use_llm=use_llm, model=args.model)
                # Only print noteworthy moves unless --all.
                noteworthy = c.verdict.quality.value in (
                    "inaccuracy", "mistake", "blunder", "brilliant",
                )
                if args.all or noteworthy:
                    print(f"\n{num}{'.' if mover=='White' else '...'} {c.move_san}  ({mover})")
                    print(_render(c, color))
            board.push(move)
    return 0


def cmd_play(args) -> int:
    use_llm = _llm_flags(args)
    board = chess.Board()
    human = chess.WHITE if args.color == "white" else chess.BLACK
    # Map a 1-8 "level" onto Stockfish skill + a short think time.
    skill = max(0, min(20, args.level * 2))
    with Analyzer(movetime_s=args.movetime, depth=args.depth) as az:
        color = sys.stdout.isatty()
        print("Enter moves in SAN (e.g. Nf3, e4, O-O). Ctrl-D or 'quit' to stop.\n")
        while not board.is_game_over():
            print(board.unicode(borders=False, invert_color=True))
            if board.turn == human:
                try:
                    raw = input(f"\nYour move ({'White' if human==chess.WHITE else 'Black'}): ").strip()
                except EOFError:
                    break
                if raw in ("quit", "exit"):
                    break
                try:
                    move = board.parse_san(raw)
                except ValueError:
                    print("  Illegal or unparseable move; try again.")
                    continue
                c = coach_move(az, board, move, use_llm=use_llm, model=args.model)
                print(_render(c, color))
                board.push(move)
            else:
                # Weaken ONLY the opponent's move selection; analysis used for
                # coaching stays at full strength (configured back to 20 after).
                try:
                    az._engine.configure({"Skill Level": skill})
                    result = az._engine.play(board, az._limit())
                finally:
                    try:
                        az._engine.configure({"Skill Level": 20})
                    except Exception:
                        pass
                print(f"\nEngine plays: {board.san(result.move)}")
                board.push(result.move)
        print(f"\nGame over: {board.result()} ({board.outcome().termination.name if board.outcome() else 'stopped'})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="coach_cli", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--movetime", type=float, default=0.5,
                   help="engine seconds per analysis (default 0.5)")
    p.add_argument("--depth", type=int, default=None,
                   help="fixed engine depth (overrides --movetime)")
    p.add_argument("--model", default=None, help="Ollama model name override")
    p.add_argument("--no-llm", action="store_true",
                   help="skip Ollama; use the deterministic template explainer")
    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("move", help="coach a single move from a FEN")
    pm.add_argument("--fen", required=True)
    g = pm.add_mutually_exclusive_group(required=True)
    g.add_argument("--san")
    g.add_argument("--uci")
    pm.set_defaults(func=cmd_move)

    pp = sub.add_parser("pgn", help="coach every noteworthy move in a PGN")
    pp.add_argument("path", help="PGN file path, or '-' for stdin")
    pp.add_argument("--side", choices=["white", "black", "both"], default="both")
    pp.add_argument("--all", action="store_true", help="show every move, not just noteworthy ones")
    pp.set_defaults(func=cmd_pgn)

    pl = sub.add_parser("play", help="play vs Stockfish and get coached")
    pl.add_argument("--color", choices=["white", "black"], default="white")
    pl.add_argument("--level", type=int, default=3, help="1 (easy) .. 8 (hard)")
    pl.set_defaults(func=cmd_play)

    args = p.parse_args(argv)
    try:
        find_stockfish()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 3
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
