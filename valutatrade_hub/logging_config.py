"""JSON Lines, UTC, ротация по размеру; отдельный logger приложения."""

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .infra.settings import SettingsLoader

LOGGER_NAME = "valutatrade.actions"


class ActionFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            **getattr(record, "action_data", {"message": record.getMessage()}),
        }
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def setup_logging(settings=None):
    settings = settings or SettingsLoader()
    path = Path(settings.get("LOG_FILE")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    handler = RotatingFileHandler(
        path,
        maxBytes=settings.get("LOG_MAX_BYTES"),
        backupCount=settings.get("LOG_BACKUP_COUNT"),
        encoding="utf-8",
    )
    handler.setFormatter(ActionFormatter())
    # Повторная настройка не дублирует строки и закрывает прежний файл.
    for previous in logger.handlers[:]:
        logger.removeHandler(previous)
        previous.close()
    logger.addHandler(handler)
    logger.setLevel(settings.get("LOG_LEVEL"))
    logger.propagate = False
    return logger
