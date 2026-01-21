#!/usr/bin/env python3
"""
Websockets Server for Cribbage Host
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional

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
        self.current_player = 0  # Track whose turn it is
        self._last_scores: Dict[int, int] = {}

    async def broadcast_scores(self):
        if not self.game:
            return
        scores = {pid: self.game.players[pid].score for pid in self.connections}
        if scores != self._last_scores:
            self._last_scores = scores.copy()
            await self.broadcast({"type": "scores", "scores": scores})

    def get_next_active_player(self, start: Optional[int], include_start: bool = False) -> Optional[int]:
        if not self.game or not self.connections:
            return None
        player_ids = sorted(self.connections.keys())
        if not player_ids:
            return None
        if start is None or start not in player_ids:
            index = 0
        else:
            index = player_ids.index(start)
        offsets = range(len(player_ids)) if include_start else range(1, len(player_ids) + 1)
        for offset in offsets:
            pid = player_ids[(index + offset) % len(player_ids)]
            if len(self.game.players[pid].hand) > 0:
                return pid
        return None

    async def broadcast_show_hands(self):
        if not self.game:
            return
        show_hands = self.game.get_show_hand_strings()
        starter = str(self.game.starter) if self.game.starter else None
        crib = [str(card) for card in self.game.crib]
        dealer = self.game.dealer
        for pid in self.connections:
            message = {"type": "show_hand", "hand": show_hands.get(pid, []), "starter": starter, "dealer": dealer}
            if pid == dealer:
                message["crib"] = crib
            await self.send_to_player(pid, message)

    async def trigger_show_phase(self):
        if not self.game:
            return
        self.current_player = None
        await self.broadcast({"type": "turn", "phase": "show", "player_id": None, "message": "Show scoring round begins."})
        await self.broadcast_show_hands()
        show_points = self.game.score_show_round()
        await self.broadcast({"type": "show_results", "show_points": show_points, "dealer": self.game.dealer})
        await self.broadcast_scores()

    async def maybe_auto_go(self):
        if not self.game or self.current_player is None:
            return
        player_id = self.current_player
        if len(self.game.players[player_id].hand) == 0:
            return
        if self.game.has_playable_card(player_id):
            return
        await self.handle_go(player_id, auto=True)

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
        elif msg_type == "start":
            await self.start_game()
        elif msg_type == "discard":
            await self.handle_discard(player_id, data)
        elif msg_type == "play":
            await self.handle_play(player_id, data)
        elif msg_type == "go":
            await self.handle_go(player_id)

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
        await self.broadcast_scores()

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
            # Reveal starter after all discards
            await self.broadcast({"type": "starter_revealed", "starter": str(self.game.starter)})
            self.current_player = 0  # Start pegging with player 0
            self.game.capture_show_hands()
            await self.broadcast({"type": "turn", "phase": "play", "player_id": self.current_player})
            await self.maybe_auto_go()

    async def handle_play(self, player_id: int, data: dict):
        if player_id != self.current_player:
            await self.send_to_player(player_id, {"type": "ack", "message": "Not your turn."})
            return
        card_index = data["card_index"]
        if not self.game.can_play_card(player_id, card_index):
            await self.send_to_player(player_id, {"type": "ack", "message": "Cannot play that card (exceeds 31)."})
            return
        card, points = self.game.play_card(player_id, card_index)
        self.game.players[player_id].score += points
        await self.broadcast({"type": "played", "player_id": player_id, "card": str(card), "points": points, "total": self.game.pegging_total, "pegging_cards": self.game.pegging_cards})
        # Send updated hand
        hand = [str(c) for c in self.game.players[player_id].hand]
        await self.send_to_player(player_id, {"type": "hand_update", "hand": hand})
        await self.broadcast_scores()
        # Check if pegging over
        if self.game.is_pegging_over():
            await self.trigger_show_phase()
            return
        next_player = self.get_next_active_player(player_id)
        if next_player is None:
            await self.trigger_show_phase()
            return
        else:
            self.current_player = next_player
            await self.broadcast({"type": "turn", "phase": "play", "player_id": self.current_player})
            await self.maybe_auto_go()

    async def handle_go(self, player_id: int, auto: bool = False):
        if player_id != self.current_player:
            await self.send_to_player(player_id, {"type": "ack", "message": "Not your turn."})
            return
        scorer, round_over, show_phase, _ = self.game.go(player_id)
        if scorer is not None:
            message = "All players went; new pegging round begins."
            await self.broadcast({"type": "pegging_round_end", "winner": scorer, "message": message})
            await self.broadcast_scores()
            if show_phase:
                await self.trigger_show_phase()
                return
            next_start = self.get_next_active_player(self.game.last_played_player, include_start=True)
            if next_start is None:
                await self.trigger_show_phase()
                return
            self.current_player = next_start
            await self.broadcast({"type": "turn", "phase": "play", "player_id": self.current_player, "message": f"New pegging round starts with Player {self.current_player}."})
            await self.maybe_auto_go()
            return
        if round_over and show_phase:
            await self.trigger_show_phase()
            return
        message = "Automatic go (no playable cards)." if auto else "Player cannot play."
        await self.broadcast({"type": "go", "player_id": player_id, "message": message})
        next_player = self.get_next_active_player(player_id)
        if next_player is None:
            await self.trigger_show_phase()
            return
        self.current_player = next_player
        await self.broadcast({"type": "turn", "phase": "play", "player_id": self.current_player})
        await self.maybe_auto_go()

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
