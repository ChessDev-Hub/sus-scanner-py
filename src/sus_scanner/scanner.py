#!/usr/bin/env python3
from __future__ import annotations
import csv
import datetime as dt
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import requests


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

    lifetime_games: int = 0
    lifetime_wins: int = 0
    lifetime_draws: int = 0
    lifetime_losses: int = 0

    recent_games: int = 0
    recent_wins: int = 0
    recent_draws: int = 0
    recent_losses: int = 0

    win_streak: int = 0
    max_win_streak: int = 0

    upset_wins: int = 0
    short_win_rate: float = 0.0
    timeout_win_ratio: float = 0.0

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
    wr_gap: float = 0.0

    suspicion_score: float = 0.0
    reasons: List[str] = field(default_factory=list)


class SusScanner:
    API_BASE = "https://api.chess.com/pub/player"

    def __init__(
        self,
        *,
        user_agent: str = "GrandTourneys Suspicion Scanner (+contact: example@example.com)",
        lookback_months: int = 2,
        min_lifetime_games: int = 30,
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
    ):
        self.lookback_months = lookback_months

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

        self.request_timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

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

        m.lifetime_games = len(rated)
        m.lifetime_wins = sum(g.is_win for g in rated)
        m.lifetime_draws = sum(g.is_draw for g in rated)
        m.lifetime_losses = sum(g.is_loss for g in rated)

        m.recent_games = m.lifetime_games
        m.recent_wins = m.lifetime_wins
        m.recent_draws = m.lifetime_draws
        m.recent_losses = m.lifetime_losses

        m.win_streak, m.max_win_streak = self._rolling_win_streak(games)

        for g in rated:
            if g.is_win and g.my_rating and g.opp_rating:
                if g.opp_rating - g.my_rating >= self.rating_upset_margin:
                    m.upset_wins += 1

        win_games = [g for g in rated if g.is_win]
        short_wins = [g for g in win_games if (g.plies or 10**9) <= self.short_game_plies]
        m.short_win_rate = self._ratio(len(short_wins), max(1, len(win_games)))

        timeoutish = [g for g in win_games if ("timeout" in g.end_reason or "abandon" in g.end_reason or "resign" in g.end_reason)]
        m.timeout_win_ratio = self._ratio(len(timeoutish), max(1, len(win_games)))

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

        m.tourn_win_rate = self._ratio(m.tourn_wins, max(1, m.tourn_games - m.tourn_draws))
        m.non_tourn_win_rate = self._ratio(m.non_tourn_wins, max(1, m.non_tourn_games - m.non_tourn_draws))
        m.wr_gap = m.tourn_win_rate - m.non_tourn_win_rate

        life_wr = self._ratio(m.lifetime_wins, max(1, m.lifetime_games - m.lifetime_draws))
        rec_wr = self._ratio(m.recent_wins, max(1, m.recent_games - m.recent_draws))

        score = 0.0
        def bump(points: float, reason: str):
            nonlocal score
            score += points
            m.reasons.append(reason)

        if m.lifetime_games >= self.min_lifetime_games and life_wr >= self.high_win_rate:
            bump(2.0, f"High lifetime WR {life_wr:.0%} over {m.lifetime_games} games")

        if m.recent_games >= self.recent_min_games:
            if rec_wr >= self.high_win_rate:
                bump(2.0, f"High recent WR {rec_wr:.0%} over {m.recent_games} games")
            if m.lifetime_games >= self.min_lifetime_games and (rec_wr - life_wr) >= self.spike_delta:
                bump(1.5, f"Recent spike +{(rec_wr - life_wr):.0%} vs lifetime")

        if m.win_streak >= self.streak_suspect:
            bump(1.0, f"Active win streak {m.win_streak}")

        if m.upset_wins >= 3:
            bump(1.0, f"{m.upset_wins} upset wins (≥{self.rating_upset_margin})")

        if m.short_win_rate >= self.short_win_rate_th and len(win_games) >= 10:
            bump(0.7, f"{m.short_win_rate:.0%} of wins ≤{self.short_game_plies} plies")

        if m.timeout_win_ratio >= self.finish_timeout_ratio_th and len(win_games) >= 10:
            bump(0.7, f"{m.timeout_win_ratio:.0%} of wins via resign/timeout")

        if (m.tourn_games >= self.tourn_min_games and
            m.non_tourn_games >= self.non_tourn_min_games and
            m.wr_gap >= self.wr_gap_suspect):
            bump(2.2, f"Tournament WR {m.tourn_win_rate:.0%} vs non-tournament {m.non_tourn_win_rate:.0%} (gap {m.wr_gap:.0%})")

        m.suspicion_score = round(score, 2)
        return m

    def print_table(self, metrics: List[UserMetrics]) -> None:
        header = (
            f"{'User':<20} {'Games':>5} {'W-D-L':>9} {'LifeWR':>7} "
            f"{'Recent':>6} {'R W-D-L':>9} {'RecWR':>7} {'Stk':>4} "
            f"{'Upset':>5} {'ShortW%':>8} {'TO/Res%':>8} "
            f"{'TournWR':>8} {'NonTWR':>8} {'Gap':>6} {'Score':>6}"
        )
        print(header)
        print("-" * len(header))
        for m in metrics:
            life_wr = (m.lifetime_wins / max(1, (m.lifetime_games - m.lifetime_draws))) if m.lifetime_games else 0
            rec_wr  = (m.recent_wins  / max(1, (m.recent_games  - m.recent_draws))) if m.recent_games else 0
            wdl  = f"{m.lifetime_wins}-{m.lifetime_draws}-{m.lifetime_losses}"
            rwdl = f"{m.recent_wins}-{m.recent_draws}-{m.recent_losses}"
            print(
                f"{m.username:<20} {m.lifetime_games:>5} {wdl:>9} {life_wr:>7.0%} "
                f"{m.recent_games:>6} {rwdl:>9} {rec_wr:>7.0%} {m.win_streak:>4} "
                f"{m.upset_wins:>5} {m.short_win_rate:>8.0%} {m.timeout_win_ratio:>8.0%} "
                f"{m.tourn_win_rate:>8.0%} {m.non_tourn_win_rate:>8.0%} {m.wr_gap:>6.0%} {m.suspicion_score:>6.2f}"
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
                "lifetime_games","lifetime_wins","lifetime_draws","lifetime_losses","lifetime_win_rate",
                "recent_games","recent_wins","recent_draws","recent_losses","recent_win_rate",
                "active_win_streak","max_win_streak","upset_wins",
                "short_win_rate","timeout_win_ratio",
                "tourn_games","tourn_wins","tourn_draws","tourn_losses","tourn_win_rate",
                "non_tourn_games","non_tourn_wins","non_tourn_draws","non_tourn_losses","non_tourn_win_rate",
                "wr_gap","suspicion_score","reasons"
            ])
            for m in metrics:
                life_wr = (m.lifetime_wins / max(1, (m.lifetime_games - m.lifetime_draws))) if m.lifetime_games else 0
                rec_wr  = (m.recent_wins  / max(1, (m.recent_games  - m.recent_draws))) if m.recent_games else 0
                w.writerow([
                    m.username,
                    m.lifetime_games, m.lifetime_wins, m.lifetime_draws, m.lifetime_losses, f"{life_wr:.4f}",
                    m.recent_games, m.recent_wins, m.recent_draws, m.recent_losses, f"{rec_wr:.4f}",
                    m.win_streak, m.max_win_streak, m.upset_wins,
                    f"{m.short_win_rate:.4f}", f"{m.timeout_win_ratio:.4f}",
                    m.tourn_games, m.tourn_wins, m.tourn_draws, m.tourn_losses, f"{m.tourn_win_rate:.4f}",
                    m.non_tourn_games, m.non_tourn_wins, m.non_tourn_draws, m.non_tourn_losses, f"{m.non_tourn_win_rate:.4f}",
                    f"{m.wr_gap:.4f}", f"{m.suspicion_score:.2f}", " | ".join(m.reasons)
                ])

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
        m = re.search(rf'\[{re.escape(key)}\s+"([^"]+)"\]', pgn)
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
