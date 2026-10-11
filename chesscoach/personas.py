"""Campaign personas — a ladder of named opponents.

Standard chess throughout (no rule changes): a persona is pure flavour wrapped
around a Stockfish strength setting, plus a gate on the player's progression
level so the campaign unfolds instead of dropping the learner against a
grandmaster on day one. Each persona has a voice so the opponent feels like a
character, not a slider.

A persona is "beaten" when the learner has won at least one played game at that
persona's engine level or higher — derived from real game history, never
asserted. Beating the hardest persona is the campaign's summit.
"""

from __future__ import annotations

# level       -> the engine level (as used by webapp api_engine) this persona plays at
# unlockLevel -> the player's progression level (chesscoach.progress) required to face them
_PERSONAS = [
    {"id": "novice", "name": "The Novice", "icon": "🪖", "level": 1, "unlockLevel": 1,
     "voice": "I'm still learning the moves — go easy on me. Or don't."},
    {"id": "cadet", "name": "The Cadet", "icon": "🎖️", "level": 2, "unlockLevel": 1,
     "voice": "Drilled in the basics. I won't hang pieces for free anymore."},
    {"id": "tactician", "name": "The Tactician", "icon": "🗡️", "level": 3, "unlockLevel": 2,
     "voice": "Leave a square loose and I'll find the fork. Watch your king."},
    {"id": "baron", "name": "The Baron", "icon": "🏰", "level": 4, "unlockLevel": 3,
     "voice": "I build slowly, take your squares, and strangle you by move 40."},
    {"id": "general", "name": "The General", "icon": "⚔️", "level": 5, "unlockLevel": 4,
     "voice": "I coordinate every piece. Your weaknesses are my battle plan."},
    {"id": "strategist", "name": "The Strategist", "icon": "🧠", "level": 6, "unlockLevel": 6,
     "voice": "Tactics are for amateurs. I win the game three plans ahead of you."},
    {"id": "grandmaster", "name": "The Grandmaster", "icon": "👑", "level": 8, "unlockLevel": 8,
     "voice": "You've come far. Now show me you deserve to be here."},
]


def ladder() -> list[dict]:
    """The personas in campaign order (copies, safe for the caller to annotate)."""
    return [dict(p) for p in _PERSONAS]


def campaign_state(player_level: int, wins_by_level: dict[int, int]) -> dict:
    """Annotate the ladder with unlocked / beaten / current state.

    `player_level` is the learner's progression level. `wins_by_level` maps an
    engine level to how many games the learner has won at that level. A persona
    counts as beaten if the learner has won at that level or any higher one
    (beating a stronger opponent subsumes the weaker rung).
    """
    def wins_at_or_above(level: int) -> int:
        return sum(c for lv, c in wins_by_level.items() if lv >= level)

    out = []
    current_set = False
    for p in _PERSONAS:
        entry = dict(p)
        entry["unlocked"] = player_level >= p["unlockLevel"]
        entry["beaten"] = entry["unlocked"] and wins_at_or_above(p["level"]) > 0
        entry["current"] = False
        # The "current" quest is the first unlocked-but-not-yet-beaten persona.
        if not current_set and entry["unlocked"] and not entry["beaten"]:
            entry["current"] = True
            current_set = True
        out.append(entry)

    beaten = sum(1 for e in out if e["beaten"])
    return {
        "personas": out,
        "beaten": beaten,
        "total": len(out),
        "complete": beaten == len(out),
        "playerLevel": player_level,
    }


def persona_by_id(pid: str) -> dict | None:
    for p in _PERSONAS:
        if p["id"] == pid:
            return dict(p)
    return None
