"""Explanation layer -- the "voice".

Two modes, both grounded in facts the engine and motif layers produced:

  1. TEMPLATE  -- deterministic prose assembled from the structured facts.
                  Always available, needs no model, and can never hallucinate
                  because it only restates given facts. This is the fallback
                  and the correctness baseline.

  2. OLLAMA    -- a small local LLM (default qwen2.5:7b-instruct) rewrites the
                  SAME facts into friendlier, more intuitive prose. It is given
                  the numbers and told explicitly NOT to invent moves or
                  evaluations. On any error it silently falls back to TEMPLATE.

The model never decides whether a move is good; it only phrases a verdict that
was already computed. That is what keeps a local 7B model trustworthy here.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .classify import Quality, QualityVerdict
from .engine import MoveEval
from .motifs import MotifReport

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("CHESSCOACH_MODEL", "qwen2.5:7b-instruct")


@dataclass
class CoachingFacts:
    """The grounded bundle handed to whichever explainer is active."""

    mover: str                 # "White" / "Black"
    move_san: str
    quality: QualityVerdict
    best_move_san: str
    best_line_san: list[str]
    refutation_san: list[str]
    motif_report: MotifReport
    eval_before_cp: int        # best-move eval, mover POV
    eval_after_cp: int         # actual-move eval, mover POV


def _pawns(cp: int) -> str:
    return f"{cp / 100:+.1f}"


def _quality_phrase(v: QualityVerdict) -> str:
    return {
        Quality.BRILLIANT: "a brilliant move",
        Quality.BEST: "the best move",
        Quality.EXCELLENT: "an excellent move",
        Quality.GOOD: "a good move",
        Quality.INACCURACY: "an inaccuracy",
        Quality.MISTAKE: "a mistake",
        Quality.BLUNDER: "a blunder",
    }[v.quality]


def template_explanation(f: CoachingFacts) -> str:
    """Deterministic, hallucination-proof explanation from the facts."""
    v = f.quality
    parts: list[str] = []
    head = f"{f.move_san} is {_quality_phrase(v)}"
    if v.quality.glyph:
        head += f" ({v.quality.glyph})"
    parts.append(head + ".")

    # Why, in concrete terms first.
    tactical = f.motif_report.tactical
    positional = f.motif_report.positional

    positive = v.quality in (Quality.BRILLIANT, Quality.BEST, Quality.EXCELLENT, Quality.GOOD)
    if positive:
        reasons = [m.text for m in (tactical + positional)][:3]
        if reasons:
            parts.append("It works because " + _join(reasons) + ".")
        elif v.is_best_move:
            parts.append("It keeps the position at its best available evaluation.")
        else:
            parts.append("A sound move that keeps your position healthy.")
    else:
        # Lead with the REASON, not the number. Tactical facts first (concrete),
        # then the positional contrast (why the best move is better).
        reasons = [m.text for m in tactical[:2]]
        if len(reasons) < 2:
            reasons += [m.text for m in positional if m.kind == "positional_contrast"][:2 - len(reasons)]

        if v.cp_loss >= 1000:
            lead = (f"It throws away the game — {f.best_move_san} kept a decisive "
                    f"advantage and this move surrenders it")
            parts.append((lead + (": " + _join(reasons) if reasons else "") + "."))
        elif reasons:
            parts.append("The problem: " + _join(reasons) + ".")
        else:
            # Truly diffuse positional slip — be honest rather than invent a reason.
            parts.append(
                f"It's a subtle positional slip: the engine prefers {f.best_move_san} "
                f"for long-term reasons rather than anything you can point to in one move."
            )

        if f.refutation_san and tactical:
            parts.append("The main line is: " + " ".join(f.refutation_san[:4]) + ".")
        if f.best_line_san:
            parts.append(f"{f.best_move_san} was better: " + " ".join(f.best_line_san[:4]) + ".")
        if v.cp_loss < 1000:          # the pawn figure is meaningless at mate scale
            parts.append(f"(about {v.cp_loss / 100:.1f} pawns worse.)")
        if v.swung_the_game:
            parts.append("This is the move that changed who is winning.")

    return " ".join(parts)


# --------------------------------------------------------------------------
# Optional local-LLM narration
# --------------------------------------------------------------------------
def _facts_block(f: CoachingFacts) -> str:
    tac = "; ".join(m.text for m in f.motif_report.tactical) or "none"
    pos = "; ".join(m.text for m in f.motif_report.positional) or "none"
    return (
        f"Side to move: {f.mover}\n"
        f"Move played: {f.move_san}\n"
        f"Verdict (already decided, do not change): {f.quality.quality.value}\n"
        f"Centipawn loss vs best: {f.quality.cp_loss}\n"
        f"Eval after best move ({f.best_move_san}): {_pawns(f.eval_before_cp)} pawns\n"
        f"Eval after move played: {_pawns(f.eval_after_cp)} pawns\n"
        f"Best move and line: {f.best_move_san} -> {' '.join(f.best_line_san[:5])}\n"
        f"Refutation / main line after move played: {' '.join(f.refutation_san[:5]) or 'none'}\n"
        f"Tactical facts: {tac}\n"
        f"Positional hints: {pos}\n"
    )


_SYSTEM = (
    "You are a patient chess coach talking to an improving club player. "
    "Explain, in 2-4 short sentences of plain language, WHY the move earned "
    "its verdict, so the student builds intuition rather than memorising "
    "numbers. Rules you must obey: use ONLY the facts provided; never invent "
    "moves, lines, or evaluations; do not contradict the given verdict; refer "
    "to moves in the notation given. Prefer concrete cause-and-effect "
    "('this leaves the knight loose, so Black wins it with ...') over vague "
    "praise. Do not restate the centipawn number as the reason."
)


def ollama_explanation(f: CoachingFacts, *, model: str | None = None, timeout: float = 60.0) -> str:
    """Ask a local Ollama model to narrate the facts. Raises on failure."""
    model = model or OLLAMA_MODEL
    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0.3},
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _facts_block(f) + "\nWrite the explanation now."},
        ],
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data.get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("Ollama returned an empty response.")
    return content


def ollama_available(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def explain(f: CoachingFacts, *, use_llm: bool = True, model: str | None = None) -> tuple[str, str]:
    """Return (explanation_text, source) where source is 'ollama' or 'template'."""
    if use_llm:
        try:
            return ollama_explanation(f, model=model), "ollama"
        except Exception:
            pass  # fall through to the always-correct baseline
    return template_explanation(f), "template"


def _join(items) -> str:
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]
