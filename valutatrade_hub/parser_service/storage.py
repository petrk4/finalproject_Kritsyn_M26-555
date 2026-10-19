"""Атомарные история и снимок, дедупликация и межпроцессная блокировка."""

import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.utils import JsonStorage, number
from valutatrade_hub.infra.database import database_operation

from .config import ParserConfig


def utc_time(value):
    """Разобрать ISO-время и привести его к UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def cache_pairs(snapshot):
    """Читает новый формат и старый плоский кэш без учебных значений."""
    pairs = snapshot.get("pairs", snapshot)
    if not isinstance(pairs, dict):
        raise ValueError("Некорректный формат pairs в rates.json")
    return {
        key: value
        for key, value in pairs.items()
        if "_" in key
        and isinstance(value, dict)
        and "rate" in value
        and not str(value.get("source", snapshot.get("source", ""))).startswith("Demo")
    }


@contextmanager
def writer_lock(path, timeout=10):
    """ОС освобождает блокировку при завершении процесса, в том числе аварийном."""
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        start = time.monotonic()
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - start >= timeout:
                    raise OSError("Другой Parser Service занят записью") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ParserStorage:
    """История измерений и атомарный снимок под блокировкой записи."""

    def __init__(self, config=None):
        self.config = config or ParserConfig.from_settings()
        self.rates_path = Path(self.config.RATES_FILE_PATH)
        self.history_path = Path(self.config.HISTORY_FILE_PATH)
        self.rates = JsonStorage(self.rates_path.parent)
        self.history = JsonStorage(self.history_path.parent)

    @database_operation
    def save(self, measurements):
        # Сначала проверяем весь пакет, затем изменяем файлы.
        """Валидировать измерения, дополнить историю и обновить свежие пары снимка."""
        validated = []
        for item in measurements:
            source = get_currency(item["from_currency"]).code
            target = get_currency(item["to_currency"]).code
            timestamp = utc_time(item["timestamp"]).isoformat().replace("+00:00", "Z")
            if not isinstance(item["source"], str) or not item["source"]:
                raise ValueError("Источник котировки не указан")
            validated.append(
                {
                    **item,
                    "rate": number(item["rate"]),
                    "timestamp": timestamp,
                    "from_currency": source,
                    "to_currency": target,
                    "id": f"{source}_{target}_{timestamp}",
                }
            )
        with writer_lock(self.rates_path.with_suffix(".lock")):
            history = self.history.read(self.history_path.name, [])
            snapshot = self.rates.read(self.rates_path.name, {})
            pairs = cache_pairs(snapshot)
            ids = {item["id"] for item in history}
            for item in validated:
                if item["id"] not in ids:
                    history.append(item)
                    ids.add(item["id"])
            changed = set()
            # Восстановление снимка из истории помогает после сбоя между записями.
            for item in history:
                key = f"{item['from_currency']}_{item['to_currency']}"
                previous = pairs.get(key)
                if previous is None or utc_time(item["timestamp"]) > utc_time(
                    previous["updated_at"]
                ):
                    pairs[key] = {
                        "rate": item["rate"],
                        "updated_at": item["timestamp"],
                        "source": item["source"],
                    }
                    changed.add(key)
            refreshed = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.history.write(self.history_path.name, history)
            self.rates.write(
                self.rates_path.name, {"pairs": pairs, "last_refresh": refreshed}
            )
            return {
                "updated": len(changed),
                "last_refresh": refreshed,
                "history_count": len(history),
            }
