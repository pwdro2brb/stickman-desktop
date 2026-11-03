import pytest

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


@pytest.mark.parametrize("command", ["listar janelas", "Janelas visíveis!", "ver janelas"])
def test_parse_window_list(command):
    assert parse_command(command).action == "list_windows"


@pytest.mark.parametrize("command, action", [
    ("subir na janela", "climb"),
    ("Subir janela!", "climb"),
    ("escalar janela", "climb"),
    ("pular na janela", "climb"),
    ("descer", "descend"),
    ("descer da janela", "descend"),
    ("explorar", "explore"),
    ("passear", "explore"),
    ("seguir mouse", "follow"),
    ("seguir cursor", "follow"),
    ("parar", "stop"),
    ("descansar", "stop"),
    ("acenar", "wave"),
    ("OI!", "wave"),
])
def test_parse_character_interactions(command, action):
    result = parse_command(command)
    assert result.action == action
    assert result.argument == ""


@pytest.mark.parametrize("command, argument", [
    ("andar -500", "-500"),
    ("ANDAR +500", "+500"),
    ("andar 500.5", "500.5"),
    ("andar 500,5", "500.5"),
    ("  andar  -500,25  ", "-500.25"),
    ("andar\t.5", ".5"),
    ("andar zero", "zero"),
    ("andar 5.2.1", "5.2.1"),
])
def test_parse_walk_keeps_signed_coordinates_and_invalid_arguments(command, argument):
    result = parse_command(command)
    assert result.action == "walk"
    assert result.argument == argument


def test_normalize_keeps_its_general_punctuation_rules():
    assert normalize("Andar -500,25!") == "andar 500 25"
