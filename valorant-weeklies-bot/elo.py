"""
Team-based Elo rating math, plus a small brute-force balancer for splitting
a pool of players into two 5-a-side teams with the closest possible average
rating (fine for the small headcounts a weekly pickup night has -- up to
~16 players is instant, no need for anything fancier).
"""

from itertools import combinations

K_FACTOR = 32
DEFAULT_ELO = 1000.0


def expected_score(team_elo: float, opponent_elo: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent_elo - team_elo) / 400))


def update_team_elos(
    team1_elos: dict[str, float],
    team2_elos: dict[str, float],
    winner: str,  # 'team1' | 'team2' | 'draw'
) -> dict[str, tuple[float, float]]:
    """
    Returns {discord_id: (elo_before, elo_after)} for every player in both
    teams. Each team's average rating is used to compute the expected
    result, and the resulting delta is applied equally to every player on
    that team. Simple and predictable -- easy to explain to players, which
    matters more than a fancier per-player-performance-weighted formula for
    a casual weekly ladder.
    """
    avg1 = sum(team1_elos.values()) / len(team1_elos)
    avg2 = sum(team2_elos.values()) / len(team2_elos)

    exp1 = expected_score(avg1, avg2)
    exp2 = expected_score(avg2, avg1)

    if winner == "team1":
        actual1, actual2 = 1.0, 0.0
    elif winner == "team2":
        actual1, actual2 = 0.0, 1.0
    else:  # draw
        actual1, actual2 = 0.5, 0.5

    delta1 = K_FACTOR * (actual1 - exp1)
    delta2 = K_FACTOR * (actual2 - exp2)

    updates: dict[str, tuple[float, float]] = {}
    for pid, elo in team1_elos.items():
        updates[pid] = (elo, elo + delta1)
    for pid, elo in team2_elos.items():
        updates[pid] = (elo, elo + delta2)
    return updates


def balance_teams(players: dict[str, float]) -> tuple[list[str], list[str]]:
    """
    players: {discord_id: elo}
    Splits into two teams (as close to even headcount as possible; exactly
    even if the player count is even) minimizing the difference between
    team average Elo. Brute force over all splits -- trivial at pickup-night
    scale (<= ~16 players).
    """
    ids = list(players.keys())
    n = len(ids)
    if n < 2:
        raise ValueError("Need at least 2 players to balance teams")

    half = n // 2
    best_split = None
    best_diff = float("inf")

    # try both floor and ceil team sizes when n is odd
    sizes = {half} if n % 2 == 0 else {half, half + 1}

    for size in sizes:
        for combo in combinations(ids, size):
            team1 = set(combo)
            team2 = set(ids) - team1
            if not team2:
                continue
            avg1 = sum(players[p] for p in team1) / len(team1)
            avg2 = sum(players[p] for p in team2) / len(team2)
            diff = abs(avg1 - avg2)
            if diff < best_diff:
                best_diff = diff
                best_split = (list(team1), list(team2))

    return best_split
