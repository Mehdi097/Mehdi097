#!/usr/bin/env python3
"""Point d'entrée TraderDesk.

    python run.py                         # application + navigateur (local)
    python run.py --host 0.0.0.0 --port 8000 --no-browser   # aperçu distant
    python run.py --bridge --api-key MA_CLE --port 8765     # passerelle MT5
    python run.py --reset                 # repartir d'un compte démo vierge

Depuis le .exe Windows : TraderDesk.exe [--bridge ...] [--port 8770]
"""

import argparse
import os
import sys
import threading
import time
import webbrowser


def main(argv=None):
    ap = argparse.ArgumentParser(description="TraderDesk — 11 agents de trading + MetaTrader 5")
    ap.add_argument("--host", default=os.environ.get("TRADERDESK_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("TRADERDESK_PORT", "8770")))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reset", action="store_true", help="réinitialiser les données de démo")
    ap.add_argument("--bridge", action="store_true", help="lancer la passerelle REST MT5 au lieu du dashboard")
    ap.add_argument("--api-key", default=os.environ.get("TRADERDESK_API_KEY", "change-moi"))
    ap.add_argument("--login", default=os.environ.get("MT5_LOGIN", ""))
    ap.add_argument("--password", default=os.environ.get("MT5_PASSWORD", ""))
    ap.add_argument("--server", default=os.environ.get("MT5_SERVER", ""))
    ap.add_argument("--terminal-path", default=os.environ.get("MT5_PATH", ""))
    args, extra = ap.parse_known_args(argv)

    if args.bridge:
        from traderdesk.mt5.bridge import main as bridge_main
        return bridge_main(["--api-key", args.api_key, "--port", str(args.port),
                            "--host", args.host, "--login", args.login,
                            "--password", args.password, "--server", args.server,
                            "--terminal-path", args.terminal_path])

    from traderdesk.settings import Settings
    from traderdesk.state import Store
    from traderdesk.agents.registry import AGENTS_BY_ID
    from traderdesk.mt5 import ConnectorManager
    from traderdesk.agents.engine import Engine
    from traderdesk.server import serve

    settings = Settings()
    store = Store(list(AGENTS_BY_ID))
    connectors = ConnectorManager(settings, store)
    engine = Engine(settings, store, connectors)
    if args.reset:
        store.reset_demo()
    engine.seed(force=bool(args.reset))
    engine.start()

    httpd = serve(host=args.host, port=args.port, settings=settings, store=store, engine=engine)
    url = "http://%s:%d/" % ("127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host, args.port)
    print("TraderDesk prêt : %s  (API : %sapi/state)" % (url, url), flush=True)
    print("Dossier de travail : %s" % os.environ.get("TRADERDESK_HOME", "runtime/"), flush=True)
    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt de TraderDesk…", flush=True)
    finally:
        engine.stop()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
