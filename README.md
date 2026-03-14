# Codenames

A terminal-based implementation of the Codenames board game where local LLMs play as AI agents via [Ollama](https://ollama.com). Built with [Textual](https://textual.textualize.io/) and managed with [uv](https://docs.astral.sh/uv/).

## Overview

Two teams — Red and Blue — compete to identify their agents on a 5×5 word grid. Each team has a **spymaster** who knows the full board and gives one-word clues, and a **guesser** who picks cards based on those clues. Hit the assassin word and your team instantly loses.

You can take any of the four roles (red/blue spymaster or guesser), with AI agents filling the remaining seats.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) running locally with at least one model pulled

## Setup

```bash
# Clone and install dependencies
git clone <repo-url>
cd code_names
uv sync

# Pull a model (deepseek-r1:8b recommended for reasoning quality)
ollama pull deepseek-r1:8b
```

## Running

```bash
uv run code-names
```

Or directly:

```bash
uv run python main.py
```

## How It Works

### Startup

On first launch you choose:
- **Your team**: Red or Blue
- **Your role**: Spymaster or Guesser
- **Starting team**: which team goes first (gets 9 cards instead of 8)
- **Base model**: the Ollama model to use for all AI agents

The app then creates two custom Ollama models — `codenames-spy` and `codenames-guesser` — from the Modelfiles in `modelfiles/`, with system prompts and sampling parameters tuned for each role. This only takes a few seconds.

### Board

```
Card distribution:
  Starting team   9 cards
  Other team      8 cards
  Neutral         7 cards
  Assassin        1 card
```

Cards are revealed as the game progresses. As spymaster you see the full colour layout; as guesser you only see unrevealed words.

### Gameplay

**As Spymaster** — enter your clue word and the number of cards it relates to in the sidebar, then submit. Your guesser (AI) will reason through the board and pick cards one at a time until it passes, guesses wrong, or uses all allowed guesses.

**As Guesser** — after the AI spymaster gives a clue, click a card to guess it, or press *End Turn* to pass. The AI's reasoning is shown live in the thinking panel on the right.

**Full AI turns** — when neither role is yours, both spymaster and guesser run automatically. Watch the thinking panel to follow the AI's reasoning.

### AI Agents

| Model | Role | Behaviour |
|---|---|---|
| `codenames-spy` | Spymaster | Outputs `{"clue": "WORD", "number": N}` |
| `codenames-guesser` | Guesser | Reasons briefly, then outputs `{"guess": "WORD"}` or `{"guess": "PASS"}` |

Both models are built on top of whichever base model you select at startup. The Modelfiles live in `modelfiles/` and can be edited to tune temperature, context window, token limits, or system prompts.

Models with a reasoning step (e.g. `deepseek-r1`) are well supported — the `<think>` block is extracted and displayed in the thinking panel separately from the answer.

## Project Structure

```
code_names/
├── main.py              # Entry point
├── app.py               # Textual UI (screens, widgets, game loop)
├── agents.py            # SpymasterAgent, GuesserAgent, ensure_models()
├── game_state.py        # GameState, Card, Clue, enums
├── codenames.tcss       # Textual CSS stylesheet
├── words.txt            # ~300 Codenames-style words
├── modelfiles/
│   ├── spymaster.Modelfile
│   └── guesser.Modelfile
└── pyproject.toml
```

## Configuration

Edit the Modelfiles in `modelfiles/` to change AI behaviour. Key parameters:

| Parameter | Default (spy / guesser) | Effect |
|---|---|---|
| `temperature` | 0.8 / 0.5 | Higher = more creative clues |
| `num_ctx` | 4096 / 4096 | Context window size |
| `num_predict` | 200 / 300 | Max tokens per response |
| `repeat_penalty` | 1.1 / 1.0 | Discourages repetition |

Changes take effect the next time you start a game (models are recreated on startup).

## Keyboard Shortcuts

| Key | Action |
|---|---|
| Click card | Guess that word (guesser turn only) |
| Enter | Submit clue (spymaster input) |
| Tab / Shift-Tab | Navigate UI elements |
| Q / Ctrl-C | Quit |
