"""Отдельный процесс парсера: разовый запуск или периодический цикл."""

import argparse
import logging
from threading import Event

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import number
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_parser_logging

from .config import ParserConfig
from .updater import LOGGER_NAME, RatesUpdater


def run_scheduler(updater, interval, stop_event=None):
    interval = number(interval)
    stop_event = stop_event or Event()
    while not stop_event.is_set():
        try:
            updater.run_update()
        except (ApiRequestError, ValueError, OSError):
            logging.getLogger(LOGGER_NAME).error(
                "Scheduled update failed; retry next interval"
            )
        if stop_event.wait(interval):
            break


def main():
    parser = argparse.ArgumentParser(description="Parser Service валютных курсов")
    parser.add_argument("--once", action="store_true", help="одно обновление и выход")
    parser.add_argument("--interval", type=float, help="секунды между обновлениями")
    parser.add_argument("--source", choices=("coingecko", "exchangerate"))
    parser.add_argument("--data-dir")
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        if args.config:
            SettingsLoader().reload(args.config)
        setup_parser_logging()
        updater = RatesUpdater.create(args.data_dir, args.source)
        if args.once:
            result = updater.run_update()
            print(
                f"Обновлено курсов: {result['updated']}. "
                f"Время: {result['last_refresh']}"
            )
            if result["errors"]:
                print("Частичное обновление: " + "; ".join(result["errors"]))
                return 1
        else:
            interval = (
                args.interval
                if args.interval is not None
                else ParserConfig.from_settings().UPDATE_INTERVAL_SECONDS
            )
            run_scheduler(updater, interval)
    except KeyboardInterrupt:
        print("Parser Service остановлен")
    except (ValueError, OSError) as error:
        parser.exit(1, f"Ошибка: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
