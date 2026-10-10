"""chesscoach -- a local chess tutor that explains *why*, not just +/-.

Design in one line: the engine thinks, the language model talks, and the
language model is never allowed to invent the numbers.
"""

from .coach import Coaching, coach_move
from .engine import Analyzer, find_stockfish

__all__ = ["Analyzer", "coach_move", "Coaching", "find_stockfish"]
__version__ = "0.1.0"
