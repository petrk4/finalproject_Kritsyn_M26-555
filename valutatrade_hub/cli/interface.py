"""Разбор пользовательских команд и представление результатов."""

import argparse
import shlex
from functools import wraps
from importlib.metadata import version

from prettytable import PrettyTable

from valutatrade_hub.core.currencies import CURRENCIES
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
)
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import setup_logging


class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def confirmed(function):
    """Подтверждает сделку; --yes подходит для сценариев без диалога."""

    @wraps(function)
    def wrapped(self, args):
        if not args.yes:
            answer = input("Подтвердить виртуальную сделку? [y/N]: ").strip().lower()
            if answer not in {"y", "yes", "д", "да"}:
                print("Операция отменена")
                return
        return function(self, args)

    return wrapped


def command_parser():
    parser = CommandParser(prog="wallet", description="Команды валютного кошелька")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("register", "login"):
        command = commands.add_parser(name)
        command.add_argument("--username", required=True)
        command.add_argument("--password", required=True)
    command = commands.add_parser("show-portfolio")
    command.add_argument("--base", default=None)
    for name in ("buy", "sell"):
        command = commands.add_parser(name)
        command.add_argument("--currency", required=True)
        command.add_argument("--amount", type=float, required=True)
        command.add_argument("--yes", action="store_true", help="без подтверждения")
    command = commands.add_parser("get-rate")
    command.add_argument("--from", dest="source", required=True)
    command.add_argument("--to", dest="target", required=True)
    for name in ("help", "history", "logout", "exit", "quit", "currencies"):
        commands.add_parser(name)
    return parser


class WalletApplication:
    def __init__(self, service=None):
        self.service = service or WalletService()
        self.parser = command_parser()

    @confirmed
    def trade(self, args):
        result = getattr(self.service, args.command)(args.currency, args.amount)
        label = "Покупка" if args.command == "buy" else "Продажа"
        print(f"{label} выполнена: {result['amount']:.8f} {result['currency']}")
        print(f"Курс: {result['rate']:.8f} USD/{result['currency']}")
        print(f"Баланс: {result['before']:.8f} → {result['after']:.8f}")
        print(f"Стоимость: {result['cost']:.2f} USD")
        print(f"Баланс USD: {result['usd_balance']:.2f}")
        print(f"Источник: {result['source']}")

    def execute(self, line):
        tokens = shlex.split(line)
        if not tokens:
            return True
        args = self.parser.parse_args(tokens)
        match args.command:
            case "exit" | "quit":
                return False
            case "help":
                self.parser.print_help()
                print("Подробная справка: <команда> --help")
            case "currencies":
                for currency in CURRENCIES.values():
                    print(currency.get_display_info())
                print("Капитализация криптовалют — учебные данные.")
            case "register":
                user = self.service.register(args.username, args.password)
                print(
                    f"Пользователь '{user['username']}' зарегистрирован "
                    f"(id={user['user_id']}). Начальный баланс: 10 000 USD."
                )
                print("Войдите: login --username <имя> --password <пароль>")
            case "login":
                user = self.service.login(args.username, args.password)
                print(f"Вы вошли как '{user['username']}'")
            case "logout":
                self.service.logout()
                print("Вы вышли из учётной записи")
            case "show-portfolio":
                result = self.service.show_portfolio(args.base)
                print(
                    f"Портфель пользователя '{result['username']}' "
                    f"(база: {result['base']}):"
                )
                table = PrettyTable(
                    ["Валюта", "Баланс", f"Стоимость, {result['base']}"]
                )
                for row in result["wallets"]:
                    table.add_row(
                        [
                            row["currency"],
                            f"{row['balance']:.8f}",
                            f"{row['value']:.2f}",
                        ]
                    )
                print(table if result["wallets"] else "Портфель пуст")
                print(f"ИТОГО: {result['total']:,.2f} {result['base']}")
                print("Источники: " + ", ".join(result["sources"]))
            case "buy" | "sell":
                self.trade(args)
            case "get-rate":
                rate = self.service.get_rate(args.source, args.target)
                print(
                    f"Курс {args.source.upper()}→{args.target.upper()}: "
                    f"{rate['rate']:.8f} (обновлено: {rate['updated_at']})"
                )
                print(f"Обратный курс: {1 / rate['rate']:.8f}")
                print(f"Источник: {rate.get('source', 'Локальный кеш')}")
            case "history":
                table = PrettyTable(
                    ["Время", "Операция", "Валюта", "Количество", "USD"]
                )
                history = self.service.history()
                for item in history:
                    table.add_row(
                        [
                            item["timestamp"],
                            item["operation"],
                            item["currency"],
                            item["amount"],
                            f"{item['cost']:.2f}",
                        ]
                    )
                print(table if history else "История сделок пуста")
        return True

    def run(self):
        print("Валютный кошелёк. Курсы по умолчанию учебные. Введите help.")
        while True:
            try:
                if not self.execute(input("wallet> ")):
                    break
            except (EOFError, KeyboardInterrupt):
                print()
                break
            except SystemExit:
                continue
            except InsufficientFundsError as error:
                print(error)
            except CurrencyNotFoundError as error:
                print(error)
                print("Поддерживаемые валюты: " + ", ".join(CURRENCIES))
                print("Справка: get-rate --help")
            except ApiRequestError as error:
                print(error)
                print("Повторите позже или проверьте подключение к сети.")
            except (ValueError, OSError, KeyError, TypeError) as error:
                print(f"Ошибка: {error}")
        print("До свидания!")


def main():
    parser = argparse.ArgumentParser(description="Консольный валютный кошелёк")
    parser.add_argument(
        "--version", action="version", version=version("finalproject_Kritsyn_M26-555")
    )
    parser.add_argument(
        "--data-dir", default=None, help="каталог локальных JSON-файлов"
    )
    parser.add_argument("--config", help="путь к pyproject.toml или config.json")
    args = parser.parse_args()
    try:
        settings = SettingsLoader()
        if args.config:
            settings.reload(args.config)
        setup_logging(settings)
        service = WalletService(args.data_dir)
        WalletApplication(service).run()
    except (ValueError, OSError) as error:
        parser.exit(1, f"Ошибка запуска: {error}\n")
