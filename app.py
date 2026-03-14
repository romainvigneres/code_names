from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, ContentSwitcher, Input, Label, Static

from agents import GuesserAgent, SpymasterAgent, ensure_models
from game_state import CardColor, GameState, Phase, Role, Team

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_words() -> list[str]:
    words_path = Path(__file__).parent / "words.txt"
    words = [line.strip().upper() for line in words_path.read_text().splitlines() if line.strip()]
    return list(dict.fromkeys(words))  # deduplicate while preserving order


# ── CardWidget ────────────────────────────────────────────────────────────────

class CardWidget(Button):
    """A single card on the Codenames board."""

    class Picked(Message):
        def __init__(self, word: str) -> None:
            super().__init__()
            self.word = word

    _ALL_CARD_CLASSES = (
        "card--hidden",
        "card--red",
        "card--blue",
        "card--neutral",
        "card--assassin",
        "card--spy-red",
        "card--spy-blue",
        "card--spy-neutral",
        "card--spy-assassin",
    )

    def __init__(self, card, spy_view: bool = False) -> None:
        super().__init__(card.word, id=f"card-{card.word.replace(' ', '_')}")
        self._card = card
        self.refresh_display(spy_view)

    def refresh_display(self, spy_view: bool) -> None:
        for cls in self._ALL_CARD_CLASSES:
            self.remove_class(cls)

        if self._card.revealed:
            self.add_class(f"card--{self._card.color.value}")
            self.disabled = True
            self.label = self._card.word
        elif spy_view:
            self.add_class(f"card--spy-{self._card.color.value}")
            self.disabled = False
            self.label = self._card.word
        else:
            self.add_class("card--hidden")
            self.disabled = False
            self.label = self._card.word

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if not self.disabled:
            self.post_message(self.Picked(self._card.word))


# ── GameLog ───────────────────────────────────────────────────────────────────

class GameLog(ScrollableContainer):
    """Scrollable game event log."""

    def compose(self) -> ComposeResult:
        yield Label("[Game Log]", id="log-title")

    def add_entry(self, text: str) -> None:
        label = Label(text)
        self.mount(label)
        self.scroll_end(animate=False)


# ── ThinkingPanel ─────────────────────────────────────────────────────────────

class ThinkingPanel(ScrollableContainer):
    """Shows the AI guesser's reasoning for the last guess."""

    def compose(self) -> ComposeResult:
        yield Label("", id="thinking-text", markup=False)

    def set_text(self, team: str, text: str) -> None:
        header = f"[{team} guesser]\n"
        self.query_one("#thinking-text", Label).update(header + text)
        self.scroll_home(animate=False)


# ── LoadingScreen ─────────────────────────────────────────────────────────────

class LoadingScreen(Screen):
    """Shown while Ollama models are being created."""

    def __init__(self, message: str = "Setting up AI models...") -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="loading-container"):
            yield Static("C O D E N A M E S", id="loading-title")
            yield Static(self._message, id="loading-message")
            yield Static("(this only happens once per base model)", id="loading-sub")

    def update_message(self, text: str) -> None:
        self.query_one("#loading-message", Static).update(text)


# ── SetupScreen ───────────────────────────────────────────────────────────────

class SetupScreen(Screen):
    """Initial configuration screen."""

    # Track selections
    _user_team: Team = Team.RED
    _user_role: Role = Role.GUESSER
    _starting: str = "random"  # "random" | "red" | "blue"

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-container"):
            yield Static("C O D E N A M E S", id="setup-title")
            yield Static("AI-Powered Board Game", id="setup-subtitle")

            yield Static("Your Team:", classes="setup-section-label")
            with Horizontal(classes="setup-row"):
                yield Button("Red Team", id="team-red", classes="setup-btn selected")
                yield Button("Blue Team", id="team-blue", classes="setup-btn")

            yield Static("Your Role:", classes="setup-section-label")
            with Horizontal(classes="setup-row"):
                yield Button("Guesser", id="role-guesser", classes="setup-btn selected")
                yield Button("Spymaster", id="role-spymaster", classes="setup-btn")

            yield Static("Starting Team:", classes="setup-section-label")
            with Horizontal(classes="setup-row"):
                yield Button("Random", id="start-random", classes="setup-btn selected")
                yield Button("Red First", id="start-red", classes="setup-btn")
                yield Button("Blue First", id="start-blue", classes="setup-btn")

            yield Static("AI Model:", classes="setup-section-label")
            yield Input(placeholder="deepseek-r1:8b", value="deepseek-r1:8b", id="model-input")

            yield Button("Start Game", id="start-btn")

    def _select_team(self, team: Team) -> None:
        self._user_team = team
        self.query_one("#team-red").remove_class("selected")
        self.query_one("#team-blue").remove_class("selected")
        btn_id = "team-red" if team == Team.RED else "team-blue"
        self.query_one(f"#{btn_id}").add_class("selected")

    def _select_role(self, role: Role) -> None:
        self._user_role = role
        self.query_one("#role-guesser").remove_class("selected")
        self.query_one("#role-spymaster").remove_class("selected")
        btn_id = "role-guesser" if role == Role.GUESSER else "role-spymaster"
        self.query_one(f"#{btn_id}").add_class("selected")

    def _select_starting(self, choice: str) -> None:
        self._starting = choice
        for bid in ("start-random", "start-red", "start-blue"):
            self.query_one(f"#{bid}").remove_class("selected")
        self.query_one(f"#start-{choice}").add_class("selected")

    @on(Button.Pressed, "#team-red")
    def on_team_red(self) -> None:
        self._select_team(Team.RED)

    @on(Button.Pressed, "#team-blue")
    def on_team_blue(self) -> None:
        self._select_team(Team.BLUE)

    @on(Button.Pressed, "#role-guesser")
    def on_role_guesser(self) -> None:
        self._select_role(Role.GUESSER)

    @on(Button.Pressed, "#role-spymaster")
    def on_role_spymaster(self) -> None:
        self._select_role(Role.SPYMASTER)

    @on(Button.Pressed, "#start-random")
    def on_start_random(self) -> None:
        self._select_starting("random")

    @on(Button.Pressed, "#start-red")
    def on_start_red(self) -> None:
        self._select_starting("red")

    @on(Button.Pressed, "#start-blue")
    def on_start_blue(self) -> None:
        self._select_starting("blue")

    @on(Button.Pressed, "#start-btn")
    def on_start_game(self) -> None:
        model = self.query_one("#model-input", Input).value.strip() or "qwen2.5:7b"
        self.app.start_game(
            user_team=self._user_team,
            user_role=self._user_role,
            model=model,
            starting_team_choice=self._starting,
        )


# ── GameOverModal ─────────────────────────────────────────────────────────────

class GameOverModal(ModalScreen):
    """Modal overlay displayed when the game ends."""

    def __init__(self, winner: Team, reason: str) -> None:
        super().__init__()
        self._winner = winner
        self._reason = reason

    def compose(self) -> ComposeResult:
        winner_color = "red" if self._winner == Team.RED else "blue"
        winner_text = f"{self._winner.value.upper()} TEAM WINS!"

        with Vertical(id="game-over-container"):
            yield Static("GAME OVER", id="game-over-title")
            yield Static(winner_text, id="game-over-winner")
            yield Static(self._reason, id="game-over-reason")
            yield Button("Play Again", id="play-again-btn", classes="modal-btn")
            yield Button("Quit", id="quit-btn", classes="modal-btn")

    def on_mount(self) -> None:
        winner_label = self.query_one("#game-over-winner")
        if self._winner == Team.RED:
            winner_label.styles.color = "#FF6666"
        else:
            winner_label.styles.color = "#6666FF"

    @on(Button.Pressed, "#play-again-btn")
    def on_play_again(self) -> None:
        self.app.pop_screen()  # dismiss modal
        self.app.pop_screen()  # dismiss game screen
        self.app.push_screen(SetupScreen())

    @on(Button.Pressed, "#quit-btn")
    def on_quit(self) -> None:
        self.app.exit()


# ── GameScreen ────────────────────────────────────────────────────────────────

class GameScreen(Screen):
    """Main game screen."""

    def __init__(self) -> None:
        super().__init__()
        self._log_index: int = 0
        self._ai_running: bool = False
        self._card_widgets: dict[str, CardWidget] = {}

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # Score bar
        with Horizontal(id="score-bar"):
            yield Static("RED: ?", id="score-red")
            yield Static("Loading...", id="score-turn")
            yield Static("BLUE: ?", id="score-blue")

        # Main area: card grid + sidebar
        with Horizontal(id="main-area"):
            with Container(id="card-area"):
                yield Grid(id="card-grid")

            with Vertical(id="sidebar"):
                yield Static("CODENAMES", id="sidebar-title")
                yield Static("Waiting for clue...", id="clue-display")
                yield Static("", id="turn-label")

                # Spymaster clue input — lives in the sidebar, shown only on user's spy turn
                with Vertical(id="spy-input"):
                    yield Static("Enter your clue:", id="spy-input-label")
                    yield Input(placeholder="One word", id="clue-word", max_length=30)
                    with Horizontal(id="spy-input-row2"):
                        yield Input(placeholder="#", id="clue-number", max_length=2)
                        yield Button("Give Clue", id="submit-clue")

                yield GameLog(id="game-log")
                yield Static("── AI Thinking ──", id="thinking-title")
                yield ThinkingPanel(id="thinking-panel")

        # Action bar — status + guesser controls only (no spymaster input here)
        with Horizontal(id="action-bar"):
            with ContentSwitcher(id="action-switcher", initial="status-area"):
                with Horizontal(id="status-area"):
                    yield Static("", id="status-label")
                with Horizontal(id="guess-controls-area"):
                    yield Button("End Turn / Pass", id="end-turn")
                    yield Static("Click a card to guess", id="guess-instruction")

    # ── Mount ─────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state
        grid = self.query_one("#card-grid", Grid)
        spy_view = self._is_user_spymaster()

        for card in state.cards:
            widget = CardWidget(card, spy_view=spy_view)
            self._card_widgets[card.word.upper()] = widget
            grid.mount(widget)

        self._refresh_board()
        self.advance_game()

    # ── Board / UI refresh ────────────────────────────────────────────────────

    def _is_user_turn(self) -> bool:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state
        if state.current_team != app.user_team:
            return False
        if state.phase == Phase.GIVING_CLUE and app.user_role == Role.SPYMASTER:
            return True
        if state.phase == Phase.GUESSING and app.user_role == Role.GUESSER:
            return True
        return False

    def _is_user_spymaster(self) -> bool:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        return app.user_role == Role.SPYMASTER

    def _refresh_board(self) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state
        spy_view = self._is_user_spymaster()

        # Update cards
        for card in state.cards:
            widget = self._card_widgets.get(card.word.upper())
            if widget:
                widget._card = card
                widget.refresh_display(spy_view)

        # Score bar
        red_rem = state.remaining(Team.RED)
        blue_rem = state.remaining(Team.BLUE)
        self.query_one("#score-red", Static).update(f"RED: {red_rem}")
        self.query_one("#score-blue", Static).update(f"BLUE: {blue_rem}")

        team_name = state.current_team.value.upper()
        if state.phase == Phase.GAME_OVER:
            winner = state.winner.value.upper() if state.winner else "?"
            self.query_one("#score-turn", Static).update(f"── {winner} WINS! ──")
        else:
            self.query_one("#score-turn", Static).update(f"── {team_name}'S TURN ──")

        # Clue display
        clue_label = self.query_one("#clue-display", Static)
        if state.current_clue:
            remaining_guesses = state.current_clue.number + 1 - state.guesses_made
            clue_label.update(
                f"Clue: {state.current_clue.word} × {state.current_clue.number}\n"
                f"Guesses left: {remaining_guesses}"
            )
        else:
            clue_label.update("Waiting for clue...")

        # Turn label
        turn_label = self.query_one("#turn-label", Static)
        if state.phase != Phase.GAME_OVER:
            role_name = "Spymaster" if state.phase == Phase.GIVING_CLUE else "Guesser"
            turn_label.update(f"{team_name} {role_name}")
        else:
            turn_label.update("")

        # Game log: add any new entries
        game_log = self.query_one("#game-log", GameLog)
        while self._log_index < len(state.log):
            entry = state.log[self._log_index]
            game_log.add_entry(entry)
            self._log_index += 1

    # ── Action bar management ─────────────────────────────────────────────────

    def _set_spy_input_visible(self, visible: bool) -> None:
        self.query_one("#spy-input").display = visible

    def _show_user_ui(self) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state

        if state.phase == Phase.GIVING_CLUE and app.user_role == Role.SPYMASTER:
            self._set_spy_input_visible(True)
            self.query_one("#action-switcher", ContentSwitcher).current = "status-area"
            self.query_one("#status-label", Static).update("Your turn — give a clue above")
            for w in self._card_widgets.values():
                w.disabled = True
            try:
                self.query_one("#clue-word", Input).focus()
            except Exception:
                pass
        elif state.phase == Phase.GUESSING and app.user_role == Role.GUESSER:
            self._set_spy_input_visible(False)
            self.query_one("#action-switcher", ContentSwitcher).current = "guess-controls-area"
            for card in state.cards:
                widget = self._card_widgets.get(card.word.upper())
                if widget:
                    widget.disabled = card.revealed

    def _show_thinking_ui(self) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state
        self._set_spy_input_visible(False)
        self.query_one("#action-switcher", ContentSwitcher).current = "status-area"

        team_name = state.current_team.value.upper()
        role_name = "spymaster" if state.phase == Phase.GIVING_CLUE else "guesser"
        self.query_one("#status-label", Static).update(
            f"AI {team_name} {role_name} is thinking..."
        )
        for w in self._card_widgets.values():
            if not w._card.revealed:
                w.disabled = True

    def _set_thinking_text(self, team: Team, text: str) -> None:
        self.query_one("#thinking-panel", ThinkingPanel).set_text(
            team.value.upper(), text
        )

    # ── Game flow ─────────────────────────────────────────────────────────────

    def advance_game(self) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state

        if state.phase == Phase.GAME_OVER:
            # Determine reason
            last_log = state.log[-1] if state.log else ""
            if "ASSASSIN" in last_log.upper():
                reason = "The assassin was revealed!"
            else:
                winner = state.winner
                reason = f"All {winner.value.upper()} words found!" if winner else ""
            self.app.push_screen(GameOverModal(state.winner, reason))
            return

        if self._is_user_turn():
            self._show_user_ui()
        else:
            if not self._ai_running:
                self._ai_running = True
                self._show_thinking_ui()
                self._run_ai_loop()

    @work(exclusive=True)
    async def _run_ai_loop(self) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state

        try:
            while state.phase != Phase.GAME_OVER and not self._is_user_turn():
                if state.phase == Phase.GIVING_CLUE:
                    # AI spymaster gives a clue
                    spymaster = app.spymasters[state.current_team]
                    self.query_one("#status-label", Static).update(
                        f"AI {state.current_team.value.upper()} spymaster thinking..."
                    )
                    clue_word, clue_number = await spymaster.give_clue(state)
                    state.set_clue(clue_word, clue_number)
                    self._refresh_board()
                    await asyncio.sleep(1.5)

                elif state.phase == Phase.GUESSING:
                    # AI guesser makes guesses
                    team = state.current_team
                    guesser = app.guessers[team]
                    self.query_one("#status-label", Static).update(
                        f"AI {team.value.upper()} guesser thinking..."
                    )
                    await asyncio.sleep(0.5)
                    guess, raw = await guesser.make_guess(state)
                    self._set_thinking_text(team, raw)

                    if guess == "PASS":
                        state.pass_turn()
                        self._refresh_board()
                    else:
                        _color, continues = state.pick_card(guess)
                        self._refresh_board()
                        await asyncio.sleep(1.2)

        finally:
            self._ai_running = False
            self._refresh_board()
            self.advance_game()

    # ── User action handlers ──────────────────────────────────────────────────

    def on_card_widget_picked(self, event: CardWidget.Picked) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state

        if state.phase != Phase.GUESSING:
            return
        if not self._is_user_turn():
            return

        _color, continues = state.pick_card(event.word)
        self._refresh_board()

        if state.phase == Phase.GAME_OVER or not continues:
            self.advance_game()
        else:
            # Still guessing - update UI
            self._show_user_ui()

    @on(Button.Pressed, "#submit-clue")
    def on_submit_clue(self) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state

        if state.phase != Phase.GIVING_CLUE or not self._is_user_turn():
            return

        clue_word_input = self.query_one("#clue-word", Input)
        clue_number_input = self.query_one("#clue-number", Input)

        clue_word = clue_word_input.value.strip().upper()
        try:
            clue_number = int(clue_number_input.value.strip())
        except ValueError:
            self.query_one("#status-label", Static).update("Enter a valid number!")
            return

        if not clue_word or not clue_word.isalpha():
            return

        # Check clue word is not on board
        board_words = {c.word.upper() for c in state.cards}
        if clue_word in board_words:
            self.query_one("#clue-display", Static).update(
                f"'{clue_word}' is on the board!\nPick a different word."
            )
            return

        max_guesses = state.remaining(
            Team.RED if state.current_team == Team.RED else Team.BLUE
        )
        clue_number = max(1, min(clue_number, max_guesses))

        state.set_clue(clue_word, clue_number)
        clue_word_input.value = ""
        clue_number_input.value = ""
        self._refresh_board()
        self.advance_game()

    @on(Button.Pressed, "#end-turn")
    def on_end_turn(self) -> None:
        app: CodenamesApp = self.app  # type: ignore[assignment]
        state = app.game_state

        if not self._is_user_turn():
            return

        state.pass_turn()
        self._refresh_board()
        self.advance_game()

    @on(Input.Submitted, "#clue-word")
    def on_clue_word_submitted(self) -> None:
        """Move focus to number field when Enter pressed in word input."""
        try:
            self.query_one("#clue-number", Input).focus()
        except Exception:
            pass

    @on(Input.Submitted, "#clue-number")
    def on_clue_number_submitted(self) -> None:
        """Submit clue when Enter pressed in number field."""
        self.on_submit_clue()


# ── CodenamesApp ──────────────────────────────────────────────────────────────

class CodenamesApp(App):
    CSS_PATH = "codenames.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.game_state: Optional[GameState] = None
        self.user_team: Team = Team.RED
        self.user_role: Role = Role.GUESSER
        self.spymasters: dict[Team, SpymasterAgent] = {}
        self.guessers: dict[Team, GuesserAgent] = {}
        self._words: list[str] = _load_words()

    def on_mount(self) -> None:
        self.push_screen(SetupScreen())

    def start_game(
        self,
        user_team: Team,
        user_role: Role,
        model: str,
        starting_team_choice: str,
    ) -> None:
        self.user_team = user_team
        self.user_role = user_role
        self._loading_screen = LoadingScreen()
        self.push_screen(self._loading_screen)
        self._prepare_game(model, starting_team_choice)

    @work(exclusive=True)
    async def _prepare_game(self, model: str, starting_team_choice: str) -> None:
        loading = self._loading_screen

        loading.update_message(f"Building codenames-spy from {model}...")
        await ensure_models(model)
        loading.update_message("Starting game...")

        if starting_team_choice == "red":
            starting_team = Team.RED
        elif starting_team_choice == "blue":
            starting_team = Team.BLUE
        else:
            starting_team = random.choice([Team.RED, Team.BLUE])

        self.game_state = GameState(self._words, starting_team)
        self.spymasters = {
            Team.RED: SpymasterAgent(Team.RED),
            Team.BLUE: SpymasterAgent(Team.BLUE),
        }
        self.guessers = {
            Team.RED: GuesserAgent(Team.RED),
            Team.BLUE: GuesserAgent(Team.BLUE),
        }

        self.pop_screen()          # remove LoadingScreen
        self.push_screen(GameScreen())
