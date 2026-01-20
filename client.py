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
            console.print(f"Joined as Player {self.player_id}")
        elif msg_type == "game_started":
            self.phase = 'discard'
            console.print("Game started! Discard phase.")
            self.display_instructions()
        elif msg_type == "deal":
            self.hand = data["hand"]
            starter = data["starter"]
            self.phase = 'discard'
            self.display_hand()
            console.print(f"Starter: {starter}")
            self.display_instructions()
        elif msg_type == "player_disconnected":
            console.print(f"Player {data['player_id']} disconnected. Game paused.")
        elif msg_type == "turn":
            self.phase = data["phase"]
            turn_player = data["player_id"]
            if turn_player == self.player_id:
                console.print(f"Your turn: {self.phase} phase")
                self.display_instructions()
            else:
                console.print(f"Player {turn_player}'s turn: {self.phase} phase")
        elif msg_type == "hand_update":
            self.hand = data["hand"]
            self.display_hand()
        elif msg_type == "played":
            console.print(f"Player {data['player_id']} played {data['card']}, scored {data['points']} points")
        elif msg_type == "ack":
            console.print(data["message"])

    async def handle_input(self):
        while True:
            try:
                command = await aioconsole.ainput("Enter command (type 'help' for options): ")
                if command == "help":
                    self.display_instructions()
                elif command.startswith("discard"):
                    if self.phase != 'discard':
                        console.print("Not in discard phase.")
                        continue
                    parts = command.split()
                    if len(parts) == 3:
                        indices = [int(parts[1]), int(parts[2])]
                        await self.send({"type": "discard", "indices": indices})
                    else:
                        console.print("Invalid discard command. Use 'discard <index1> <index2>'")
                elif command.startswith("play"):
                    if self.phase != 'play':
                        console.print("Not in play phase.")
                        continue
                    parts = command.split()
                    if len(parts) == 2:
                        card_index = int(parts[1])
                        await self.send({"type": "play", "card_index": card_index})
                    else:
                        console.print("Invalid play command. Use 'play <index>'")
                elif command == "start":
                    await self.send({"type": "start_game"})
                else:
                    console.print("Unknown command. Type 'help' for options.")
            except Exception as e:
                logging.error(f"Input error: {e}")

    async def send(self, message: dict):
        if self.websocket:
            await self.websocket.send(json.dumps(message))

    def display_hand(self):
        table = Table(title="Your Hand")
        table.add_column("Index", justify="center")
        table.add_column("Card", justify="center")
        table.add_column("Value", justify="center")
        for i, card_str in enumerate(self.hand):
            # Parse card to get value, but since hand is list of str, need to parse
            # For simplicity, assume format like "10H", value is int of first part
            if card_str[0].isdigit():
                if card_str[1].isdigit():  # 10
                    value = 10
                else:
                    value = int(card_str[0])
            else:
                value = 10  # Face cards
            table.add_row(str(i), card_str, str(value))
        console.print(table)

    def display_instructions(self):
        instructions = {
            'waiting': "Waiting for game to start. Type 'start' to begin if host.",
            'discard': "Discard 2 cards to crib. Type 'discard <index1> <index2>' (e.g., discard 0 1).",
            'play': "Play a card. Type 'play <index>' (e.g., play 0).",
            'show': "Show your hand. Scoring will be calculated automatically."
        }
        console.print(Panel.fit(instructions.get(self.phase, "Unknown phase"), title="Instructions"))

async def run_client(host: str, port: int):
    client = CribbageClient(host, port)
    await client.run()