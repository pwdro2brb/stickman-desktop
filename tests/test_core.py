from stickman_desktop.core import normalize, parse_command


def test_normalize_accents():
    assert normalize("História!") == "historia"


def test_parse_open():
    result = parse_command("Abrir calculadora")
    assert result.action == "open"
    assert result.argument == "calculadora"


def test_parse_walk():
    result = parse_command("andar 500")
    assert result.action == "walk"
    assert result.argument == "500"


def test_unknown_command():
    assert parse_command("faça café").action == "unknown"
