# ♟️ SusScanner – Chess.com Daily Suspicion Scanner

**SusScanner** is a Python module + CLI tool for analyzing Chess.com **Daily games** and detecting suspicious activity.  
It compares **Tournament vs Non-Tournament** performance and flags large gaps, streaks, upset wins, short-game patterns, and timeout-heavy wins.

## 🚀 Features
- Fetches Daily games via the official Chess.com Published Data API
- Tournament vs Non‑Tournament win rate comparison
- Lifetime/recent win rates, active win streaks
- Upset wins vs higher‑rated opponents
- Short‑game and timeout/resign concentration checks
- Composite suspicion score with human‑readable reasons
- CLI and importable module, CSV export

## 📦 Install
```bash
pip install -r requirements.txt
pip install -e .
```

## 🖥️ CLI Usage
Prepare a text file with usernames (one per line), then run:
```bash
sus-scanner usernames.txt --lookback-months 3 --csv suspicion_report.csv
```

## 🐍 Module Usage
```python
from sus_scanner import SusScanner
scanner = SusScanner(lookback_months=3, wr_gap_suspect=0.25)
results = scanner.analyze_usernames_file("usernames.txt")
scanner.print_table(results)
scanner.write_csv("suspicion_report.csv", results)
```

## 📂 Layout
- `src/sus_scanner/scanner.py` – core `SusScanner` implementation
- `src/sus_scanner/cli.py` – command‑line entrypoint (`sus-scanner`)
- `examples/demo.py` – minimal example
- `tests/test_scanner.py` – simple sanity test
