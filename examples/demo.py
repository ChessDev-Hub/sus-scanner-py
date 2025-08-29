from sus_scanner import SusScanner

if __name__ == "__main__":
    scanner = SusScanner(lookback_months=3)
    results = scanner.analyze_usernames_file("../usernames.txt")
    scanner.print_table(results)
