#!/usr/bin/env python3
"""
Cribbage Game Logic
"""

import random
from typing import List, Dict, Optional

SUITS = ['H', 'D', 'C', 'S']  # Hearts, Diamonds, Clubs, Spades
RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
VALUES = {'A': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 10, 'Q': 10, 'K': 10}

class Card:
    def __init__(self, suit: str, rank: str):
        self.suit = suit
        self.rank = rank
        self.value = VALUES[rank]

    def __str__(self):
        return f"{self.rank}{self.suit}"

    def __repr__(self):
        return self.__str__()

class Deck:
    def __init__(self):
        self.cards = [Card(suit, rank) for suit in SUITS for rank in RANKS]
        random.shuffle(self.cards)

    def deal(self, num: int) -> List[Card]:
        return [self.cards.pop() for _ in range(num)]

class Player:
    def __init__(self, id: int, name: str = None):
        self.id = id
        self.name = name or f"Player {id}"
        self.hand: List[Card] = []
        self.score = 0

    def discard(self, indices: List[int]) -> List[Card]:
        discarded = [self.hand[i] for i in sorted(indices, reverse=True)]
        for i in sorted(indices, reverse=True):
            del self.hand[i]
        return discarded

class Game:
    def __init__(self, num_players: int):
        self.num_players = num_players
        self.players = [Player(i) for i in range(num_players)]
        self.deck = Deck()
        self.crib: List[Card] = []
        self.starter: Optional[Card] = None
        self.current_player = 0
        self.phase = 'deal'  # deal, discard, play, show

    def deal_cards(self):
        cards_per_player = 6 if self.num_players == 2 else 5
        for player in self.players:
            player.hand = self.deck.deal(cards_per_player)

    def set_starter(self):
        self.starter = self.deck.deal(1)[0]

    def collect_discards(self, discards: Dict[int, List[int]]):
        for pid, indices in discards.items():
            discarded = self.players[pid].discard(indices)
            self.crib.extend(discarded)

    def play_card(self, player_id: int, card_index: int) -> tuple[Card, int]:
        # Simple play, return points if any
        card = self.players[player_id].hand[card_index]
        # For now, just remove card, no pegging logic yet
        del self.players[player_id].hand[card_index]
        return card, 0  # Placeholder

    def calculate_score(self, hand: List[Card], is_crib: bool = False) -> int:
        # Placeholder for scoring logic
        return 0

    def show_hands(self):
        for player in self.players:
            score = self.calculate_score(player.hand + [self.starter])
            player.score += score
        # Crib score
        crib_score = self.calculate_score(self.crib + [self.starter], is_crib=True)
        self.players[self.current_player].score += crib_score  # Dealer

    def next_dealer(self):
        self.current_player = (self.current_player + 1) % self.num_players

    def is_game_over(self) -> bool:
        return any(p.score >= 121 for p in self.players)