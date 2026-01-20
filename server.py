#!/usr/bin/env python3
"""
Websockets Server for Cribbage Host
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional

import websockets
from websockets.exceptions import ConnectionClosedOK

from game import Game

logging.basicConfig(level=logging.INFO)

class CribbageServer:
    def __init__(self, port: int):
        self.port = port
        self.connections: Dict[int, websockets.WebSocketServerProtocol] = {}
        self.game: Optional[Game] = None
        self.next_player_id = 0
        self.discards: Dict[int, List[int]] = {}
        self.plays: List[Dict] = []  # For pegging

    async def handler(self, websocket: websockets.WebSocketServerProtocol):
        player_id = self.next_player_id
        self.next_player_id += 1
        self.connections[player_id] = websocket
        logging.info(f"Player {player_id} connected")

        try:
            await self.send_to_player(player_id, {"type": "welcome", "player_id": player_id})

            async for message in websocket:
                data = json.loads(message)
                await self.handle_message(player_id, data)
        except ConnectionClosedOK:
            logging.info(f"Player {player_id} disconnected normally")
        except Exception as e:
            logging.error(f"Error with player {player_id}: {e}")
        finally:
            if player_id in self.connections:
                del self.connections[player_id]
            # Handle disconnection: pause or allow reconnect
            await self.handle_disconnect(player_id)

    async def handle_message(self, player_id: int, data: dict):
        msg_type = data.get("type")
        if msg_type == "join":
            await self.handle_join(player_id, data)
        elif msg_type == "start_game":
            await self.start_game()
        elif msg_type == "discard":
            await self.handle_discard(player_id, data)
        elif msg_type == "play":
            await self.handle_play(player_id, data)
        # Add more as needed

    async def handle_join(self, player_id: int, data: dict):
        # For now, just acknowledge
        await self.broadcast({"type": "player_joined", "player_id": player_id})

    async def start_game(self):
        if len(self.connections) >= 2:
            self.game = Game(len(self.connections))
            await self.broadcast({"type": "game_started", "num_players": len(self.connections)})
            await self.deal_cards()

    async def deal_cards(self):
        self.game.deal_cards()
        self.game.set_starter()
        for pid, ws in self.connections.items():
            hand = [str(card) for card in self.game.players[pid].hand]
            await self.send_to_player(pid, {"type": "deal", "hand": hand, "starter": str(self.game.starter)})
        await self.broadcast({"type": "turn", "phase": "discard", "player_id": None})  # All discard

    async def handle_discard(self, player_id: int, data: dict):
        indices = data["indices"]
        self.discards[player_id] = indices
        await self.send_to_player(player_id, {"type": "ack", "message": "Discard received"})
        if len(self.discards) == len(self.connections):
            # All discards collected
            self.game.collect_discards(self.discards)
            self.discards = {}  # Reset
            # Send updated hands
            for pid in self.connections:
                hand = [str(card) for card in self.game.players[pid].hand]
                await self.send_to_player(pid, {"type": "hand_update", "hand": hand})
            await self.broadcast({"type": "turn", "phase": "play", "player_id": 0})  # Start with player 0

    async def handle_play(self, player_id: int, data: dict):
        card_index = data["card_index"]
        card, points = self.game.play_card(player_id, card_index)
        self.plays.append({"player_id": player_id, "card": str(card), "points": points})
        await self.broadcast({"type": "played", "player_id": player_id, "card": str(card), "points": points})
        # Send updated hand to player
        hand = [str(c) for c in self.game.players[player_id].hand]
        await self.send_to_player(player_id, {"type": "hand_update", "hand": hand})
        # Check if round over, etc. Placeholder
        next_player = (player_id + 1) % len(self.connections)
        await self.broadcast({"type": "turn", "phase": "play", "player_id": next_player})

    async def handle_disconnect(self, player_id: int):
        # Pause game
        await self.broadcast({"type": "player_disconnected", "player_id": player_id})
        # For reconnection, wait or something, but for now pause

    async def send_to_player(self, player_id: int, message: dict):
        if player_id in self.connections:
            await self.connections[player_id].send(json.dumps(message))

    async def broadcast(self, message: dict):
        msg = json.dumps(message)
        await asyncio.gather(*[ws.send(msg) for ws in self.connections.values()])

async def run_server(port: int):
    server = CribbageServer(port)
    async with websockets.serve(server.handler, "0.0.0.0", port):
        logging.info(f"Server started on port {port}")
        await asyncio.Future()  # Run forever