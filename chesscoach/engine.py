"""Engine layer: Stockfish is the single source of truth.

This module is deliberately the ONLY place that produces evaluations and
"best move" claims. The explanation layer is never allowed to invent these
numbers; it only narrates what this layer reports. That separation is the
whole design: the engine thinks, the language model talks.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

import chess
import chess.engine

# Centipawn value used to stand in for a forced mate when we need a scalar.
MATE_SCORE = 100_000


def find_stockfish() -> str:
    """Locate a Stockfish binary.

    Resolution order:
      1. $CHESSCOACH_STOCKFISH (explicit path)
      2. `stockfish` on PATH
    Raises a clear, actionable error if neither is found, because on the
    target machine (a laptop) the most common setup problem is simply not
    having installed the engine yet.
    """
    env = os.environ.get("CHESSCOACH_STOCKFISH")
    if env:
        if os.path.isfile(env) and os.access(env, os.X_OK):
            return env
        raise FileNotFoundError(
            f"CHESSCOACH_STOCKFISH is set to '{env}' but that is not an "
            f"executable file."
        )
    found = shutil.which("stockfish")
    if found:
        return found
    raise FileNotFoundError(
        "Stockfish not found. Install it (e.g. `sudo apt install stockfish`, "
        "`brew install stockfish`, or download a static build from "
        "https://stockfishchess.org/download/) and either put it on your PATH "
        "or set the CHESSCOACH_STOCKFISH environment variable to its path."
    )


@dataclass
class MoveEval:
    """One candidate move and the engine's evaluation of it.

    `score_cp` is from the point of view of the side that is about to move,
    so higher is always better for that side. A mate is mapped onto a large
    centipawn magnitude so downstream math stays simple.
    """

    move: chess.Move
    san: str
    score_cp: int
    mate_in: int | None  # signed: +N = mover mates in N, -N = mover gets mated
    pv: list[chess.Move] = field(default_factory=list)
    pv_san: list[str] = field(default_factory=list)


@dataclass
class PositionReport:
    """Everything the engine knows about one position, before any move."""

    fen: str
    turn: chess.Color
    best: MoveEval
    alternatives: list[MoveEval]  # includes `best` as element 0


class Analyzer:
    """Thin, laptop-friendly wrapper around a persistent Stockfish process.

    Use as a context manager so the engine subprocess is always closed:

        with Analyzer() as az:
            report = az.analyse_position(board, multipv=3)
    """

    def __init__(
        self,
        stockfish_path: str | None = None,
        *,
        threads: int = 2,
        hash_mb: int = 128,
        movetime_s: float = 0.5,
        depth: int | None = None,
    ):
        self.path = stockfish_path or find_stockfish()
        self.movetime_s = movetime_s
        self.depth = depth
        self._engine = chess.engine.SimpleEngine.popen_uci(self.path)
        # Conservative defaults: a Ryzen 5000 laptop also has to run the LLM.
        try:
            self._engine.configure({"Threads": threads, "Hash": hash_mb})
        except chess.engine.EngineError:
            # Some builds reject options silently-differently; non-fatal.
            pass

    # -- context manager plumbing -------------------------------------------
    def __enter__(self) -> "Analyzer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._engine.quit()
        except Exception:
            pass

    # -- internals ----------------------------------------------------------
    def _limit(self) -> chess.engine.Limit:
        if self.depth is not None:
            return chess.engine.Limit(depth=self.depth)
        return chess.engine.Limit(time=self.movetime_s)

    @staticmethod
    def _to_cp(score: chess.engine.PovScore, pov: chess.Color) -> tuple[int, int | None]:
        """Return (centipawns, signed_mate_in) from `pov`'s perspective."""
        rel = score.pov(pov)
        mate = rel.mate()
        cp = rel.score(mate_score=MATE_SCORE)
        return cp, mate

    # -- public API ---------------------------------------------------------
    def analyse_position(self, board: chess.Board, *, multipv: int = 3) -> PositionReport:
        """Analyse a position and return the best move plus alternatives."""
        pov = board.turn
        infos = self._engine.analyse(board, self._limit(), multipv=multipv)
        if isinstance(infos, dict):  # multipv=1 returns a single dict
            infos = [infos]

        evals: list[MoveEval] = []
        for info in infos:
            pv = info.get("pv", [])
            if not pv:
                continue
            cp, mate = self._to_cp(info["score"], pov)
            evals.append(
                MoveEval(
                    move=pv[0],
                    san=board.san(pv[0]),
                    score_cp=cp,
                    mate_in=mate,
                    pv=list(pv),
                    pv_san=_line_to_san(board, pv),
                )
            )
        if not evals:
            raise RuntimeError("Engine returned no principal variation.")
        return PositionReport(
            fen=board.fen(),
            turn=pov,
            best=evals[0],
            alternatives=evals,
        )

    def evaluate_after(self, board: chess.Board, move: chess.Move) -> MoveEval:
        """Evaluate the position that results from `move`.

        The returned score is expressed from the point of view of the player
        who just made `move` (the same POV as the pre-move analysis), so it
        can be compared directly against the best-move score to compute loss.
        The PV is the opponent's best reply line -- i.e. the *refutation*,
        which is the concrete, teachable "why this is bad".
        """
        mover = board.turn
        san = board.san(move)
        board.push(move)
        try:
            info = self._engine.analyse(board, self._limit(), multipv=1)
            if isinstance(info, list):
                info = info[0]
            cp, mate = self._to_cp(info["score"], mover)
            pv = info.get("pv", [])
            return MoveEval(
                move=move,
                san=san,
                score_cp=cp,
                mate_in=mate,
                pv=list(pv),
                pv_san=_line_to_san(board, pv),
            )
        finally:
            board.pop()


def _line_to_san(board: chess.Board, moves: list[chess.Move], max_plies: int = 6) -> list[str]:
    """Convert a list of moves to SAN from `board`, without mutating it."""
    out: list[str] = []
    b = board.copy(stack=False)
    for mv in moves[:max_plies]:
        if mv not in b.legal_moves:
            break
        out.append(b.san(mv))
        b.push(mv)
    return out
