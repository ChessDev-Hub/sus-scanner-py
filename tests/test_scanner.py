from sus_scanner import SusScanner

def test_init_defaults():
    s = SusScanner()
    assert s.lookback_months == 2
