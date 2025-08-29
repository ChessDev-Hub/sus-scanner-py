import argparse
from .scanner import SusScanner

def main():
    ap = argparse.ArgumentParser(description="Detect suspicious Daily players (Tournament vs Non-Tournament)")
    ap.add_argument("usernames_file", help="Path to text file with one Chess.com username per line")
    ap.add_argument("--lookback-months", type=int, default=2)
    ap.add_argument("--min-games", type=int, default=30)
    ap.add_argument("--tourn-min-games", type=int, default=15)
    ap.add_argument("--non-tourn-min-games", type=int, default=15)
    ap.add_argument("--wr-gap-suspect", type=float, default=0.25)
    ap.add_argument("--csv", type=str, default=None)
    args = ap.parse_args()

    scanner = SusScanner(
        lookback_months=args.lookback_months,
        min_lifetime_games=args.min_games,
        tourn_min_games=args.tourn_min_games,
        non_tourn_min_games=args.non_tourn_min_games,
        wr_gap_suspect=args.wr_gap_suspect,
    )

    results = scanner.analyze_usernames_file(args.usernames_file)
    scanner.print_table(results)
    if args.csv:
        scanner.write_csv(args.csv, results)
        print(f"\nCSV written to {args.csv}")
