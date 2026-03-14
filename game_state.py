from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import random
from typing import Optional


class CardColor(Enum):
    RED = "red"
    BLUE = "blue"
    NEUTRAL = "neutral"
    ASSASSIN = "assassin"


class Team(Enum):
    RED = "red"
    BLUE = "blue"


class Role(Enum):
    SPYMASTER = "spymaster"
    GUESSER = "guesser"


class Phase(Enum):
    GIVING_CLUE = "giving_clue"
    GUESSING = "guessing"
    GAME_OVER = "game_over"


@dataclass
class Card:
    word: str
    color: CardColor
    revealed: bool = False


@dataclass
class Clue:
    word: str
    number: int
    team: Team


class GameState:
    def __init__(self, words: list[str], starting_team: Team) -> None:
        self.starting_team = starting_team
        self.current_team = starting_team
        self.phase = Phase.GIVING_CLUE
        self.current_clue: Optional[Clue] = None
        self.guesses_made: int = 0
        self.guesses_this_turn: list[str] = []
        self.winner: Optional[Team] = None
        self.log: list[str] = []

        selected = random.sample(words, 25)
        if starting_team == Team.RED:
            red_count, blue_count = 9, 8
        else:
            red_count, blue_count = 8, 9
        neutral_count = 25 - red_count - blue_count - 1

        colors = (
            [CardColor.RED] * red_count
            + [CardColor.BLUE] * blue_count
            + [CardColor.ASSASSIN]
            + [CardColor.NEUTRAL] * neutral_count
        )
        random.shuffle(colors)
        self.cards = [Card(word=w, color=c) for w, c in zip(selected, colors)]

    def get_card(self, word: str) -> Optional[Card]:
        word = word.upper()
        for card in self.cards:
            if card.word.upper() == word:
                return card
        return None

    def unrevealed_by_color(self, color: CardColor) -> list[Card]:
        return [c for c in self.cards if c.color == color and not c.revealed]

    def remaining(self, team: Team) -> int:
        color = CardColor.RED if team == Team.RED else CardColor.BLUE
        return len(self.unrevealed_by_color(color))

    def set_clue(self, word: str, number: int) -> None:
        self.current_clue = Clue(word.upper(), number, self.current_team)
        self.guesses_made = 0
        self.guesses_this_turn = []
        self.phase = Phase.GUESSING
        self.log.append(f"[{self.current_team.value.upper()}] CLUE: {word.upper()} {number}")

    def pick_card(self, word: str) -> tuple[CardColor, bool]:
        """Reveal a card. Returns (color_revealed, turn_continues)."""
        card = self.get_card(word)
        if card is None or card.revealed:
            return CardColor.NEUTRAL, False

        card.revealed = True
        self.guesses_made += 1
        self.guesses_this_turn.append(word.upper())
        team_color = CardColor.RED if self.current_team == Team.RED else CardColor.BLUE
        self.log.append(
            f"[{self.current_team.value.upper()}] {word.upper()} → {card.color.value.upper()}"
        )

        if card.color == CardColor.ASSASSIN:
            self.winner = Team.BLUE if self.current_team == Team.RED else Team.RED
            self.phase = Phase.GAME_OVER
            return card.color, False

        for team in (Team.RED, Team.BLUE):
            if self.remaining(team) == 0:
                self.winner = team
                self.phase = Phase.GAME_OVER
                return card.color, False

        if card.color != team_color:
            self._end_turn()
            return card.color, False

        if self.guesses_made >= self.current_clue.number + 1:
            self._end_turn()
            return card.color, False

        return card.color, True

    def pass_turn(self) -> None:
        self.log.append(f"[{self.current_team.value.upper()}] passed")
        self._end_turn()

    def _end_turn(self) -> None:
        self.current_team = Team.BLUE if self.current_team == Team.RED else Team.RED
        self.current_clue = None
        self.guesses_made = 0
        self.guesses_this_turn = []
        self.phase = Phase.GIVING_CLUE
