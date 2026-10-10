# chesscoach — a local chess tutor that explains *why*, not just +/−

A fully local prototype that coaches your chess by explaining, in plain
language, **why** a move is good or bad — the refutation line, the hanging
piece, the missed fork — instead of only showing a centipawn number.

## The one idea that makes it work

> **The engine thinks. The language model talks. The language model is never
> allowed to invent the numbers.**

Two jobs that look like one but aren't:

| Job | Who does it | Why |
|---|---|---|
| *Is this move good? What's best? By how much?* | **Stockfish** (search + calculation) | LLMs play weak chess — they hallucinate illegal moves and confidently misjudge positions. Letting an LLM grade moves would teach bad chess. |
| *Why, in human terms?* | **A small local LLM** (narration only) | Given the engine's facts, it turns them into intuitive prose. It can't fabricate the verdict because it's handed the verdict. |

Between them sits a **motif layer** that converts the position and the engine's
lines into human chess concepts (hanging piece, fork, check, lost castling,
the refutation line, decisive swing), so the explanation is concrete.

```
 played move ─► Stockfish ─► classify ─► motifs ─► explain ─► coaching text
                (truth)      (quality)   (why)      (voice)
```

## What it does today (v1, CLI)

- Grades any move as `best / excellent / good / inaccuracy / mistake / blunder`
  (plus `brilliant` for sound sacrifices), from the engine's centipawn loss.
- Explains the move with **concrete, verifiable facts**: the refutation line,
  material won, the hanging piece, forced mate, and the better alternative.
- **Two explainers**, chosen automatically:
  - **Ollama** (local LLM) for friendly prose — default `qwen2.5:7b-instruct`.
  - a **deterministic template** fallback that is hallucination-proof and
    needs no model. If Ollama isn't running, it's used automatically.
- Three CLI modes: single move, whole-PGN review, and play-vs-Stockfish with
  live coaching on your moves.

## Honest limits (read this)

- **Tactical "why" is reliable.** It comes from forcing lines the engine
  actually calculates. Trust it.
- **Positional "why" is softer.** Modern NNUE engines are black boxes: they
  know a quiet move is +0.4 but can't say why in words. Those explanations are
  the LLM's interpretation — useful, but occasionally hand-wavy. The motif
  layer tags facts as tactical vs positional so the two aren't conflated.
- A 7B model on CPU narrates in a few seconds — fine for turn-based study, not
  for real-time blitz.

## Setup (Linux / macOS, incl. AMD Ryzen laptops — CPU is fine)

```bash
# 1. Python deps
pip install -r requirements.txt

# 2. Stockfish (the source of truth)
#    Debian/Ubuntu:  sudo apt install stockfish
#    macOS:          brew install stockfish
#    or a static build from https://stockfishchess.org/download/
#    If it's not on PATH, point to it:
export CHESSCOACH_STOCKFISH=/path/to/stockfish

# 3. (Optional) Local LLM for nicer prose
#    Install Ollama from https://ollama.com, then:
ollama pull qwen2.5:7b-instruct
#    Without this, the deterministic template explainer is used automatically.
```

## Usage

```bash
# Coach one move from a position
python coach_cli.py move \
  --fen "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2" \
  --san Nf3

# Review a whole game (only noteworthy moves unless --all)
python coach_cli.py pgn game.pgn
python coach_cli.py pgn game.pgn --side white --all

# Play against Stockfish and get coached on every move you make
python coach_cli.py play --level 3 --color white

# Force the no-LLM, deterministic explainer
python coach_cli.py --no-llm move --fen "<FEN>" --san Qh5
```

Useful flags: `--movetime 0.5` (engine seconds per analysis),
`--depth 16` (fixed depth instead of time), `--model <ollama-model>`.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `CHESSCOACH_STOCKFISH` | *(PATH search)* | Path to the Stockfish binary |
| `CHESSCOACH_MODEL` | `qwen2.5:7b-instruct` | Ollama model for narration |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint |

## Project layout

```
chesscoach/
  engine.py     Stockfish wrapper — the ONLY source of evals and best moves
  classify.py   centipawn-loss → move quality
  motifs.py     position + engine lines → human chess concepts ("why")
  explain.py    grounded template + optional Ollama narration ("voice")
  coach.py      wires the pipeline together
coach_cli.py    CLI (move / pgn / play)
tests/          engine-independent unit tests (run without Stockfish/Ollama)
```

## Running the tests

```bash
python tests/test_logic.py        # or: python -m pytest tests/ -q
```

## Roadmap

- Web UI (local server + board) once the coaching text is tuned — the CLI is
  the proving ground first, by design.
- Richer motif detection (pins, discovered attacks, outposts, pawn structure).
- Opening-book / endgame-tablebase awareness so early and trivial positions
  aren't over-analysed.
- Optional fine-tuned explainer model (only after the grounded pipeline proves
  its value — not a starting requirement).
