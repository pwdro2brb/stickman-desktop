from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalize(text: object) -> str:
    value = "" if text is None else str(text)
    value = "".join(
        char for char in unicodedata.normalize("NFD", value)
        if unicodedata.category(char) != "Mn"
    )
    value = re.sub(r"[^A-Za-z0-9 ]+", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class ParsedCommand:
    action: str
    argument: str = ""


def parse_command(text: str) -> ParsedCommand:
    command = normalize(text)
    if not command:
        return ParsedCommand("empty")
    if command.startswith("andar "):
        return ParsedCommand("walk", command.removeprefix("andar ").strip())
    if command in {"pular", "pule"}:
        return ParsedCommand("jump")
    if command in {"olhar tela", "analisar tela", "janela ativa"}:
        return ParsedCommand("inspect")
    if command in {"minimizar", "minimizar janela"}:
        return ParsedCommand("minimize")
    if command.startswith("abrir "):
        return ParsedCommand("open", command.removeprefix("abrir ").strip())
    if command in {"historia", "luta"}:
        return ParsedCommand("story")
    if command in {"portal", "entrar no portal"}:
        return ParsedCommand("portal")
    if command in {"ajuda", "comandos"}:
        return ParsedCommand("help")
    return ParsedCommand("unknown", command)
