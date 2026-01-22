#!/usr/bin/env python3
"""
Websockets Server for Cribbage Host
"""

import asyncio
import json
import logging
import random
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
        self.plays: List[Dict] = []
        self.current_player = 0
        self._last_scores: Dict[int, int] = {}
        self.game_over = False

    async def broadcast_scores(self):
        if not self.game:
            return
        scores = {pid: self.game.players[pid].score for pid in self.connections}
        if scores != self._last_scores:
            self._last_scores = scores.copy()
            await self.broadcast({"type": "scores", "scores": scores})

    async def start_round(self, dealer: Optional[int] = None):
        if not self.game or self.game_over:
            return
        self.game.prepare_round(dealer)
        self.discards = {}
        self.game.deal_cards()
        self.game.set_starter()
        for pid, ws in self.connections.items():
            hand = [str(card) for card in self.game.players[pid].hand]
            await self.send_to_player(pid, {"type": "deal", "hand": hand, "starter": str(self.game.starter)})
        await self.broadcast({
            "type": "round_started",
            "dealer": self.game.dealer,
            "message": f"New round starting. Player {self.game.dealer} is the dealer."
        })
        self.current_player = self.game.current_player
        await self.broadcast({"type": "turn", "phase": "discard", "player_id": None})
        await self.broadcast_scores()

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
        await self.finish_show_round()

    async def maybe_auto_go(self):
        if not self.game or self.current_player is None or self.game_over:
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
            await self.handle_disconnect(player_id)

    async def handle_message(self, player_id: int, data: dict):
        if self.game_over:
            await self.send_to_player(player_id, {"type": "ack", "message": "Game has already ended."})
            return
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
        await self.broadcast({"type": "player_joined", "player_id": player_id})

    async def start_game(self):
        if len(self.connections) >= 2:
            self.game = Game(len(self.connections))
            self.game_over = False
            await self.broadcast({"type": "game_started", "num_players": len(self.connections)})
            await self.start_round()

    async def handle_discard(self, player_id: int, data: dict):
        if not self.game:
            return
        indices = data["indices"]
        self.discards[player_id] = indices
        await self.send_to_player(player_id, {"type": "ack", "message": "Discard received"})
        if len(self.discards) == len(self.connections):
            self.game.collect_discards(self.discards)
            self.discards = {}
            for pid in self.connections:
                hand = [str(card) for card in self.game.players[pid].hand]
                await self.send_to_player(pid, {"type": "hand_update", "hand": hand})
            await self.broadcast({"type": "starter_revealed", "starter": str(self.game.starter)})
            self.game.capture_show_hands()
            self.current_player = self.game.current_player
            await self.broadcast({"type": "turn", "phase": "play", "player_id": self.current_player})
            await self.maybe_auto_go()

    def get_winner(self) -> Optional[int]:
        if not self.game:
            return None
        finalists = [p for p in self.game.players if p.score >= 121]
        if not finalists:
            return None
        max_score = max(p.score for p in finalists)
        leaders = [p.id for p in finalists if p.score == max_score]
        if self.game.dealer in leaders:
            return self.game.dealer
        return sorted(leaders)[0]

    async def end_game(self, winner_id: int, reason: str):
        if self.game_over:
            return
        self.game_over = True
        self.current_player = None
        await self.broadcast({"type": "game_over", "winner": winner_id, "reason": reason})
        await self.broadcast_scores()

    async def end_game_if_needed(self, reason: str) -> bool:
        winner = self.get_winner()
        if winner is not None:
            await self.end_game(winner, reason)
            return True
        return False

    async def finish_show_round(self):
        if await self.end_game_if_needed("Player reached 121 during the show round."):
            return
        next_dealer = (self.game.dealer + 1) % self.game.num_players
        await self.start_round(next_dealer)

    async def handle_play(self, player_id: int, data: dict):
        if self.game_over or not self.game:
            return
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
        hand = [str(c) for c in self.game.players[player_id].hand]
        await self.send_to_player(player_id, {"type": "hand_update", "hand": hand})
        await self.broadcast_scores()
        if await self.end_game_if_needed("Player reached 121 during pegging."):
            return
        if self.game.is_pegging_over():
            await self.trigger_show_phase()
            return
        next_player = self.get_next_active_player(player_id)
        if next_player is None:
            await self.trigger_show_phase()
            return
        self.current_player = next_player
        await self.broadcast({"type": "turn", "phase": "play", "player_id": self.current_player})
        await self.maybe_auto_go()

    async def handle_go(self, player_id: int, auto: bool = False):
        if self.game_over or not self.game:
            return
        if player_id != self.current_player:
            await self.send_to_player(player_id, {"type": "ack", "message": "Not your turn."})
            return
        scorer, points_awarded, round_over, show_phase = self.game.go(player_id)
        if scorer is not None:
            if points_awarded > 0:
                self.game.players[scorer].score += points_awarded
            message = "All players went; new pegging round begins."
            if points_awarded > 0:
                message = f"Pegging round ended. Player {scorer} scores {points_awarded}. {message}"
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
        await self.broadcast({"type": "player_disconnected", "player_id": player_id})

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
        await asyncio.Future()
