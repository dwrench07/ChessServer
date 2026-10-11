"""Progression: XP, levels, a game grade, and a growing kingdom.

Turns a pile of one-off games into a journey. Pure functions (no I/O) so they
are easy to test; the store holds the running totals.
"""

from __future__ import annotations

# Cumulative XP needed to *reach* each level (index 0 = level 1).
_THRESHOLDS = [0, 100, 250, 450, 700, 1000, 1400, 1900, 2500, 3200, 4000, 5000]

# What your kingdom looks like at each level (unlocked cumulatively).
_KINGDOM = [
    ("🏕️", "Camp"), ("🛖", "Hut"), ("🏘️", "Village"), ("⛪", "Chapel"),
    ("🏰", "Keep"), ("🏯", "Castle"), ("🗼", "Watchtower"), ("🏛️", "Citadel"),
    ("👑", "Throne Room"), ("🏰", "Capital"), ("🌟", "Empire"), ("⚜️", "Dynasty"),
]


def xp_for(won: bool, drew: bool, accuracy: float | None) -> int:
    """XP earned for a finished game: a base, a result bonus, and an accuracy
    bonus (so a well-played loss still pays better than a sloppy one)."""
    xp = 10
    xp += 30 if won else (12 if drew else 3)
    if accuracy is not None:
        xp += round(accuracy / 4)
    return int(xp)


def level_for_xp(xp: float) -> int:
    lvl = 1
    for i, t in enumerate(_THRESHOLDS):
        if xp >= t:
            lvl = i + 1
    return lvl


def level_progress(xp: float) -> dict:
    """Level, and progress toward the next level for a bar."""
    lvl = level_for_xp(xp)
    cur = _THRESHOLDS[lvl - 1] if lvl - 1 < len(_THRESHOLDS) else _THRESHOLDS[-1]
    nxt = _THRESHOLDS[lvl] if lvl < len(_THRESHOLDS) else None
    pct = 100 if nxt is None else round(100 * (xp - cur) / (nxt - cur))
    return {"level": lvl, "xp": int(xp), "levelFloor": cur, "nextAt": nxt, "pct": max(0, min(100, pct))}


def kingdom_for_level(level: int) -> list[dict]:
    out = []
    for i, (icon, name) in enumerate(_KINGDOM):
        out.append({"icon": icon, "name": name, "unlocked": (i + 1) <= level})
    return out


def grade(accuracy: float | None) -> str:
    if accuracy is None:
        return "—"
    if accuracy >= 95:
        return "A+"
    if accuracy >= 90:
        return "A"
    if accuracy >= 80:
        return "B"
    if accuracy >= 70:
        return "C"
    if accuracy >= 60:
        return "D"
    return "E"
