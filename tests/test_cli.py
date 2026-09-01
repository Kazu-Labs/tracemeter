from tracemeter.cli import build_parser


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
