"""Real-world analogies for chess concepts — intuition scaffolding.

Each analogy maps a chess idea to a real-world parallel that teaches the *same
principle*, not just decoration. The default lens is military, since chess is
abstract warfare, but every analogy is tied to a concrete chess rule so it
builds real understanding rather than a cute mislead.

Used two ways: an opt-in one-line analogy appended to coaching, and a
browsable concept-card library.
"""

from __future__ import annotations

# key -> {title, definition, analogy}
CONCEPTS: dict[str, dict] = {
    "hanging_piece": {
        "title": "Hanging piece",
        "definition": "A piece the opponent can win because nothing adequately defends it.",
        "analogy": "Like a soldier left outside the fort with no cover — the enemy just takes them.",
    },
    "fork": {
        "title": "Fork",
        "definition": "One piece attacks two targets at once; the opponent can only save one.",
        "analogy": "Like a pincer movement that threatens two positions at once — the defender can't hold both.",
    },
    "mate": {
        "title": "King attack / mate",
        "definition": "Bringing enough force against the king that it cannot escape.",
        "analogy": "Like encircling the enemy command post — once escape routes are cut, the campaign is over.",
    },
    "material": {
        "title": "Material",
        "definition": "The total value of your pieces; being up material usually means a winning war of attrition.",
        "analogy": "Like having more troops and supplies — trade evenly and your numbers eventually decide it.",
    },
    "center": {
        "title": "The centre",
        "definition": "Central squares let your pieces reach both wings quickly.",
        "analogy": "Like holding the high ground or the central crossroads — you can redeploy faster than the enemy.",
    },
    "open_file": {
        "title": "Open file",
        "definition": "A file with no pawns; rooks on it strike deep into the enemy position.",
        "analogy": "Like an open supply highway for your artillery — put your rooks on it.",
    },
    "outpost": {
        "title": "Outpost",
        "definition": "A square in the enemy camp no enemy pawn can attack — ideal for a knight.",
        "analogy": "Like a fortified forward base behind enemy lines that can't be shelled out.",
    },
    "pawn_break": {
        "title": "Pawn break",
        "definition": "A pawn push that strikes the enemy pawn chain to open lines.",
        "analogy": "Like a breach in the trench line — it opens the front so your heavy pieces pour through.",
    },
    "pawn_majority": {
        "title": "Pawn majority",
        "definition": "More pawns than the opponent on one wing; advance them to make a passed pawn.",
        "analogy": "Like a local troop superiority on one flank — press it there, not where the enemy is strong.",
    },
    "space": {
        "title": "Space advantage",
        "definition": "Controlling more of the board cramps the opponent's pieces.",
        "analogy": "Like holding more territory — the enemy army is crowded and slow; don't trade that edge away.",
    },
    "king_safety": {
        "title": "King safety",
        "definition": "Castling and a pawn shield keep your king out of the firing line.",
        "analogy": "Like moving headquarters into a bunker before launching your own offensive.",
    },
    "bishop_pair": {
        "title": "The bishop pair",
        "definition": "Two bishops cover both colours and dominate open positions.",
        "analogy": "Like a long-range asset that only pays off on open ground — so open the position to use it.",
    },
    "weak_point": {
        "title": "Attack the weak point",
        "definition": "Strike where you have more force or the opponent is undefended, not head-on.",
        "analogy": "Like going around the Maginot Line through the Ardennes — bypass the fortress, hit the gap.",
    },
}

# Motif tag -> concept key (for coaching).
TAG_TO_CONCEPT = {
    "hangs_piece": "hanging_piece",
    "fork": "fork",
    "allows_mate": "mate",
    "refuted": "material",
    "gives_check": "mate",
    "captures": "material",
}


def concept_for_tag(tag: str | None) -> str | None:
    return TAG_TO_CONCEPT.get(tag) if tag else None


_PLAN_KEYWORDS = [
    ("outpost", "outpost"), ("open ", "open_file"), ("semi-open", "open_file"),
    ("majority", "pawn_majority"), ("bishop pair", "bishop_pair"),
    ("space", "space"), ("exposed enemy king", "king_safety"), ("attack", "mate"),
    ("weak", "weak_point"), ("centre", "center"), ("develop", "center"),
]


def concept_for_plan(plans: list[str]) -> str | None:
    for text in plans:
        low = text.lower()
        for kw, key in _PLAN_KEYWORDS:
            if kw in low:
                return key
    return None


def concept_list() -> list[dict]:
    return [{"key": k, **v} for k, v in CONCEPTS.items()]
