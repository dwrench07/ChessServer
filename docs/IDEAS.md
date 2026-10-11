# chesscoach — idea backlog

The full menu of ideas from our design sessions, in one place. This is a
backlog to pick from, not a commitment.

**Legend:** ✅ built · ⭐ recommended next · 🎭 engagement/feel · 🎓 teaching ·
⚡ reuses analysis we already run (cheap) · L/M/H effort · 🔌 needs a new
engine/dependency.

---

## 0. Already built (baseline)

- ✅ Engine-truth + LLM-narration coaching: per-move verdict **and the why**.
- ✅ Static Exchange Evaluation grounding (real hangs vs defended pieces).
- ✅ Positional "why" for quiet inaccuracies (king safety, centre, development…).
- ✅ Strategy coach — "What's the plan?" + strategic game review (phase, turning point).
- ✅ Recurring-mistake detection ("you've hung a piece in N of your last M games").
- ✅ Threat radar ("they're threatening to win your queen with exd5").
- ✅ Learning analytics: accuracy by phase, performance by opening, weakness trend.
- ✅ Real-world analogies + concept-card library (war lens).
- ✅ Eval bar, running accuracy, auto-save, Dashboard, PGN/Lichess import, review replay.
- ✅ CLI (move / pgn / play), Docker (+ auto model pull), GPL-3.0 + CREDITS + OSS survey.

---

## 1. The "make it interesting" headliners

### 1a. 🎭🎓 The Plot (House-of-Cards mode) — ⭐ top pick
Surface the hidden drama already in chess: a quiet early move (the *seed*) that
only pays off much later (the *strike*).
- **Post-game "Plot reveal"** *(M, ⚡)* — find the strike (biggest swing), trace
  what enabled it back to the quiet move that first set it up, narrate it as a
  three-act story, and let you step the acts on the board. Fires **only** when
  there's a real multi-move thread — stays honest when a game was just a blunder.
- **Live suspense** *(H, ⚡)* — as the engine executes a long plan, build a
  "a scheme is forming" sense, then the reveal: "that pawn 8 moves ago was the plan."

### 1b. 🎭 Real-time juice
- Hanging / opportunity glow (your loose pieces amber, their winnable pieces green) ✓picked *(M, ⚡)*
- Win-probability % + momentum swing popups *(L, ⚡)*
- Brilliant confetti + accuracy streak counter *(L, ⚡)*
- Capture animations — per-piece signature motion + particle burst (+ optional sound) *(M)*
- Running game grade (live A/B/C report card) *(L, ⚡)*

### 1c. 🎓🎭 Live teaching nudges
- Sharpness meter + "you have something here" tactic nudge ✓picked *(M, ⚡)*
- Critical-moment flag ("this is a key decision") *(M, ⚡)*
- Missed-opportunity flash ("you had a tactic there") *(L, ⚡)*
- Phase-transition note ("entering the endgame — activate your king") *(L, ⚡)*
- Out-of-book nudge; opponent-plan whisper at quiet moments *(L–M)*

### 1d. 🎭 Direction-1 empire / progression (wraps real chess, engine unchanged)
- Build-your-kingdom: wins + accuracy earn resources; spend on a persistent base *(M)*
- Campaign / conquest overworld: beat a region's boss persona, Risk-style *(M)*
- Tech tree of skills: "research" unlocks coaching tools / lessons *(M, also 🎓)*
- Unlocks: cosmetic piece sets, board skins, titles *(M)*
- Resource economy for assists (hints, takebacks, puzzle entries) *(L–M)*

### 1e. 🎭 Story / campaign
- Personas + before/after cutscenes (LLM dialogue), escalating boss strength *(M)*
- Per-level **objectives / handicaps** ("win without hanging a piece", "survive 40 moves") — real stakes, not just flavour *(M)*

### 1f. 🎭🎓 New modes (variety)
- Puzzle Rush from **your own** blunders — short, scored, against a clock *(M)*
- Objective challenges / daily challenge *(M)*
- Guess-the-move (solitaire over your game or a master game) *(M, ⚡)*
- Guess-the-engine-reply mini-challenge *(M, ⚡)*

---

## 2. Coaching / algorithm menu

**Personalization**
- ✅ Recurring-mistake detection · position-similarity recall *(M)* · opening-leak
  finder (partly ✅ via analytics) · tilt/fatigue detection *(L, ⚡)* ·
  spaced-repetition of your blunders *(M)* · strength estimate from accuracy *(L)*

**Board awareness**
- Region-buildup / attention asymmetry ("they're massing kingside, you have no
  defenders there") *(M)* · ✅ threat radar · attack-vs-defense race meter *(M)* ·
  missed-tactic caller *(M, ⚡)* · control heatmap *(M)*

**Game quality**
- Critical-moment detection (MultiPV gap) *(M, ⚡)* · complexity / danger meter *(M, ⚡)*

**Teaching content**
- Endgame technique checks via tablebase *(M, 🔌 python-chess tablebases, free)* ·
  master-game echo *(H)* · plan-adherence score *(H, soft)*

**Engagement**
- Guess-the-move · badges / streaks *(L)* · adaptive opponent (eases/ramps to your play) *(M, ⚡)*

**Real ML**
- Maia — human-move prediction by rating ("a 1500 plays X here") *(M–H, 🔌 lc0 + Maia weights)* ·
  play-style clustering *(M)* · blunder-prediction model *(H)*

---

## 3. Real-time in-game — full catalog

**Safety / assist:** "Are you sure?" blunder guard · takeback-on-blunder offer ·
"only-move" alert.
**Board awareness:** hanging/opportunity glow · attack/defense heat overlay ·
threatened-piece highlight · live pin/fork/skewer markers · king danger zone ·
piece influence rays · move trail.
**Teaching nudges:** sharpness meter + tactic nudge · critical-moment flag ·
missed-opportunity flash · phase-transition note · out-of-book nudge · opponent-plan whisper.
**Game feel:** win% + momentum · accuracy streak + Brilliant confetti · running game grade · milestones/badges.
**Opponent/interaction:** persona commentary (LLM) · guess-the-reply · per-move
strength estimate · adaptive difficulty.
**Tension:** chess clock + time-trouble warnings · danger meter.
**Live readouts:** eval sparkline · material/imbalance tracker · captured-pieces
tray · coach whisper (one line per move).

---

## 4. Visual / juice / cosmetic

- Capture animations (per-piece signature motion + particles) *(M)*
- Real piece art — Cburnett SVG set *(M, asset: GPL/CC-BY-SA, attribute)*
- Board themes / skins · sound effects · move-confirmation haptics *(L–M)*

---

## 5. Variants (Direction 2 — a *different* game, not standard chess)

> Standard Stockfish only plays standard chess + Chess960. The rest need
> **Fairy-Stockfish** (🔌 GPL) or custom rules, and our coaching won't transfer cleanly.

- Chess960 (free on standard Stockfish) *(L)*
- Fog of war / "Dark chess" *(H, 🔌)* · Crazyhouse drops *(H, 🔌)* ·
  unit upgrades *(H, custom)* · terrain/forts/resource squares *(H, custom)* ·
  army-building setup *(M–H)* · king-as-castle with HP *(H, custom)*

---

## 6. Enablers / infrastructure

- Opening-book naming (python-chess polyglot) *(L, free)*
- Endgame tablebases (python-chess) *(M, free)*
- Fairy-Stockfish (unlocks variants) *(M, 🔌)*
- Maia weights (human-like opponent/analysis) *(M–H, 🔌)*
- MCP server wrapper (use chesscoach inside Claude Code) *(M)*
- ✅ Licensing + attribution already in place (GPL-3.0, CREDITS.md, OSS survey)

---

## Recommended build order (highest feeling / lowest risk first)

1. **The Plot — post-game reveal** (1a) — the House-of-Cards payoff; the most
   distinctive thing on this list, and grounded.
2. **Real-time juice** (1b) — glow + win%/momentum + confetti + capture animation;
   instantly changes how a game *feels*.
3. **Live teaching nudges** (1c) — sharpness/tactic/critical-moment.
4. **Progression spine** (1d) — XP/level, game grade, a growing kingdom in the
   SQLite we already have.
5. **One new mode** (1f) — Puzzle Rush from your own blunders.
6. **Campaign + personas** (1e) + **The Plot live-suspense** (1a) on top.
