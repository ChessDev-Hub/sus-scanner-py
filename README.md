# SusScanner – Suspicious Daily Play Scanner (Elo-based)

This tool analyzes **Chess.com Daily** games and flags potentially suspicious accounts
using **Elo overperformance** instead of raw win rates.

## What changed (core logic)

We now compute, for each rated game:

- **Expected score (Elo)**: `E = 1 / (1 + 10^((opp - me)/400))`
- **Actual score**: win = `1.0`, draw = `0.5`, loss = `0.0`
- **Delta**: `actual - expected`

We accumulate across games:

- `EloGain = sum(max(0, delta))`
- `EloLoss = sum(max(0, -delta))`
- **EloRatio** = `EloGain / max(EloLoss, ε)` (ε avoids divide-by-zero)

We compute these **overall**, **tournament**, and **non-tournament**, and then compare:

- **EloRatioGap** = `TournamentEloRatio − NonTournamentEloRatio`

Suspicion scoring now emphasizes **Elo overperformance** and **tournament vs non-tournament gaps**.

## Why this is better

Raw win rate can be misleading across rating ranges or mixed opposition.
The Elo-based approach compares results against **opponent strength**, rewarding legitimate underdog wins
and discounting wins that were already expected.

## Current scoring (defaults)

- `EloRatio ≥ 2.0` over enough games (≥ 20) → **+2.0**
- `TournamentEloRatio − NonTournamentEloRatio ≥ 1.0` with each bucket ≥ 15 games → **+2.2**
- Keep orthogonal context signals:
  - Active win streak ≥ 8 → **+1.0**
  - Upset wins ≥ 3 (≥ 250 rating diff) → **+1.0**
  - Short wins ≥ 70% (≤ 40 plies, with ≥ 10 wins) → **+0.7**
  - Resign/timeout wins ≥ 50% (with ≥ 10 wins) → **+0.7**

> This is a **triage** tool to prioritize manual review. It does **not** assert cheating.

## Usage

```bash
# From a usernames file
python sus_scanner.py usernames.txt --lookback-months 3 --csv out.csv

# Tune Elo thresholds if needed
python sus_scanner.py usernames.txt --high-elo-ratio 2.5 --elo-ratio-gap 1.2
```

The console table shows per-user: overall/tournament/non-tournament **EloRatio**, the gap,
streaks/upsets/short-wins/timeout pattern, legacy win-rate splits (for context), and the **suspicion score**.
CSV export includes all fields.

## Data source

Public Chess.com player archives for **Daily** time control (rated only). The code parses PGN headers
for result/termination and uses the API-provided end-of-game ratings to compute expected scores
and the Elo over/under-performance totals.
