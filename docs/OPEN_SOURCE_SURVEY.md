# Open-source survey — what to borrow, and how to do it cleanly

A shortlist of chess open-source projects worth drawing from, grouped by the
four areas we care about: **board UI & assets**, **analysis/coaching logic**,
**training features**, and **explanation/LLM approaches**.

For each we record the **license**, what is worth taking, and the **integration
mode**: _idea_ (reimplement, no obligation), _code_ (copy under a GPL-compatible
license into `third_party/`), or _asset_ (images/sounds/fonts with their own
license). Anything taken moves into `CREDITS.md` when integrated.

> **License accuracy.** Licenses marked **✓ verified** were checked during this
> survey. Others are from general knowledge and **must be confirmed from the
> project's own `LICENSE` before any code or asset is copied** — only ideas can
> be used without that check. We are a GPL-3.0 project, so we can reuse GPL /
> LGPL / MIT / BSD / Apache-2.0 code, but **not AGPL code** (its network clause
> would bind this whole web app).

## 1. Board UI & piece assets

| Project | License | Take | Mode | Notes |
|---|---|---|---|---|
| [lichess chessground](https://github.com/lichess-org/chessground) | **GPL-3.0 ✓** | Smooth drag/drop, premoves, animations, arrow/annotation layer | idea (or code — GPL is fine) | Despite being a Lichess project, the board library is **GPL-3.0**, not AGPL (only the `lila` server is AGPL). GPL-compatible, so we may vendor it if we want a battle-tested board instead of our hand-rolled one. |
| [cm-chessboard](https://github.com/shaack/cm-chessboard) | MIT *(confirm)* | Dependency-free SVG board with markers/arrows | code | A clean MIT board that matches our no-dependency ethos. Verify the `LICENSE` (our fetch was blocked this session). |
| [chessboard.js](https://github.com/oakmac/chessboardjs) | MIT *(confirm)* | Classic board widget, drag/drop | code | Needs jQuery; heavier than cm-chessboard. |
| [react-chessboard](https://github.com/Clariity/react-chessboard) | MIT *(confirm)* | React board with animations | code | Only if we move the UI to React (we currently avoid frameworks). |
| [Cburnett chess pieces](https://commons.wikimedia.org/wiki/Category:SVG_chess_pieces) | **GPL / BSD / GFDL + CC-BY-SA-3.0 ✓** | The standard Wikipedia/Lichess piece SVG set | asset | Multi-licensed; use under GPL or CC-BY-SA with attribution. Would replace our Unicode glyphs with real piece art. |

**Recommendation:** our hand-rolled board is fine for now. The highest-value
asset lift is a **real piece set (Cburnett or similar)** to replace Unicode
glyphs — purely cosmetic, low risk, big visual upgrade.

## 2. Analysis & coaching logic

| Project | License | Take | Mode | Notes |
|---|---|---|---|---|
| [Stockfish](https://github.com/official-stockfish/Stockfish) | **GPL-3.0** | Already used | — | Source of truth. |
| [python-chess](https://github.com/niklasf/python-chess) | **GPL-3.0** | Already used; also has a **polyglot opening-book** reader and **Gaviota/Syzygy tablebase** probing we haven't used yet | code (already a dep) | Add opening-book naming ("this is the Italian Game") and endgame-tablebase exactness for free — same dependency. |
| [Leela Chess Zero (lc0)](https://github.com/LeelaChessZero/lc0) | GPL-3.0 *(confirm)* | A second engine with a more "human"/positional style | idea/integration | Our engine layer is already UCI-based; adding lc0 as an alternate opponent/analter is mostly config. Heavy (NN weights). |
| [en-croissant](https://github.com/franciscoBSalgueiro/en-croissant) | **GPL-3.0 ✓** | Accuracy/eval-graph presentation, repertoire & database UX | idea | A modern analysis GUI; good reference for how to present eval graphs and game databases. |
| [Lichess accuracy/winning-chances model](https://github.com/lichess-org/lila) | AGPL-3.0 | The win%→accuracy math | idea only | We already reimplemented this in `accuracy.py`. **Do not copy their code** (AGPL). |

**Recommendation:** two cheap, high-value lifts that need no new dependency —
**opening-book naming** and **tablebase-exact endgame verdicts**, both via the
`python-chess` we already ship.

## 3. Training features

| Project | License | Take | Mode | Notes |
|---|---|---|---|---|
| [Lichess puzzle database](https://database.lichess.org/) | **CC0 ✓** *(confirm current terms)* | ~4M rated tactics puzzles (`lichess_db_puzzle.csv`) | asset (data) | Public-domain data — the cleanest possible source for a puzzle trainer. Pairs perfectly with our stored-blunder idea. |
| [Lucas Chess](https://github.com/lukasmonk/lucaschess) | GPL-3.0 *(confirm)* | Training-mode designs, engine-ladder opponents | idea | Mature trainer; good for feature ideas, GPL so code is compatible too. |
| [PyChess](https://github.com/pychess/pychess) | GPL-3.0 *(confirm)* | Hint/learn modes, PGN database handling | idea | |

**Recommendation:** combine the **CC0 Lichess puzzle set** with our existing
mistake-tagging to generate puzzles **from the user's own blunders** — a
differentiator tintins also has, but ours would be driven by the dashboard's
per-user weakness data.

## 4. Explanation / LLM approaches

| Project | License | Take | Mode | Notes |
|---|---|---|---|---|
| [tintins-chess-analysis](https://github.com/Chess-analysis-mcp/tintins-chess-analysis) | MIT *(confirm)* | Prompt structure for grounding LLM commentary; MCP tool surface | idea | Same core philosophy as us (engine grounds, LLM explains). Good reference for an MCP server wrapper and for chat-style coaching. |
| Various "GPT chess coach" repos | mostly MIT *(confirm each)* | Prompt templates for move explanation | idea | Quality varies; most make the mistake we avoid (letting the LLM judge). Borrow phrasing ideas only. |

**Recommendation:** the biggest win here is **turning chesscoach into an MCP
server** (like tintins) so it works inside Claude Code / other MCP clients —
expose `analyze_move`, `review_game`, `best_line` as tools over the pipeline we
already have. That is an *idea* lift (our own code), zero license risk.

---

## Suggested integration order (highest value / lowest risk first)

1. **Real piece set** (Cburnett, asset) — cosmetic upgrade, trivial.
2. **Opening-book naming** (python-chess, no new dep) — "this is the Italian Game".
3. **Puzzles from your own blunders** (Lichess CC0 data + our mistake tags).
4. **Tablebase-exact endgame verdicts** (python-chess, no new dep).
5. **MCP server wrapper** (our code) — makes it usable inside Claude Code.

Each, when built, gets a row in `CREDITS.md` naming the source, author, and
license, and (for copied code/assets) a `third_party/<name>/` folder with the
original license text.
