from sus_scanner import SusScanner

scanner = SusScanner(lookback_months=3, wr_gap_suspect=0.25)
metrics = scanner.analyze_usernames(["AlAlper", "SomeOpponent123"])
scanner.print_table(metrics)
scanner.write_csv("suspicion_report.csv", metrics)
