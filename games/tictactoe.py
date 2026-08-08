import random


class TicTacToeGame:

    def __init__(
        self,
        game_id,
        player1_id,
        player1_name,
        player2_id,
        player2_name,
        bet_amount,
    ):
        self.game_id = game_id
        self.player1_id = player1_id  # Challenger
        self.player1_name = player1_name
        self.player2_id = player2_id  # Challenged
        self.player2_name = player2_name
        self.bet_amount = float(bet_amount)

        # 3x3 board stored as flat list of 9 elements
        self.board = ["⬜"] * 9

        # Challenged player (player2) always gets X and moves first
        self.x_player = (player2_id, player2_name)
        self.o_player = (player1_id, player1_name)

        self.turn = "X"  # X always moves first
        self.is_finished = False
        self.winner = None  # None, 'X', 'O', or 'TIE'

    def current_player_id(self):
        return self.x_player[0] if self.turn == "X" else self.o_player[0]

    def current_player_name(self):
        return self.x_player[1] if self.turn == "X" else self.o_player[1]

    def get_payout(self):
        """Calculates winning payout using a 10% house edge (1.90x payout multiplier)."""
        return int(self.bet_amount * 1.90)

    def make_move(self, position, player_id):
        if self.is_finished:
            return False, "Game is already finished."

        if player_id != self.current_player_id():
            return False, "It's not your turn!"

        if self.board[position] != "⬜":
            return False, "Spot already taken!"

        symbol = "❌" if self.turn == "X" else "⭕"
        self.board[position] = symbol

        if self.check_winner(symbol):
            self.is_finished = True
            self.winner = self.turn
            return True, "WIN"
        elif "⬜" not in self.board:
            self.is_finished = True
            self.winner = "TIE"
            return True, "TIE"
        else:
            self.turn = "O" if self.turn == "X" else "X"
            return True, "CONTINUE"

    def check_winner(self, symbol):
        win_conditions = [
            (0, 1, 2),
            (3, 4, 5),
            (6, 7, 8),  # Rows
            (0, 3, 6),
            (1, 4, 7),
            (2, 5, 8),  # Columns
            (0, 4, 8),
            (2, 4, 6),  # Diagonals
        ]
        return any(
            self.board[a] == self.board[b] == self.board[c] == symbol
            for a, b, c in win_conditions
        )
