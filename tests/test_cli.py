import sys

import pytest

from tracemeter.cli import build_parser


def test_serve_command_accepts_explicit_db_path(tmp_path, monkeypatch):
    """Regression test: --db was passed straight through to SqliteStore as
    a plain string, but SqliteStore expects a Path (it calls
    `.parent.mkdir(...)` on it) -- `tracemeter serve --db <path>` crashed
    with AttributeError before ever reaching uvicorn.run."""
    db_path = tmp_path / "custom.db"
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    parser = build_parser()
    args = parser.parse_args(["serve", "--db", str(db_path)])
    exit_code = args.func(args)

    assert exit_code == 0
    assert db_path.exists()


def test_mcp_command_accepts_explicit_db_path(tmp_path, monkeypatch):
    if sys.version_info < (3, 10):
        pytest.skip("mcp requires Python 3.10+")
    pytest.importorskip("mcp")

    db_path = tmp_path / "custom.db"
    monkeypatch.setattr(
        "tracemeter.mcp_server.create_mcp_server",
        lambda store=None: type("FakeServer", (), {"run": lambda self, transport: None})(),
    )

    parser = build_parser()
    args = parser.parse_args(["mcp", "--db", str(db_path)])
    exit_code = args.func(args)

    assert exit_code == 0
    assert db_path.exists()


def test_demo_command_seeds_data_without_serving(tmp_path, capsys):
    db_path = tmp_path / "demo.db"
    parser = build_parser()
    args = parser.parse_args(["demo", "--db", str(db_path), "--no-serve"])

    exit_code = args.func(args)

    assert exit_code == 0
    assert db_path.exists()
    out = capsys.readouterr().out
    assert "Seeded" in out
    assert "demo traces" in out


def test_where_command_prints_a_path(capsys):
    parser = build_parser()
    args = parser.parse_args(["where"])

    exit_code = args.func(args)

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
