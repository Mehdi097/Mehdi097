#!/usr/bin/env python3
"""runner.py - one entry point for the whole pack. This is what becomes .exe.

Double-click it: you get a menu. Or give it a command, exactly like the CLI:

    mt5trader.exe                       # menu
    mt5trader.exe setup                 # create trader/ with config + symbols
    mt5trader.exe doctor                # is this machine ready?
    mt5trader.exe analyze --write       # metrics for the universe
    mt5trader.exe screen --write-targets
    mt5trader.exe plan --write          # lots + SL/TP -> orders.json
    mt5trader.exe check                 # PASS / BLOCK
    mt5trader.exe tickets               # READY or not
    mt5trader.exe approve --id ID --reply "yes"
    mt5trader.exe send --id ID --dry-run
    mt5trader.exe send --id ID
    mt5trader.exe journal --days 30
    mt5trader.exe clock
    mt5trader.exe kill on

Every command is forwarded to the skill that owns it, so all the flags in the
SKILL.md files still work. The only thing this file adds is: finding the pack
folders inside a frozen exe, and a default trader/ folder next to the exe so a
double-click behaves predictably.
"""

import argparse
import importlib.util
import os
import shutil
import sys

VERSION = "1.0.0"

FOLDERS = (
    "mt5-core", "mt5-analyst", "mt5-screener", "mt5-copycat", "mt5-budget",
    "mt5-risk", "mt5-broker", "mt5-journal", "mt5-alerts", "mt5-exposure",
    "mt5-calendar", "mt5-news",
)

# name -> (folder, module, argv prefix, what it does, sends orders?)
COMMANDS = {
    "setup": ("mt5-core", "doctor", ["--init"], "create trader/ (config + symbols)", False),
    "doctor": ("mt5-core", "doctor", [], "check the machine and the account", False),
    "account": ("mt5-core", "bridge", ["account"], "balance, equity, margin, demo/real", False),
    "symbols": ("mt5-core", "bridge", ["symbols"], "find the broker's exact symbol name", False),
    "spec": ("mt5-core", "bridge", ["spec"], "digits, tick value, lot step, stops level", False),
    "tick": ("mt5-core", "bridge", ["tick"], "current bid/ask", False),
    "positions": ("mt5-core", "bridge", ["positions"], "open positions", False),
    "snapshot": ("mt5-core", "bridge", ["snapshot"], "freeze quotes for offline mode", False),
    "analyze": ("mt5-analyst", "analyst", [], "ATR, ADR, RSI, trend, spread", False),
    "screen": ("mt5-screener", "screen", [], "your rules -> ranked targets", False),
    "copy": ("mt5-copycat", "copy", [], "copy a statement into target weights", False),
    "plan": ("mt5-budget", "size", [], "weights -> lots, SL, TP", False),
    "check": ("mt5-risk", "check", [], "PASS or BLOCK every order", False),
    "tickets": ("mt5-broker", "execute", ["show"], "the tickets, READY or not", False),
    "approve": ("mt5-broker", "execute", ["approve"], "record your yes for ONE order", False),
    "send": ("mt5-broker", "execute", ["send"], "place an approved order", True),
    "close": ("mt5-broker", "execute", ["close"], "close one position", True),
    "close-all": ("mt5-broker", "execute", ["close-all"], "close every position", True),
    "status": ("mt5-broker", "execute", ["status"], "account + kill switch + pending", False),
    "log": ("mt5-broker", "execute", ["log"], "today's decisions", False),
    "kill": ("mt5-broker", "execute", ["kill"], "stop everything: kill on / off", False),
    "journal": ("mt5-journal", "journal", [], "win rate, PF, drawdown", False),
    "alerts": ("mt5-alerts", "alerts", [], "check the alerts once", False),
    "clock": ("mt5-alerts", "alerts", ["clock"], "server time and sessions", False),
    "calendar": ("mt5-calendar", "econ", [], "events + news blackout", False),
    "news": ("mt5-news", "news", [], "headlines for your pairs", False),
    "exposure": ("mt5-exposure", "rebalance", [], "currency tilt and drift", False),
}

MENU = [
    ("1", "setup", "awwel marra: sawb trader\\config.json w symbols.json"),
    ("2", "doctor", "wach l'machine wajda? (terminal, AutoTrading, symbols)"),
    ("3", "analyze --write", "7allel l'universe"),
    ("4", "screen --show-fails --write-targets", "filter w ranki"),
    ("5", "plan --write", "7seb l'volume w SL/TP"),
    ("6", "check", "PASS / BLOCK"),
    ("7", "tickets", "l'tickets"),
    ("8", "status", "compte + kill switch"),
    ("9", "journal --days 30", "l'stats dyalek"),
    ("10", "clock", "sessions w l'wa9t"),
    ("11", "calendar --mine --write", "blackout dyal lyoum"),
    ("12", "exposure --band 5", "ch7al m3arred"),
    ("13", "kill on", "WE9EF KOULCHI"),
]


# ---------------------------------------------------------------- locating

def pack_root():
    """Where the mt5-* folders live: the exe bundle first, then this checkout."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle and os.path.isdir(bundle):
        return bundle
    if getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.isdir(os.path.join(here, "mt5-core")):
            return here
        internal = os.path.join(here, "_internal")
        if os.path.isdir(os.path.join(internal, "mt5-core")):
            return internal
        return here
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def skill_path(folder, module):
    """Absolute path to a skill script, or None."""
    name = module + ".py"
    roots = [pack_root()]
    here = os.path.dirname(os.path.abspath(__file__))
    roots += [os.path.join(here, ".."), here, os.getcwd()]
    for root in roots:
        path = os.path.abspath(os.path.join(root, folder, name))
        if os.path.isfile(path):
            return path
    return None


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def default_trader_dir():
    """trader/ next to the exe (double-click friendly), or ./trader in a checkout."""
    env = os.environ.get("MT5_TRADER_DIR")
    if env:
        return env
    if getattr(sys, "frozen", False):
        return os.path.join(app_dir(), "trader")
    return "trader"


def load_skill(folder, module):
    key = "mt5app_" + module
    if key in sys.modules:
        return sys.modules[key]
    path = skill_path(folder, module)
    if not path:
        raise SystemExit(
            "%s/%s.py ma l9itch / not found in the bundle.\n"
            "  bundle: %s\n  exe:    %s" % (folder, module, pack_root(), app_dir()))
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- bootstrap

def bootstrap(trader_dir):
    """Create trader/ from the bundled examples on first run. Never overwrites."""
    created = []
    os.makedirs(os.path.join(trader_dir, "state"), exist_ok=True)
    os.makedirs(os.path.join(trader_dir, "data"), exist_ok=True)
    pairs = [("config.example.json", "config.json"),
             ("symbols.example.json", "symbols.json")]
    for example, target in pairs:
        dest = os.path.join(trader_dir, target)
        if os.path.exists(dest):
            continue
        src = None
        for folder in (".", "mt5-core"):
            for root in (pack_root(), os.path.dirname(os.path.abspath(__file__))):
                cand = os.path.join(root, folder, example)
                if os.path.isfile(cand):
                    src = cand
                    break
            if src:
                break
        if src:
            shutil.copyfile(src, dest)
            created.append(dest)
    return created


# ---------------------------------------------------------------- running

def maybe_bootstrap():
    """Create trader/ on first run when we are an exe, or when the user pointed
    MT5_TRADER_DIR somewhere. In a source checkout, `setup` stays explicit."""
    if not (getattr(sys, "frozen", False) or os.environ.get("MT5_TRADER_DIR")):
        return []
    created = bootstrap(default_trader_dir())
    if created:
        print("trader/ tsayeb: %s (3emmer config.json mn be3d)\n" % ", ".join(created))
    return created


def resolve(command, extra):
    if command not in COMMANDS:
        raise SystemExit("commande ma3roufach / unknown command %r" % command)
    folder, module, prefix, _, sends = COMMANDS[command]
    argv = list(prefix) + list(extra)
    if "--trader-dir" not in argv:
        argv = ["--trader-dir", default_trader_dir()] + argv
    return folder, module, argv, sends


def run(command, extra):
    folder, module, argv, sends = resolve(command, extra)
    if sends:
        print("!! had l'commande kat-sift order / this command can place an order.")
    mod = load_skill(folder, module)
    try:
        return int(mod.main(argv) or 0)
    except SystemExit as e:
        return int(e.code or 0)


def banner():
    print("")
    print("  mt5-trader-skill %s" % VERSION)
    print("  exe      : %s" % app_dir())
    print("  pack     : %s" % pack_root())
    print("  trader   : %s" % default_trader_dir())
    print("  python   : %s%s" % (sys.version.split()[0],
                                 "  (frozen)" if getattr(sys, "frozen", False) else ""))
    print("")


def menu():
    banner()
    maybe_bootstrap()
    while True:
        print("  chnou bghit? / what do you want?")
        print("")
        for key, command, label in MENU:
            print("   %-3s %-38s %s" % (key, command, label))
        print("   %-3s %-38s %s" % ("h", "help", "every command, with its flags"))
        print("   %-3s %-38s %s" % ("q", "quit", "khoroj"))
        print("")
        try:
            choice = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("")
            return 0
        if choice in ("q", "quit", "exit", "0"):
            return 0
        if choice in ("h", "help", "?"):
            print_help()
            continue
        picked = next((c for k, c, _ in MENU if k == choice), None)
        if not picked:
            print("  ma fhemtch / not an option: %r\n" % choice)
            continue
        command, _, extra = picked.partition(" ")
        print("\n  --- %s ---\n" % picked)
        try:
            code = run(command, extra.split() if extra else [])
        except SystemExit as e:
            code = int(e.code or 0) or 1
        except Exception as e:  # noqa: BLE001 - the menu must never die
            print("  ERROR: %s" % e)
            code = 1
        print("\n  [exit %d]\n" % code)
        try:
            input("  Enter bach tkemmel / press Enter ")
        except (EOFError, KeyboardInterrupt):
            print("")
            return 0


def print_help():
    banner()
    print("  usage: mt5trader.exe <command> [flags]\n")
    for name in sorted(COMMANDS):
        folder, module, prefix, what, sends = COMMANDS[name]
        print("   %-11s %-46s %s%s" % (name, what, "[sends orders] " if sends else "", ""))
    print("""
  had l'flags kaydewzo l kol commande / these work everywhere:
     --offline            no terminal, read trader/data/snapshot.json
     --trader-dir PATH    use another trader/ folder
     --json               machine-readable output

  examples:
     mt5trader.exe setup
     mt5trader.exe doctor
     mt5trader.exe analyze --write
     mt5trader.exe screen --show-fails --write-targets
     mt5trader.exe plan --write
     mt5trader.exe check
     mt5trader.exe tickets
     mt5trader.exe approve --id EURUSD-buy-20261106120000 --reply "yes"
     mt5trader.exe send --id EURUSD-buy-20261106120000 --dry-run
     mt5trader.exe send --id EURUSD-buy-20261106120000
     mt5trader.exe kill on

  ma kaynch order bla: PASS mn mt5-risk 3la dak l'order, w yes dyalek 3la dak l'id.
  no order without a risk PASS for that exact order and your explicit yes.
""")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return menu()
    command, extra = argv[0].lower(), argv[1:]
    if command in ("help", "-h", "--help", "?"):
        print_help()
        return 0
    if command in ("version", "-V", "--version"):
        print(VERSION)
        return 0
    if command not in COMMANDS:
        print("commande ma3roufach / unknown command %r\n" % command, file=sys.stderr)
        print_help()
        return 2
    maybe_bootstrap()
    return run(command, extra)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        sys.exit(130)
