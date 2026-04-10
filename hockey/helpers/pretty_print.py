# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):    print(f"{GREEN}  ✓ {msg}{RESET}")
def info(msg):  print(f"{CYAN}  → {msg}{RESET}")
def warn(msg):  print(f"{YELLOW}  ⚠ {msg}{RESET}")
def err(msg):   print(f"{RED}  ✗ {msg}{RESET}")
def header(msg):print(f"\n{BOLD}{msg}{RESET}")

__all__ = ['GREEN', 'YELLOW', 'RED', 'CYAN', 'RESET', 'BOLD', 'ok', 'info', 'warn', 'err', 'header']

