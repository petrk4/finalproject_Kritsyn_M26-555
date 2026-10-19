"""Ленивая загрузка настроек из [tool.valutatrade] или config.json."""

import json
import logging
import math
import tomllib
from pathlib import Path
from threading import RLock

DEFAULTS = {
    "DATA_DIR": "data",
    "USERS_FILE": "users.json",
    "PORTFOLIOS_FILE": "portfolios.json",
    "RATES_FILE": "rates.json",
    "RATES_TTL_SECONDS": 300,
    "DEFAULT_BASE_CURRENCY": "USD",
    "LOG_FILE": "logs/actions.log",
    "LOG_FORMAT": "json",
    "LOG_LEVEL": "INFO",
    "LOG_MAX_BYTES": 1_048_576,
    "LOG_BACKUP_COUNT": 3,
    "PARSER_LOG_FILE": "logs/parser.log",
    "HISTORY_FILE": "exchange_rates.json",
    "REQUEST_TIMEOUT": 10,
    "UPDATE_INTERVAL_SECONDS": 3600,
}


class SettingsLoader:
    """Единственный кэш настроек с безопасной перезагрузкой."""

    _instance = None
    _lock = RLock()

    # __new__ выбран ради простоты: создание единственного объекта явно видно,
    # метакласс не нужен. Импорт модуля не создаёт экземпляр и не читает файлы.
    def __new__(cls):
        """Создать настройки один раз, включая при одновременных вызовах."""
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._values = {}
                instance._path = None
                instance.reload()
                cls._instance = instance
            return cls._instance

    def get(self, key, default=None):
        """Вернуть значение настройки или переданное значение по умолчанию."""
        with self._lock:
            return self._values.get(key, default)

    def reload(self, path=None):
        """Атомарно обновить настройки; ошибка сохраняет предыдущие значения."""
        with self._lock:
            selected = Path(path) if path is not None else self._path
            if selected is None:
                selected = Path("pyproject.toml")
            values = DEFAULTS.copy()
            if selected.exists():
                with selected.open("rb") as stream:
                    if selected.suffix == ".json":
                        overrides = json.load(stream)
                    else:
                        overrides = (
                            tomllib.load(stream).get("tool", {}).get("valutatrade", {})
                        )
                if not isinstance(overrides, dict):
                    raise ValueError("Настройки должны быть объектом")
                values.update(overrides)
            elif path is not None:
                raise ValueError(f"Файл настроек не найден: {selected}")
            self._validate(values)
            self._values, self._path = values, selected

    @staticmethod
    def _validate(values):
        for key in ("DATA_DIR", "LOG_FILE", "PARSER_LOG_FILE"):
            if not isinstance(values[key], str) or not values[key].strip():
                raise ValueError(f"Некорректная настройка {key}")
        for key in ("USERS_FILE", "PORTFOLIOS_FILE", "RATES_FILE", "HISTORY_FILE"):
            value = values[key]
            if (
                not isinstance(value, str)
                or not value
                or value in {".", ".."}
                or "/" in value
                or "\\" in value
                or ":" in value
            ):
                raise ValueError(f"{key} должен быть именем файла внутри DATA_DIR")
        if (
            len(
                {
                    values[key].casefold()
                    for key in (
                        "USERS_FILE",
                        "PORTFOLIOS_FILE",
                        "RATES_FILE",
                        "HISTORY_FILE",
                    )
                }
            )
            != 4
        ):
            raise ValueError("Имена JSON-файлов должны различаться")
        ttl = values["RATES_TTL_SECONDS"]
        if (
            isinstance(ttl, bool)
            or not isinstance(ttl, (int, float))
            or not math.isfinite(ttl)
            or ttl < 0
        ):
            raise ValueError("RATES_TTL_SECONDS должен быть конечным числом >= 0")
        for key in ("LOG_MAX_BYTES", "LOG_BACKUP_COUNT"):
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{key} должен быть положительным целым числом")
        if values["LOG_FORMAT"] != "json":
            raise ValueError("Поддерживается LOG_FORMAT=json")
        if values["LOG_LEVEL"] not in logging.getLevelNamesMapping():
            raise ValueError("Неизвестный LOG_LEVEL")
        from valutatrade_hub.core.currencies import get_currency

        get_currency(values["DEFAULT_BASE_CURRENCY"])
