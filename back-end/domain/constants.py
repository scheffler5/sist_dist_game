from enum import Enum


class GameStatus(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    VOTING = "voting"
    FINISHED = "finished"


FIRST_GUESS_POINTS = 15
OTHER_GUESS_POINTS = 10
SOLO_BONUS_POINTS = 5

OWNER_SOLO_POINTS = 20
OWNER_MULTI_POINTS = 10
OWNER_ALL_PENALTY = -5

SPY_CAUGHT_PENALTY = -5
SPY_CATCH_CHANCE = 0.4

OBJECTS = [
    {"name": "bicicleta",   "emoji": "🚲"},
    {"name": "piano",       "emoji": "🎹"},
    {"name": "telescópio",  "emoji": "🔭"},
    {"name": "guitarra",    "emoji": "🎸"},
    {"name": "foguete",     "emoji": "🚀"},
    {"name": "montanha",    "emoji": "⛰️"},
    {"name": "borboleta",   "emoji": "🦋"},
    {"name": "castelo",     "emoji": "🏰"},
    {"name": "helicóptero", "emoji": "🚁"},
    {"name": "polvo",       "emoji": "🐙"},
    {"name": "girassol",    "emoji": "🌻"},
    {"name": "trompete",    "emoji": "🎺"},
    {"name": "coroa",       "emoji": "👑"},
    {"name": "microscópio", "emoji": "🔬"},
    {"name": "âncora",      "emoji": "⚓"},
    {"name": "dragão",      "emoji": "🐉"},
    {"name": "vulcão",      "emoji": "🌋"},
    {"name": "cacto",       "emoji": "🌵"},
    {"name": "cogumelo",    "emoji": "🍄"},
    {"name": "cristal",     "emoji": "💎"},
    {"name": "farol",       "emoji": "🏯"},
    {"name": "tartaruga",   "emoji": "🐢"},
    {"name": "trovoada",    "emoji": "⛈️"},
    {"name": "harpa",       "emoji": "🎵"},
]
