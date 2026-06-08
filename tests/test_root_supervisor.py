import main


def test_root_launcher_has_no_src_imports():
    source = open(main.__file__, encoding="utf-8").read()
    assert "from " + "src" not in source
    assert "import " + "src" not in source


def test_parser_supports_required_modes():
    parser = main.build_parser()
    for command in ["run", "backend-only", "frontend-only", "healthcheck", "shutdown"]:
        args = parser.parse_args([command])
        assert args.command == command
