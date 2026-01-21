#!/usr/bin/env python3
"""
Cribbage Game Logic
"""

import random
from collections import Counter
from itertools import combinations
from typing import List, Dict, Optional, Set

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
        self.pegging_total = 0
        self.pegging_cards = []  # List of card strings for display
        self.last_played_player: Optional[int] = None
        self.players_passed: Set[int] = set()
        self.last_card_bonus_awarded = False
        self.show_hands: Dict[int, List[Card]] = {}
        self.dealer = 0

    def deal_cards(self):
        cards_per_player = 6 if self.num_players == 2 else 5
        for player in self.players:
            player.hand = self.deck.deal(cards_per_player)
        self.last_card_bonus_awarded = False

    def set_starter(self):
        self.starter = self.deck.deal(1)[0]

    def collect_discards(self, discards: Dict[int, List[int]]):
        for pid, indices in discards.items():
            discarded = self.players[pid].discard(indices)
            self.crib.extend(discarded)
        self.capture_show_hands()

    def capture_show_hands(self):
        self.show_hands = {pid: list(player.hand) for pid, player in enumerate(self.players)}

    def can_play_card(self, player_id: int, card_index: int) -> bool:
        if card_index < 0 or card_index >= len(self.players[player_id].hand):
            return False
        card = self.players[player_id].hand[card_index]
        value = self.get_card_value(card)
        return self.pegging_total + value <= 31

    def has_playable_card(self, player_id: int) -> bool:
        return any(self.can_play_card(player_id, idx) for idx in range(len(self.players[player_id].hand)))

    def play_card(self, player_id: int, card_index: int) -> tuple:
        card = self.players[player_id].hand.pop(card_index)
        value = self.get_card_value(card)
        self.pegging_total += value
        self.pegging_cards.append(str(card))  # Append card string
        points = self.calculate_pegging_points()
        was_last_card = all(len(p.hand) == 0 for p in self.players)
        if was_last_card and self.pegging_total != 31 and not self.last_card_bonus_awarded:
            points += 1
            self.last_card_bonus_awarded = True
        self.last_played_player = player_id
        self.players_passed.clear()
        return card, points

    def go(self, player_id: int) -> tuple[Optional[int], bool, bool, bool]:
        self.players_passed.add(player_id)
        active_players = {pid for pid, player in enumerate(self.players) if len(player.hand) > 0}
        if not active_players:
            # Nothing left to play, move to show without awarding an extra point
            self.players_passed.clear()
            return None, True, True, False
        if self.last_played_player is None:
            return None, False, False, False
        if active_players.issubset(self.players_passed):
            total_before_reset = self.pegging_total
            self.pegging_total = 0
            self.pegging_cards = []
            self.players_passed.clear()
            self.last_card_bonus_awarded = False
            award_last_card = total_before_reset != 31 and all(len(p.hand) == 0 for p in self.players)
            return self.last_played_player, True, self.is_pegging_over(), award_last_card
        return None, False, False, False

    def calculate_pegging_points(self) -> int:
        points = 0
        # 15 or 31
        if self.pegging_total == 15 or self.pegging_total == 31:
            points += 2
        # Pairs, etc.
        if len(self.pegging_cards) >= 2:
            last_rank = self.get_card_rank(self.pegging_cards[-1])
            count = 1
            for card_str in reversed(self.pegging_cards[:-1]):
                if self.get_card_rank(card_str) == last_rank:
                    count += 1
                else:
                    break
            if count >= 2:
                points += 2 * (count - 1)
        # Runs
        for length in range(len(self.pegging_cards), 2, -1):
            tail = self.pegging_cards[-length:]
            nums = sorted(self.rank_to_num(self.get_card_rank(card)) for card in tail)
            if len(set(nums)) != length:
                continue
            if nums == list(range(nums[0], nums[0] + length)):
                points += length
                break  # Longest run in tail
        return points

    def rank_to_num(self, rank: str) -> int:
        if rank == 'A': return 1
        if rank.isdigit(): return int(rank)
        return 11 if rank == 'J' else 12 if rank == 'Q' else 13  # K

    def get_card_value(self, card) -> int:
        return VALUES[card.rank]

    def get_card_rank(self, card_str: str) -> str:
        return card_str[:-1]

    def score_show_cards(self, cards: List[Card]) -> int:
        if not cards:
            return 0
        total = 0
        total += self.count_fifteens(cards)
        total += self.count_pairs(cards)
        total += self.count_runs(cards)
        return total

    def count_fifteens(self, cards: List[Card]) -> int:
        values = [VALUES[card.rank] for card in cards]
        count = 0
        for r in range(1, len(values) + 1):
            for combo in combinations(values, r):
                if sum(combo) == 15:
                    count += 1
        return count * 2

    def count_pairs(self, cards: List[Card]) -> int:
        ranks = Counter(card.rank for card in cards)
        count = 0
        for qty in ranks.values():
            if qty >= 2:
                count += (qty * (qty - 1) // 2) * 2
        return count

    def count_runs(self, cards: List[Card]) -> int:
        if len(cards) < 3:
            return 0
        rank_counts = Counter(self.rank_to_num(card.rank) for card in cards)
        sorted_nums = sorted(rank_counts)
        segments = []
        i = 0
        while i < len(sorted_nums):
            j = i
            while j + 1 < len(sorted_nums) and sorted_nums[j + 1] == sorted_nums[j] + 1:
                j += 1
            length = j - i + 1
            if length >= 3:
                segments.append((i, j))
            i = j + 1
        if not segments:
            return 0
        max_length = max(j - i + 1 for i, j in segments)
        score = 0
        for start, end in segments:
            length = end - start + 1
            if length != max_length:
                continue
            multiplier = 1
            for num in sorted_nums[start:end + 1]:
                multiplier *= rank_counts[num]
            score += length * multiplier
        return score

    def score_show_round(self) -> Dict[int, int]:
        if not self.starter:
            return {}
        show_points: Dict[int, int] = {}
        for pid, cards in self.show_hands.items():
            points = self.score_show_cards(cards + [self.starter])
            show_points[pid] = points
            self.players[pid].score += points
        if self.crib:
            crib_points = self.score_show_cards(self.crib + [self.starter])
            owner = self.dealer
            show_points[owner] = show_points.get(owner, 0) + crib_points
            self.players[owner].score += crib_points
        self.crib = []
        self.show_hands = {}
        return show_points

    def get_show_hand_strings(self) -> Dict[int, List[str]]:
        return {pid: [str(card) for card in cards] for pid, cards in self.show_hands.items()}


    def is_pegging_over(self) -> bool:
        return all(len(p.hand) == 0 for p in self.players)

    def next_dealer(self):
        self.current_player = (self.current_player + 1) % self.num_players

    def is_game_over(self) -> bool:
        return any(p.score >= 121 for p in self.players)
