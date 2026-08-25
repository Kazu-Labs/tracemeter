"""tracemeter CLI: `tracemeter serve` launches the local dashboard.

Zero required config: run it, get a URL, see your traces. No collector,
no exporter, no account.
"""

from __future__ import annotations

import argparse
import sys

from tracemeter.storage.sqlite_store import default_db_path


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "The dashboard server requires extra dependencies.\n"
            "Install them with: pip install 'tracemeter[server]'",
            file=sys.stderr,
        )
        return 1

    from tracemeter.server.app import create_app
    from tracemeter.storage.sqlite_store import SqliteStore

    store = SqliteStore(args.db) if args.db else SqliteStore.default()
    app = create_app(store=store)

    print(f"TraceMeter dashboard: reading {store.db_path}")
    print(f"Serving at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_where(args: argparse.Namespace) -> int:
    print(default_db_path())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tracemeter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Launch the local dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument(
        "--db", default=None, help="Path to the SQLite trace DB (default: ~/.tracemeter/traces.db)"
    )
    serve.set_defaults(func=_cmd_serve)

    where = subparsers.add_parser("where", help="Print the default trace DB path")
    where.set_defaults(func=_cmd_where)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
