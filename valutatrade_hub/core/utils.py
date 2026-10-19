"""Валидация, атомарная запись JSON и кэширование курсов."""

import json
import math
import os
import re
import tempfile
import time
from pathlib import Path


def currency_code(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{2,10}", value):
        raise ValueError("Код валюты должен содержать от 2 до 10 латинских букв")
    return value.upper()


def number(value: float, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("'amount' должен быть положительным числом")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError("Сумма должна быть конечным положительным числом")
    return value


def cached(ttl: float):
    """Замыкание с TTL; исключения не кэшируются."""

    def decorate(function):
        cache = {}

        def wrapped(*args):
            now = time.monotonic()
            if args not in cache or now - cache[args][0] >= ttl:
                cache[args] = (now, function(*args))
            return cache[args][1]

        return wrapped

    return decorate


class JsonStorage:
    """Локальное хранилище для одного работающего экземпляра CLI."""

    def __init__(self, directory: str | Path = "data"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def read(self, name: str, default):
        path = self.directory / name
        if not path.exists():
            return default
        try:
            with path.open(encoding="utf-8") as stream:
                value = json.load(stream)
            if not isinstance(value, type(default)):
                raise ValueError("Некорректная структура JSON")
            return value
        except (ValueError, OSError) as error:
            raise ValueError(f"Не удалось прочитать {path}: {error}") from error

    def write(self, name: str, value) -> None:
        path = self.directory / name
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory, delete=False
            ) as stream:
                temporary = stream.name
                json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
