# Credits & third-party attribution

chesscoach is built on open-source work. This file credits every project and
asset the repository depends on or incorporates, with its author and license.
It is the authoritative attribution record — when we add code, assets, or ideas
from another project, we add a row here.

chesscoach itself is licensed **GPL-3.0** (see `LICENSE`). That choice is not
arbitrary: the engine and chess library we depend on are GPL-3.0, so the
combined work is GPL-3.0.

## How we reuse others' work (the rules we follow)

- **Ideas / features / design patterns** — reused freely, reimplemented in our
  own code. No license obligation, but we still credit the project that
  inspired the feature (the "inspired by" rows below).
- **Copied code** — only from GPL-compatible licenses (GPL, LGPL, MIT, BSD,
  Apache-2.0, ISC). Kept in `third_party/<name>/` with the original `LICENSE`
  file and a note here. We do **not** copy code from AGPL projects, because the
  AGPL network clause would then apply to this web app.
- **Assets (images, piece sets, sounds, fonts)** — only with a clear license;
  attribution and any share-alike terms honoured here and in-app.

## Dependencies we use today

| Project | Author | License | How we use it |
|---|---|---|---|
| [Stockfish](https://github.com/official-stockfish/Stockfish) | The Stockfish developers | GPL-3.0 | The analysis engine — the single source of truth for evaluations and best lines. Invoked as a separate UCI binary. |
| [python-chess](https://github.com/niklasf/python-chess) | Niklas Fiekas | GPL-3.0 | Board state, move generation/validation, SAN/FEN/PGN handling. |
| [Fraunces](https://github.com/undercasetype/Fraunces) | Undercase Type | OFL-1.1 | Display typeface (web UI), loaded from Google Fonts. |
| [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) | JetBrains | OFL-1.1 | Monospace typeface for notation, loaded from Google Fonts. |

The board and its arrows in the web UI are our own implementation (hand-rolled
FEN parser + SVG), not a third-party board library. If we later adopt one, it
goes in the table below.

## Inspired by (ideas, not code)

| Project | Author | License | Idea we learned from |
|---|---|---|---|
| [Lichess](https://github.com/lichess-org/lila) | Thibault Duplessis & contributors | AGPL-3.0 | Move-quality thresholds and the win%-based accuracy model (reimplemented in `chesscoach/accuracy.py`; no Lichess code used). |

## Pending integrations

See [`docs/OPEN_SOURCE_SURVEY.md`](docs/OPEN_SOURCE_SURVEY.md) for the shortlist
of projects we are evaluating to borrow features or assets from. When one is
integrated, it moves into a table above with the specific commit/file noted.
