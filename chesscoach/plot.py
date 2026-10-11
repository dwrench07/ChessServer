"""The Plot — the House-of-Cards narrative of a game.

Chess hides a story: a quiet early move (the *seed*) that only pays off much
later (the *strike*). A normal UI shows none of it. This module reconstructs
that arc from a game's per-ply analysis:

  1. Find the **strike** — the winner's move that delivered the decisive blow
     (the biggest favourable eval swing into a winning position).
  2. Trace the striking piece back along its own path to the **seed** — the
     earliest *quiet* move that first set it on the road to the strike square.
  3. The moves in between are the **buildup**.

It stays honest: if a game was balanced, drawn, or turned on a single moment
with no slow-laid plan, there is no plot and we say so. The drama only lands
because it is real and rare.

Input is the `review` list produced by the web server's `_analyze_pgn` — one
dict per ply with: side, san, moveNumber, playedFrom, playedTo, evalCp (mover
POV), fenBefore, quality.
"""

from __future__ import annotations

_PIECE = {"N": "knight", "B": "bishop", "R": "rook", "Q": "queen", "K": "king"}

DECISIVE = 150      # centipawns: "winning"
MIN_BLOW = 120      # a strike must swing at least this much
MIN_GAP = 5         # plies between seed and strike for a real "plot"
QUIET_JUMP = 70     # a seed move changed the eval by less than this


def _piece_name(san: str) -> str:
    s = san.lstrip()
    return _PIECE.get(s[0], "pawn") if s else "pawn"


def _is_quiet(san: str) -> bool:
    return not any(ch in san for ch in ("x", "+", "#", "="))


def _node(c: dict, swing: int | None = None) -> dict:
    n = {
        "ply": c["ply"], "moveNumber": c["moveNumber"], "side": c["side"],
        "san": c["san"], "from": c["playedFrom"], "to": c["playedTo"],
        "fenBefore": c.get("fenBefore"),
    }
    if swing is not None:
        n["swing"] = swing
    return n


def live_plot(review: list[dict]) -> dict:
    """The live, in-game version of the plot: did the move *just played* land a
    decisive blow that a quiet earlier move set up?

    Unlike find_plot (which tells the whole story after the game), this asks a
    narrower question at every ply: is the latest move a *strike*, and can its
    piece be traced back to a quiet *seed* laid well before? When yes, it hands
    back a short callback so the UI can reveal — at the payoff moment — that the
    plan was laid long ago. Pure eval math (mover-POV evalCp per ply), no engine.

    Returns {fired: False} unless the latest move completes a real plot.
    """
    n = len(review)
    if n < MIN_GAP + 2:
        return {"fired": False}

    last = n - 1
    mover = review[last]["side"]

    # White-POV eval after each ply (evalCp is mover-POV per the review contract).
    white = []
    for c in review:
        cp = c.get("evalCp")
        if cp is None:
            cp = int(round(c.get("evalAfter", 0) * 100))
        white.append(cp if c["side"] == "white" else -cp)

    msign = 1 if mover == "white" else -1
    mser = [msign * x for x in white]           # mover's advantage after each ply

    # Is the latest move a strike by `mover`? Either a mate, or a big favourable
    # jump that leaves `mover` decisively winning.
    is_mate = review[last]["san"].endswith("#")
    jump = mser[last] - (mser[last - 1] if last > 0 else 0)
    if not is_mate and not (mser[last] >= DECISIVE and jump >= MIN_BLOW):
        return {"fired": False}

    # Trace the striking piece back along its own squares (same side only).
    path = [last]
    cur_sq = review[last]["playedFrom"]
    k = last - 1
    while k >= 0:
        c = review[k]
        if c["side"] == mover and c["playedTo"] == cur_sq:
            path.append(k)
            cur_sq = c["playedFrom"]
        k -= 1
    path.sort()

    seed_i = None
    for i in path:
        if i == last:
            continue
        prev = mser[i - 1] if i > 0 else 0
        if _is_quiet(review[i]["san"]) and abs(mser[i] - prev) < QUIET_JUMP and (last - i) >= MIN_GAP:
            seed_i = i
            break
    if seed_i is None:
        return {"fired": False}

    seed, strike = review[seed_i], review[last]
    piece = _piece_name(strike["san"])
    moves_ago = strike["moveNumber"] - seed["moveNumber"]
    who = "White" if mover == "white" else "Black"
    if is_mate:
        text = (f"The plot pays off. That quiet {seed['san']} on move "
                f"{seed['moveNumber']} set this {piece} on its road — and now, "
                f"{moves_ago} moves later, {strike['san']} is checkmate.")
    else:
        text = (f"The plot pays off. {seed['san']} back on move {seed['moveNumber']} "
                f"looked like nothing — but it aimed this {piece}, and {moves_ago} "
                f"moves later {strike['san']} lands the blow.")

    return {
        "fired": True,
        "mover": who,
        "piece": piece,
        "kind": "mate" if is_mate else "blow",
        "movesAgo": moves_ago,
        "seed": _node(seed),
        "strike": _node(strike, max(0, jump)),
        "text": text,
    }


def find_plot(review: list[dict]) -> dict:
    if len(review) < 8:
        return {"hasPlot": False, "reason": "too short a game to hold a plot."}

    # White-POV eval after each ply, then winner-POV.
    white = []
    for c in review:
        cp = c.get("evalCp")
        if cp is None:
            cp = int(round(c.get("evalAfter", 0) * 100))
        white.append(cp if c["side"] == "white" else -cp)

    final = white[-1]
    if abs(final) < DECISIVE:
        return {"hasPlot": False, "reason": "the game stayed balanced — no decisive plot to tell."}

    winner = "white" if final > 0 else "black"
    wsign = 1 if winner == "white" else -1
    wser = [wsign * x for x in white]   # winner's advantage after each ply

    # Strike: either the mating move that ends the game, or (when already
    # winning without a mate) the move with the biggest favourable eval jump.
    last = len(review) - 1
    best_i, best_jump, kind = None, 0, "blow"
    if review[last]["san"].endswith("#") and review[last]["side"] == winner:
        best_i = last
        best_jump = max(0, wser[last] - (wser[last - 1] if last > 0 else 0))
        kind = "mate"
    else:
        for i, c in enumerate(review):
            if c["side"] != winner:
                continue
            prev = wser[i - 1] if i > 0 else 0
            jump = wser[i] - prev
            if jump > best_jump and wser[i] >= DECISIVE:
                best_i, best_jump = i, jump
        if best_i is None:      # no clean decisive blow; fall back to biggest jump
            for i, c in enumerate(review):
                if c["side"] != winner:
                    continue
                prev = wser[i - 1] if i > 0 else 0
                jump = wser[i] - prev
                if jump > best_jump:
                    best_i, best_jump = i, jump
        if best_i is None or best_jump < MIN_BLOW:
            return {"hasPlot": False, "winner": winner,
                    "reason": "the game turned gradually, with no single decisive blow."}

    strike = review[best_i]

    # Trace the striking piece back along its own path (by square).
    path = [best_i]
    cur_sq = strike["playedFrom"]
    k = best_i - 1
    while k >= 0:
        c = review[k]
        if c["side"] == winner and c["playedTo"] == cur_sq:
            path.append(k)
            cur_sq = c["playedFrom"]
        k -= 1
    path.sort()

    # Seed: earliest quiet path move, well before the strike.
    seed_i = None
    for i in path:
        if i == best_i:
            continue
        prev = wser[i - 1] if i > 0 else 0
        if _is_quiet(review[i]["san"]) and abs(wser[i] - prev) < QUIET_JUMP and (best_i - i) >= MIN_GAP:
            seed_i = i
            break

    if seed_i is None:
        return {
            "hasPlot": False, "winner": winner,
            "reason": "this game turned on the moment itself, not a slow-laid plan.",
            "strike": _node(strike, best_jump),
        }

    buildup = [review[i] for i in path if seed_i < i < best_i]
    piece = _piece_name(strike["san"])
    journey = [review[seed_i]["playedTo"]] + [b["playedTo"] for b in buildup]

    text = (
        f"Act 1 — the seed. Move {review[seed_i]['moveNumber']}, {review[seed_i]['san']}: "
        f"it looked like nothing, but it set the {piece} on the road to {strike['playedTo']}. "
    )
    if buildup:
        text += (f"Act 2 — the slow build. The {piece} travelled "
                 f"{' → '.join(journey)}, the position staying quiet. ")
    if kind == "mate":
        text += (f"Act 3 — the strike. Move {strike['moveNumber']}, {strike['san']}: "
                 f"checkmate — and only now is the whole plan visible.")
    else:
        text += (f"Act 3 — the strike. Move {strike['moveNumber']}, {strike['san']}: the blow "
                 f"lands (about {best_jump / 100:.1f} pawns), and only now is the plan visible.")

    return {
        "hasPlot": True,
        "winner": "White" if winner == "white" else "Black",
        "piece": piece, "kind": kind,
        "seed": _node(review[seed_i]),
        "buildup": [_node(b) for b in buildup],
        "strike": _node(strike, best_jump),
        "text": text,
    }
