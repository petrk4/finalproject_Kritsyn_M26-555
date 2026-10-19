"""Singleton-менеджер JSON и блокировка read–modify–write внутри процесса."""

from contextlib import contextmanager
from functools import wraps
from threading import RLock

from valutatrade_hub.core.utils import JsonStorage

from .settings import SettingsLoader


class ManagedStorage(JsonStorage):
    def __init__(self, directory, filenames, lock):
        super().__init__(directory)
        self._filenames, self._lock = filenames, lock

    def read(self, name, default):
        with self._lock:
            return super().read(self._filenames.get(name, name), default)

    def write(self, name, value):
        with self._lock:
            return super().write(self._filenames.get(name, name), value)

    def exists(self, name):
        return (self.directory / self._filenames.get(name, name)).exists()


class DatabaseManager:
    _instance = None
    _creation_lock = RLock()

    # Простой __new__ обеспечивает один менеджер даже при повторных импортах.
    def __new__(cls):
        with cls._creation_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._lock = RLock()
                cls._instance = instance
            return cls._instance

    def for_directory(self, directory=None):
        settings = SettingsLoader()
        names = {
            "users.json": settings.get("USERS_FILE"),
            "portfolios.json": settings.get("PORTFOLIOS_FILE"),
            "rates.json": settings.get("RATES_FILE"),
        }
        return ManagedStorage(
            directory if directory is not None else settings.get("DATA_DIR"),
            names,
            self._lock,
        )

    @contextmanager
    def transaction(self):
        """Сериализация операции; атомарность файлов обеспечивает JsonStorage.

        Это не откат нескольких файлов и не межпроцессная блокировка.
        """
        with self._lock:
            yield


def database_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with DatabaseManager().transaction():
            return function(*args, **kwargs)

    return wrapped
