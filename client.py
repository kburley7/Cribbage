#!/usr/bin/env python3
"""
Websockets Client for Cribbage Joiner
"""

import asyncio
import json
import logging
from typing import Optional, List, Dict

import websockets
from websockets.exceptions import ConnectionClosedOK
import aioconsole
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logging.basicConfig(level=logging.INFO)
console = Console()

class CribbageClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.player_id: Optional[int] = None
        self.hand: List[str] = []
        self.scores: Dict[int, int] = {}
        self.phase = 'waiting'  # waiting, discard, play, show
        self.reconnect_attempts = 0
        self.max_attempts = 3
        self.timeout = 10
        self.current_turn_player = None  # Track from "turn" messages
        self.pegging_total = 0
        self.pegging_cards = []
        self.starter = None
        self._last_phase_displayed: Optional[str] = None

    async def connect(self):
        uri = f"ws://{self.host}:{self.port}"
        while self.reconnect_attempts < self.max_attempts:
            try:
                self.websocket = await asyncio.wait_for(websockets.connect(uri), timeout=self.timeout)
                self.reconnect_attempts = 0  # Reset on success
                logging.info("Connected to server")
                return True
            except Exception as e:
                self.reconnect_attempts += 1
                logging.warning(f"Connection attempt {self.reconnect_attempts} failed: {e}")
                if self.reconnect_attempts < self.max_attempts:
                    await asyncio.sleep(self.timeout)
        return False

    async def run(self):
        if not await self.connect():
            console.print("Failed to connect after max attempts")
            return

        # Start listening and input tasks
        listen_task = asyncio.create_task(self.listen())
        input_task = asyncio.create_task(self.handle_input())

        await asyncio.gather(listen_task, input_task)

    async def listen(self):
        try:
            async for message in self.websocket:
                data = json.loads(message)
                await self.handle_message(data)
        except ConnectionClosedOK:
            logging.info("Connection closed")
        except Exception as e:
            logging.error(f"Listen error: {e}")

    async def handle_message(self, data: dict):
        msg_type = data.get("type")
        if msg_type == "welcome":
            self.player_id = data["player_id"]
            console.print(f"Connected as Player {self.player_id}")
        elif msg_type == "player_joined":
            console.print(f"Player {data['player_id']} joined")
        elif msg_type == "game_started":
            console.print("Game started!")
        elif msg_type == "round_started":
            dealer = data.get("dealer")
            console.print(data.get("message", "A new round is starting."))
            if dealer is not None:
                console.print(f"Dealer for this round: Player {dealer}")
            self.display_instructions(force=True)
        elif msg_type == "deal":
            self.hand = data["hand"]
            # Store starter but don't display yet
            self.starter = data.get("starter")
            self.phase = 'discard'
            self.display_hand()
            self.display_instructions()
        elif msg_type == "starter_revealed":
            self.starter = data["starter"]
            self.display_starter()
        elif msg_type == "turn":
            self.phase = data["phase"]
            self.current_turn_player = data["player_id"]
            if data["player_id"] == self.player_id or data["player_id"] is None:
                console.print(f"Your turn: {self.phase}")
            else:
                console.print(f"Player {data['player_id']}'s turn: {self.phase}")
            if data.get("message"):
                console.print(data["message"])
            self.display_instructions()
        elif msg_type == "played":
            self.pegging_total = data["total"]
            self.pegging_cards = data["pegging_cards"]
            console.print(f"Player {data['player_id']} played {data['card']}, scored {data['points']} points.")
            self.display_pegging()
        elif msg_type == "go":
            if "points" in data:
                console.print(f"Player {data['player_id']} said go, Player {(data['player_id'] + 1) % 4} scored {data['points']} points.")
            else:
                console.print(data.get("message", f"Player {data['player_id']} said go."))
            self.display_instructions()
        elif msg_type == "hand_update":
            self.hand = data["hand"]
            self.display_hand()
        elif msg_type == "ack":
            console.print(data["message"])
        elif msg_type == "scores":
            raw_scores = data.get("scores", {})
            self.scores = {int(pid): score for pid, score in raw_scores.items()}
            self.display_scores()
        elif msg_type == "pegging_round_end":
            console.print(f"Pegging round ended. Player {data['winner']} scores 1. {data.get('message', '')}")
            self.display_scores()
        elif msg_type == "show_results":
            console.print(Panel.fit(f"Dealer: Player {data.get('dealer')}", title="Show Round Complete"))
            show_points = data.get("show_points") or {}
            for pid, pts in show_points.items():
                console.print(f"Player {pid} scored {pts} from the show.")
            self.display_scores()
        elif msg_type == "show_hand":
            hand_cards = data.get("hand", [])
            if hand_cards:
                self.display_hand(hand_cards, title="Show Hand")
            else:
                console.print("Show hand empty.")
            crib = data.get("crib", [])
            if crib:
                console.print(f"Crib: {', '.join(crib)}")
            if data.get("starter"):
                console.print(f"Starter: {data['starter']}")
        elif msg_type == "player_disconnected":
            console.print(f"Player {data['player_id']} disconnected. Game paused.")
        elif msg_type == "pegging_reset":
            self.pegging_total = 0
            self.pegging_cards = []
            console.print(data["message"])
            self.display_pegging()

    async def handle_input(self):
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(None, input, "> ")
                parts = user_input.strip().split()
                if not parts:
                    continue
                cmd = parts[0].lower()
                if cmd == "help":
                    self.display_instructions(force=True)
                elif cmd == "hand":
                    self.display_hand()
                elif cmd == "start" and self.phase == "waiting":
                    await self.send({"type": "start"})
                elif cmd == "discard" and self.phase == "discard":
                    if len(parts) == 3:
                        indices = [int(parts[1]), int(parts[2])]
                        await self.send({"type": "discard", "indices": indices})
                    else:
                        console.print("Invalid discard command. Use 'discard <index1> <index2>'")
                elif cmd == "play" and self.phase == "play" and self.player_id == self.current_turn_player:
                    if len(parts) == 2:
                        try:
                            index = int(parts[1])
                            await self.send({"type": "play", "card_index": index})
                        except ValueError:
                            console.print("Invalid index.")
                    else:
                        console.print("Usage: play <index>")
                elif cmd == "go" and self.phase == "play" and self.player_id == self.current_turn_player:
                    await self.send({"type": "go"})
                else:
                    console.print("Invalid command or not your turn.")
            except Exception as e:
                logging.error(f"Input error: {e}")

    async def send(self, message: dict):
        if self.websocket:
            await self.websocket.send(json.dumps(message))

    def get_card_ascii(self, card_str: str) -> str:
        """Generate simple ASCII art for a playing card."""
        rank = card_str[:-1]  # e.g., "10" or "A"
        suit = card_str[-1]   # e.g., "H"
        suit_symbols = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
        suit_symbol = suit_symbols.get(suit, "?")
        
        # Simple 3-line card
        return f"""+-----+
|{rank:<2}  |
|  {suit_symbol} |
|  {rank:>2}|
+-----+"""

    def display_hand(self, cards: Optional[List[str]] = None, title: str = "Your Hand"):
        table = Table(title=title)
        table.add_column("Index", justify="center")
        table.add_column("Card", justify="center")
        table.add_column("Value", justify="center")
        table.add_column("Graphic", justify="left")
        cards_to_display = cards if cards is not None else self.hand
        for i, card_str in enumerate(cards_to_display):
            if card_str[0].isdigit():
                if card_str[1].isdigit():  # 10
                    value = 10
                else:
                    value = int(card_str[0])
            else:
                value = 10
            graphic = self.get_card_ascii(card_str)
            table.add_row(str(i), card_str, str(value), graphic)
        console.print(table)

    def display_scores(self):
        if not self.scores:
            return
        table = Table(title="Scores")
        table.add_column("Player", justify="center")
        table.add_column("Score", justify="center")
        for pid in sorted(self.scores):
            table.add_row(f"Player {pid}", str(self.scores[pid]))
        console.print(table)

    def display_instructions(self, force: bool = False):
        instructions = {
            'waiting': "Waiting for game to start. Type 'start' to begin if host.",
            'discard': "Discard 2 cards to crib. Type 'discard <index1> <index2>' (e.g., discard 0 1).",
            'play': "Play a card. Type 'play <index>' (e.g., play 0).",
            'show': "Show your hand. Scoring will be calculated automatically."
        }
        if not force and self.phase == self._last_phase_displayed:
            return
        console.print(Panel.fit(instructions.get(self.phase, "Unknown phase"), title="Instructions"))
        self._last_phase_displayed = self.phase

    def display_starter(self):
        if self.starter:
            graphic = self.get_card_ascii(self.starter)
            console.print(Panel.fit(f"Starter Card:\n{graphic}", title="Starter"))

    def display_pegging(self):
        if self.pegging_cards:
            console.print(f"Pegging Total: {self.pegging_total}")
            table = Table(title="Pegging Sequence")
            table.add_column("Order", justify="center")
            table.add_column("Card", justify="center")
            for i, card in enumerate(self.pegging_cards):
                table.add_row(str(i+1), card)
            console.print(table)
        else:
            console.print("Pegging Total: 0 (No cards played yet)")

async def run_client(host: str, port: int):
    client = CribbageClient(host, port)
    await client.run()
