#!/usr/bin/env python3
# sus_scanner.py
"""
Chess.com Daily suspicious-activity scanner with Tournament vs Non-Tournament comparison,
now using Elo-based gain/loss ratio instead of raw win rates for core scoring.

Use as a module:
    from sus_scanner import SusScanner
    scanner = SusScanner(lookback_months=3)
    results = scanner.analyze_usernames_file("usernames.txt")
    scanner.print_table(results)
    scanner.write_csv("out.csv", results)

Or as a CLI:
    python sus_scanner.py usernames.txt --lookback-months 3 --csv out.csv
"""

from __future__ import annotations
import argparse
import csv
import datetime as dt
import math
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import requests


# --------------------------- Data Models ---------------------------

@dataclass
class GameSummary:
    result: str
    is_win: bool
    is_loss: bool
    is_draw: bool
    my_rating: Optional[int]
    opp_rating: Optional[int]
    plies: Optional[int]
    end_reason: str
    is_rated: bool
    from_tournament: bool
    end_time: Optional[int]


@dataclass
class UserMetrics:
    username: str

    # Lifetime (over fetched window) — rated daily only
    lifetime_games: int = 0
    lifetime_wins: int = 0
    lifetime_draws: int = 0
    lifetime_losses: int = 0

    # “Recent” == same fetched window
    recent_games: int = 0
    recent_wins: int = 0
    recent_draws: int = 0
    recent_losses: int = 0

    # Streaks (all daily, rated/ unrated)
    win_streak: int = 0
    max_win_streak: int = 0

    # Other signals (rated daily)
    upset_wins: int = 0
    short_win_rate: float = 0.0
    timeout_win_ratio: float = 0.0

    # Tournament vs non-tournament (rated daily)
    tourn_games: int = 0
    tourn_wins: int = 0
    tourn_draws: int = 0
    tourn_losses: int = 0
    non_tourn_games: int = 0
    non_tourn_wins: int = 0
    non_tourn_draws: int = 0
    non_tourn_losses: int = 0
    tourn_win_rate: float = 0.0
    non_tourn_win_rate: float = 0.0
    wr_gap: float = 0.0  # tournament WR minus non-tournament WR (legacy display)

    # --- Elo-based accounting ---
    elo_gain: float = 0.0         # sum(max(0, actual - expected))
    elo_loss: float = 0.0         # sum(max(0, expected - actual))
    elo_ratio: float = 0.0        # elo_gain / max(elo_loss, eps)

    tourn_elo_gain: float = 0.0
    tourn_elo_loss: float = 0.0
    tourn_elo_ratio: float = 0.0

    non_tourn_elo_gain: float = 0.0
    non_tourn_elo_loss: float = 0.0
    non_tourn_elo_ratio: float = 0.0

    elo_ratio_gap: float = 0.0    # tournament elo_ratio minus non_tourn_elo_ratio

    suspicion_score: float = 0.0
    reasons: List[str] = field(default_factory=list)


# --------------------------- Scanner Class ---------------------------

class SusScanner:
    """
    Suspicion scanner for Chess.com Daily games.

    Core change: scores are driven by Elo overperformance ratio (gain vs loss)
    and the gap between tournament and non-tournament Elo ratios.
    """

    API_BASE = "https://api.chess.com/pub/player"

    def __init__(
        self,
        *,
        user_agent: str = "GrandTourneys Suspicion Scanner (+contact: example@example.com)",
        lookback_months: int = 2,
        min_lifetime_games: int = 30,
        # kept for display context only
        high_win_rate: float = 0.80,
        recent_min_games: int = 15,
        spike_delta: float = 0.20,
        streak_suspect: int = 8,
        rating_upset_margin: int = 250,
        short_game_plies: int = 40,
        short_win_rate: float = 0.70,
        finish_timeout_ratio: float = 0.50,
        tourn_min_games: int = 15,
        non_tourn_min_games: int = 15,
        wr_gap_suspect: float = 0.25,
        request_timeout: int = 20,
        # --- Elo thresholds ---
        min_games_for_elo: int = 20,
        high_elo_ratio: float = 2.0,
        elo_ratio_gap_suspect: float = 1.0,
    ):
        self.lookback_months = lookback_months

        # thresholds
        self.min_lifetime_games = min_lifetime_games
        self.high_win_rate = high_win_rate
        self.recent_min_games = recent_min_games
        self.spike_delta = spike_delta
        self.streak_suspect = streak_suspect
        self.rating_upset_margin = rating_upset_margin
        self.short_game_plies = short_game_plies
        self.short_win_rate_th = short_win_rate
        self.finish_timeout_ratio_th = finish_timeout_ratio
        self.tourn_min_games = tourn_min_games
        self.non_tourn_min_games = non_tourn_min_games
        self.wr_gap_suspect = wr_gap_suspect

        self.min_games_for_elo = min_games_for_elo
        self.high_elo_ratio = high_elo_ratio
        self.elo_ratio_gap_suspect = elo_ratio_gap_suspect

        # HTTP
        self.request_timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    # --------------------- Public API ---------------------

    def analyze_usernames_file(self, path: str) -> List[UserMetrics]:
        with open(path, "r", encoding="utf-8") as f:
            usernames = [ln.strip().lower() for ln in f if ln.strip()]
        return self.analyze_usernames(usernames)

    def analyze_usernames(self, usernames: List[str]) -> List[UserMetrics]:
        results: List[UserMetrics] = []
        for u in usernames:
            try:
                results.append(self.analyze_user(u))
            except Exception as e:
                print(f"[warn] {u}: {e}")
        results.sort(key=lambda m: m.suspicion_score, reverse=True)
        return results

    def analyze_user(self, username: str) -> UserMetrics:
        games = self._fetch_daily_games(username, self.lookback_months)
        m = UserMetrics(username=username)
        if not games:
            return m

        rated = [g for g in games if g.is_rated]

        # Lifetime/Recent over fetched window
        m.lifetime_games = len(rated)
        m.lifetime_wins = sum(g.is_win for g in rated)
        m.lifetime_draws = sum(g.is_draw for g in rated)
        m.lifetime_losses = sum(g.is_loss for g in rated)

        m.recent_games = m.lifetime_games
        m.recent_wins = m.lifetime_wins
        m.recent_draws = m.lifetime_draws
        m.recent_losses = m.lifetime_losses

        # Streaks (all daily)
        m.win_streak, m.max_win_streak = self._rolling_win_streak(games)

        # Upset wins
        for g in rated:
            if g.is_win and g.my_rating and g.opp_rating:
                if g.opp_rating - g.my_rating >= self.rating_upset_margin:
                    m.upset_wins += 1

        # Short wins & timeoutish ratio
        win_games = [g for g in rated if g.is_win]
        short_wins = [g for g in win_games if (g.plies or 10**9) <= self.short_game_plies]
        m.short_win_rate = self._ratio(len(short_wins), max(1, len(win_games)))
        timeoutish = [g for g in win_games if ("timeout" in g.end_reason or "abandon" in g.end_reason or "resign" in g.end_reason)]
        m.timeout_win_ratio = self._ratio(len(timeoutish), max(1, len(win_games)))

        # Tournament vs non-tournament
        t_games = [g for g in rated if g.from_tournament]
        nt_games = [g for g in rated if not g.from_tournament]

        m.tourn_games = len(t_games)
        m.tourn_wins = sum(g.is_win for g in t_games)
        m.tourn_draws = sum(g.is_draw for g in t_games)
        m.tourn_losses = sum(g.is_loss for g in t_games)

        m.non_tourn_games = len(nt_games)
        m.non_tourn_wins = sum(g.is_win for g in nt_games)
        m.non_tourn_draws = sum(g.is_draw for g in nt_games)
        m.non_tourn_losses = sum(g.is_loss for g in nt_games)

        # (legacy display) Win rates
        m.tourn_win_rate = self._ratio(m.tourn_wins, max(1, m.tourn_games - m.tourn_draws))
        m.non_tourn_win_rate = self._ratio(m.non_tourn_wins, max(1, m.non_tourn_games - m.non_tourn_draws))
        m.wr_gap = m.tourn_win_rate - m.non_tourn_win_rate

        # --- Elo accounting ---
        def expected_score(r_me: Optional[int], r_opp: Optional[int]) -> Optional[float]:
            if r_me is None or r_opp is None:
                return None
            return 1.0 / (1.0 + 10.0 ** ((r_opp - r_me) / 400.0))

        def actual_score(g: GameSummary) -> float:
            if g.is_win:
                return 1.0
            if g.is_draw:
                return 0.5
            return 0.0

        def accum_elo(glist: List[GameSummary]) -> Tuple[float, float]:
            gain = loss = 0.0
            for g in glist:
                e = expected_score(g.my_rating, g.opp_rating)
                if e is None:
                    continue
                a = actual_score(g)
                d = a - e
                if d >= 0:
                    gain += d
                else:
                    loss += -d
            return gain, loss

        m.elo_gain, m.elo_loss = accum_elo(rated)
        eps = 1e-9
        m.elo_ratio = m.elo_gain / (m.elo_loss if m.elo_loss > eps else eps)

        m.tourn_elo_gain, m.tourn_elo_loss = accum_elo(t_games)
        m.non_tourn_elo_gain, m.non_tourn_elo_loss = accum_elo(nt_games)

        m.tourn_elo_ratio = (m.tourn_elo_gain / (m.tourn_elo_loss if m.tourn_elo_loss > eps else eps)) if m.tourn_games else 0.0
        m.non_tourn_elo_ratio = (m.non_tourn_elo_gain / (m.non_tourn_elo_loss if m.non_tourn_elo_loss > eps else eps)) if m.non_tourn_games else 0.0
        m.elo_ratio_gap = m.tourn_elo_ratio - m.non_tourn_elo_ratio

        # --- Scoring (Elo-driven) ---
        score = 0.0
        def bump(points: float, reason: str):
            nonlocal score
            score += points
            m.reasons.append(reason)

        # High overall Elo overperformance ratio
        if m.lifetime_games >= self.min_games_for_elo and m.elo_ratio >= self.high_elo_ratio:
            bump(2.0, f"High EloRatio {m.elo_ratio:.2f} over {m.lifetime_games} rated games")

        # Tournament >> Non-tournament EloRatio gap
        if (m.tourn_games >= self.tourn_min_games and
            m.non_tourn_games >= self.non_tourn_min_games and
            m.elo_ratio_gap >= self.elo_ratio_gap_suspect):
            bump(2.2, f"Tourn EloRatio {m.tourn_elo_ratio:.2f} vs non-tourn {m.non_tourn_elo_ratio:.2f} (gap {m.elo_ratio_gap:.2f})")

        # Keep orthogonal indicators
        if m.win_streak >= self.streak_suspect:
            bump(1.0, f"Active win streak {m.win_streak}")
        if m.upset_wins >= 3:
            bump(1.0, f"{m.upset_wins} upset wins (≥{self.rating_upset_margin})")
        if m.short_win_rate >= self.short_win_rate_th and len(win_games) >= 10:
            bump(0.7, f"{m.short_win_rate:.0%} of wins ≤{self.short_game_plies} plies")
        if m.timeout_win_ratio >= self.finish_timeout_ratio_th and len(win_games) >= 10:
            bump(0.7, f"{m.timeout_win_ratio:.0%} of wins via resign/timeout")

        m.suspicion_score = round(score, 2)
        return m

    def print_table(self, metrics: List[UserMetrics]) -> None:
        header = (
            f"{'User':<20} {'Games':>5} {'W-D-L':>9} "
            f"{'EloR':>6} {'T.EloR':>7} {'NT.EloR':>7} {'ΔEloR':>7} "
            f"{'Stk':>4} {'Upset':>5} {'ShortW%':>8} {'TO/Res%':>8} "
            f"{'TWR':>6} {'NTWR':>6} {'ΔWR':>6} {'Score':>6}"
        )
        print(header)
        print("-" * len(header))
        for m in metrics:
            wdl  = f"{m.lifetime_wins}-{m.lifetime_draws}-{m.lifetime_losses}"
            print(
                f"{m.username:<20} {m.lifetime_games:>5} {wdl:>9} "
                f"{m.elo_ratio:>6.2f} {m.tourn_elo_ratio:>7.2f} {m.non_tourn_elo_ratio:>7.2f} {m.elo_ratio_gap:>7.2f} "
                f"{m.win_streak:>4} {m.upset_wins:>5} {m.short_win_rate:>8.0%} {m.timeout_win_ratio:>8.0%} "
                f"{m.tourn_win_rate:>6.0%} {m.non_tourn_win_rate:>6.0%} {m.wr_gap:>6.0%} {m.suspicion_score:>6.2f}"
            )

        print("\nTop reasons per user:")
        for m in metrics:
            if m.reasons:
                print(f"- {m.username}: {', '.join(m.reasons)}")


    def write_csv(self, path: str, metrics: List[UserMetrics]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "username",
                "lifetime_games","lifetime_wins","lifetime_draws","lifetime_losses",
                "elo_gain","elo_loss","elo_ratio",
                "tourn_games","tourn_wins","tourn_draws","tourn_losses",
                "tourn_elo_gain","tourn_elo_loss","tourn_elo_ratio",
                "non_tourn_games","non_tourn_wins","non_tourn_draws","non_tourn_losses",
                "non_tourn_elo_gain","non_tourn_elo_loss","non_tourn_elo_ratio",
                "elo_ratio_gap",
                "short_win_rate","timeout_win_ratio",
                "tourn_win_rate","non_tourn_win_rate","wr_gap",
                "suspicion_score","reasons"]
            )
            for m in metrics:
                w.writerow([
                    m.username,
                    m.lifetime_games, m.lifetime_wins, m.lifetime_draws, m.lifetime_losses,
                    f"{m.elo_gain:.6f}", f"{m.elo_loss:.6f}", f"{m.elo_ratio:.6f}",
                    m.tourn_games, m.tourn_wins, m.tourn_draws, m.tourn_losses,
                    f"{m.tourn_elo_gain:.6f}", f"{m.tourn_elo_loss:.6f}", f"{m.tourn_elo_ratio:.6f}",
                    m.non_tourn_games, m.non_tourn_wins, m.non_tourn_draws, m.non_tourn_losses,
                    f"{m.non_tourn_elo_gain:.6f}", f"{m.non_tourn_elo_loss:.6f}", f"{m.non_tourn_elo_ratio:.6f}",
                    f"{m.elo_ratio_gap:.6f}",
                    f"{m.short_win_rate:.6f}", f"{m.timeout_win_ratio:.6f}",
                    f"{m.tourn_win_rate:.6f}", f"{m.non_tourn_win_rate:.6f}", f"{m.wr_gap:.6f}",
                    f"{m.suspicion_score:.2f}", " | ".join(m.reasons)
                ])

    # --------------------- Internals ---------------------

    def _get_json(self, url: str, retries: int = 3, backoff: float = 0.8):
        for i in range(retries):
            r = self.session.get(url, timeout=self.request_timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            time.sleep(backoff * (i + 1))
        return None

    def _get_archives(self, username: str) -> List[str]:
        data = self._get_json(f"{self.API_BASE}/{username}/games/archives")
        if not data or "archives" not in data:
            return []
        return data["archives"]

    @staticmethod
    def _parse_pgn_value(pgn: str, key: str) -> Optional[str]:
        m = re.search(rf'\[{re.escape(key)}\s+\"([^\"]+)\"\]', pgn)
        return m.group(1) if m else None

    @staticmethod
    def _parse_plies_from_pgn(pgn: str) -> Optional[int]:
        parts = re.split(r"\n\n", pgn, maxsplit=1)
        if len(parts) < 2:
            return None
        body = parts[1]
        fullmoves = len(re.findall(r"\b\d+\.", body))
        return 2 * fullmoves if fullmoves > 0 else None

    def _fetch_daily_games(self, username: str, lookback_months: int) -> List[GameSummary]:
        archives = self._get_archives(username)
        if not archives:
            return []

        ym_to_include = set()
        today = dt.date.today()
        cur = today.replace(day=1)
        for _ in range(lookback_months):
            ym_to_include.add(f"{cur.year}-{cur.month:02d}")
            cur = (cur - dt.timedelta(days=1)).replace(day=1)

        results: List[GameSummary] = []
        for url in archives:
            parts = url.rstrip("/").split("/")
            if len(parts) < 2:
                continue
            y, m = parts[-2], parts[-1]
            ym = f"{y}-{m}"
            if ym not in ym_to_include:
                continue

            data = self._get_json(url)
            if not data or "games" not in data:
                continue

            for g in data["games"]:
                if g.get("time_class") != "daily":
                    continue
                rated = bool(g.get("rated"))
                pgn = g.get("pgn", "")
                end_reason = (self._parse_pgn_value(pgn, "Termination") or "").lower()
                result = self._parse_pgn_value(pgn, "Result") or ""

                white = g.get("white", {})
                black = g.get("black", {})
                end_time = g.get("end_time")

                is_white = white.get("username", "").lower() == username.lower()
                me = white if is_white else black
                opp = black if is_white else white
                my_rating = me.get("rating")
                opp_rating = opp.get("rating")
                plies = self._parse_plies_from_pgn(pgn)
                from_tourn = "tournament" in g

                is_win  = (result == "1-0" and is_white) or (result == "0-1" and not is_white)
                is_loss = (result == "0-1" and is_white) or (result == "1-0" and not is_white)
                is_draw = (result == "1/2-1/2")

                results.append(GameSummary(
                    result=result,
                    is_win=is_win,
                    is_loss=is_loss,
                    is_draw=is_draw,
                    my_rating=my_rating,
                    opp_rating=opp_rating,
                    plies=plies,
                    end_reason=end_reason,
                    is_rated=rated,
                    from_tournament=from_tourn,
                    end_time=end_time
                ))

        return results

    @staticmethod
    def _ratio(n: int, d: int) -> float:
        return n / d if d > 0 else 0.0

    @staticmethod
    def _rolling_win_streak(games: List[GameSummary]) -> Tuple[int, int]:
        gs = [g for g in games if g.end_time]
        gs.sort(key=lambda x: x.end_time)
        cur = mx = 0
        for g in gs:
            if g.is_win:
                cur += 1
                mx = max(mx, cur)
            else:
                cur = 0
        return cur, mx


# --------------------------- Optional CLI ---------------------------

def _cli():
    ap = argparse.ArgumentParser(description="Detect suspicious Daily players (Tournament vs Non-Tournament) with Elo overperformance scoring")
    ap.add_argument("usernames_file", help="Path to text file with one Chess.com username per line")
    ap.add_argument("--lookback-months", type=int, default=2)
    ap.add_argument("--min-games", type=int, default=30)
    ap.add_argument("--tourn-min-games", type=int, default=15)
    ap.add_argument("--non-tourn-min-games", type=int, default=15)
    ap.add_argument("--high-elo-ratio", type=float, default=2.0)
    ap.add_argument("--elo-ratio-gap", type=float, default=1.0)
    ap.add_argument("--csv", type=str, default=None)
    args = ap.parse_args()

    scanner = SusScanner(
        lookback_months=args.lookback_months,
        min_lifetime_games=args.min_games,
        tourn_min_games=args.tourn_min_games,
        non_tourn_min_games=args.non_tourn_min_games,
        high_elo_ratio=args.high_elo_ratio,
        elo_ratio_gap_suspect=args.elo_ratio_gap,
    )

    results = scanner.analyze_usernames_file(args.usernames_file)
    scanner.print_table(results)
    if args.csv:
        scanner.write_csv(args.csv, results)
        print(f"\nCSV written to {args.csv}")


if __name__ == "__main__":
    _cli()
