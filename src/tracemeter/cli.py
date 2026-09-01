"""tracemeter CLI: `tracemeter serve` launches the local dashboard.

Zero required config: run it, get a URL, see your traces. No collector,
no exporter, no account.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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

    store = SqliteStore(Path(args.db)) if args.db else SqliteStore.default()
    app = create_app(store=store)

    print(f"TraceMeter dashboard: reading {store.db_path}")
    print(f"Serving at http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    try:
        from tracemeter.mcp_server import create_mcp_server
    except ImportError:
        print(
            "The MCP server requires extra dependencies (Python 3.10+).\n"
            "Install them with: pip install 'tracemeter[mcp]'",
            file=sys.stderr,
        )
        return 1

    from tracemeter.storage.sqlite_store import SqliteStore

    store = SqliteStore(Path(args.db)) if args.db else SqliteStore.default()
    # stdio transport uses stdout for the JSON-RPC protocol itself -- any
    # stray print() to stdout here would corrupt the stream, so status
    # goes to stderr only.
    print(f"TraceMeter MCP server: reading {store.db_path}", file=sys.stderr)
    create_mcp_server(store=store).run(transport="stdio")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from tracemeter.demo import populate_demo_data
    from tracemeter.storage.sqlite_store import SqliteStore

    db_path = Path(args.db) if args.db else default_db_path().parent / "demo.db"
    if db_path.exists():
        db_path.unlink()  # regenerate fresh each time so it's reproducible

    store = SqliteStore(db_path)
    summary = populate_demo_data(store)
    print(
        f"Seeded {summary.trace_count} demo traces ({summary.span_count} spans, "
        f"${summary.total_cost_usd:,.2f} total cost) into {db_path}\n"
        "Synthetic data -- no API keys or real LLM calls involved."
    )

    if args.no_serve:
        print(f"Run `tracemeter serve --db {db_path}` to view it.")
        return 0

    try:
        import uvicorn
    except ImportError:
        print(
            "The dashboard requires extra dependencies.\n"
            "Install them with: pip install 'tracemeter[server]'",
            file=sys.stderr,
        )
        return 1

    from tracemeter.server.app import create_app

    app = create_app(store=store)
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

    demo = subparsers.add_parser(
        "demo", help="Seed synthetic trace data and open the dashboard -- no API keys needed"
    )
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8765)
    demo.add_argument(
        "--db", default=None, help="Path to write demo data to (default: ~/.tracemeter/demo.db)"
    )
    demo.add_argument(
        "--no-serve", action="store_true", help="Seed the demo data without launching the dashboard"
    )
    demo.set_defaults(func=_cmd_demo)

    where = subparsers.add_parser("where", help="Print the default trace DB path")
    where.set_defaults(func=_cmd_where)

    mcp = subparsers.add_parser(
        "mcp", help="Launch the MCP server (stdio) for agent access to trace/cost data"
    )
    mcp.add_argument(
        "--db", default=None, help="Path to the SQLite trace DB (default: ~/.tracemeter/traces.db)"
    )
    mcp.set_defaults(func=_cmd_mcp)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
