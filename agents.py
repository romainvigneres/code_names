from __future__ import annotations

import asyncio
import json
import random
import re
import tempfile
from pathlib import Path

import ollama

from game_state import CardColor, GameState, Team

DEFAULT_MODEL = "llama3.1:latest"

SPYMASTER_MODEL = "codenames-spy"
GUESSER_MODEL = "codenames-guesser"

_MODELFILES_DIR = Path(__file__).parent / "modelfiles"


def _extract_json(text: str) -> dict:
    """Extract first JSON object (used for spymaster)."""
    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _extract_last_json(text: str) -> dict:
    """Extract last JSON object in text (reasoning may precede it)."""
    for match in reversed(list(re.finditer(r'\{[^{}]*\}', text, re.DOTALL))):
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _split_thinking(text: str) -> tuple[str, str]:
    """Split deepseek-r1 <think>…</think> from the answer.
    Returns (thinking_content, answer_text).
    Falls back gracefully for models without think tags.
    """
    match = re.search(r'<think>(.*?)</think>', text, re.DOTALL)
    if match:
        return match.group(1).strip(), text[match.end():].strip()
    return "", text.strip()


async def ensure_models(base_model: str) -> None:
    """Create (or recreate) the two custom Codenames models from Modelfiles."""
    specs = [
        (SPYMASTER_MODEL, _MODELFILES_DIR / "spymaster.Modelfile"),
        (GUESSER_MODEL,   _MODELFILES_DIR / "guesser.Modelfile"),
    ]
    for model_name, modelfile_path in specs:
        content = modelfile_path.read_text()
        # Substitute whichever base model the user selected
        content = content.replace("FROM llama3.1:latest", f"FROM {base_model}", 1)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".Modelfile", delete=False
        ) as tmp:
            tmp.write(content)
            tmpfile = Path(tmp.name)

        try:
            proc = await asyncio.create_subprocess_exec(
                "ollama", "create", model_name, "-f", str(tmpfile),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
        finally:
            tmpfile.unlink(missing_ok=True)


class SpymasterAgent:
    def __init__(self, team: Team) -> None:
        self.team = team

    async def give_clue(self, state: GameState) -> tuple[str, int]:
        team_color = CardColor.RED if self.team == Team.RED else CardColor.BLUE
        other_color = CardColor.BLUE if self.team == Team.RED else CardColor.RED

        team_words = [c.word for c in state.unrevealed_by_color(team_color)]
        other_words = [c.word for c in state.unrevealed_by_color(other_color)]
        assassin_list = [
            c.word for c in state.cards
            if c.color == CardColor.ASSASSIN and not c.revealed
        ]
        assassin = assassin_list[0] if assassin_list else "none"
        neutral = [c.word for c in state.unrevealed_by_color(CardColor.NEUTRAL)]
        board_words = {c.word.upper() for c in state.cards}

        prompt = (
            f"You are the {self.team.value.upper()} spymaster.\n\n"
            f"Your team's words to find: {', '.join(team_words)}\n"
            f"Opponent's words (avoid): {', '.join(other_words)}\n"
            f"ASSASSIN word (never lead here): {assassin}\n"
            f"Neutral words: {', '.join(neutral)}\n\n"
            "Give ONE clue word + how many of YOUR team's words it connects."
        )

        try:
            client = ollama.AsyncClient()
            response = await asyncio.wait_for(
                client.generate(model=SPYMASTER_MODEL, prompt=prompt),
                timeout=60.0,
            )
            _, answer = _split_thinking(response.response)
            data = _extract_last_json(answer) or _extract_last_json(response.response)
            clue = str(data.get("clue", "CONNECT")).upper().strip()
            number = int(data.get("number", 1))
            if clue in board_words or not clue.isalpha():
                clue = "CONNECT"
                number = 1
            return clue, max(1, min(number, len(team_words)))
        except Exception:
            return "CONNECT", 1


class GuesserAgent:
    def __init__(self, team: Team) -> None:
        self.team = team

    async def make_guess(self, state: GameState) -> tuple[str, str]:
        """Returns (guess, raw_reasoning_text). Guess is uppercase word or 'PASS'."""
        clue = state.current_clue
        unrevealed = [c.word for c in state.cards if not c.revealed]
        guesses_left = clue.number + 1 - state.guesses_made

        prev = ""
        if state.guesses_this_turn:
            prev = f"Already guessed this turn: {', '.join(state.guesses_this_turn)}\n"

        prompt = (
            f"Spymaster's clue: \"{clue.word}\" ({clue.number} card(s))\n"
            f"{prev}"
            f"Words on the board: {', '.join(unrevealed)}\n"
            f"Guesses remaining: {guesses_left}"
        )

        try:
            client = ollama.AsyncClient()
            response = await asyncio.wait_for(
                client.generate(model=GUESSER_MODEL, prompt=prompt),
                timeout=60.0,
            )
            raw = response.response
            thinking, answer = _split_thinking(raw)
            # Display content: prefer the extracted <think> block, else the full response
            display = thinking if thinking else raw
            data = _extract_last_json(answer) or _extract_last_json(raw)
            guess = str(data.get("guess", "PASS")).upper().strip()
            if guess == "PASS":
                return "PASS", display
            unrevealed_upper = {c.word.upper() for c in state.cards if not c.revealed}
            if guess in unrevealed_upper:
                return guess, display
            if unrevealed:
                return random.choice(unrevealed).upper(), display
            return "PASS", display
        except Exception:
            return "PASS", ""
