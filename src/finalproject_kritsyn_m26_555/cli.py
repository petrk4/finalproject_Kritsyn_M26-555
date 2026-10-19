"""Базовый интерфейс приложения; операции кошелька добавляются отдельно."""

import argparse
import shlex
from importlib.metadata import version

from prettytable import PrettyTable


class WalletApplication:
    """Управляет интерактивным циклом консольного приложения."""

    def show_help(self) -> None:
        table = PrettyTable(["Команда", "Описание"])
        table.align = "l"
        table.add_row(["help", "Показать доступные команды"])
        table.add_row(["exit / quit", "Завершить работу"])
        print(table)

    def run(self) -> None:
        print("Валютный кошелёк. Введите help для справки.")
        while True:
            try:
                tokens = shlex.split(input("wallet> "))
            except (EOFError, KeyboardInterrupt):
                print("\nДо свидания!")
                return
            except ValueError as error:
                print(f"Ошибка ввода: {error}")
                continue

            if not tokens:
                continue
            if tokens in (["exit"], ["quit"]):
                print("До свидания!")
                return
            if tokens == ["help"]:
                self.show_help()
            else:
                print("Неизвестная команда или лишние аргументы. Введите help.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Консольный валютный кошелёк")
    parser.add_argument(
        "--version",
        action="version",
        version=version("finalproject_Kritsyn_M26-555"),
    )
    parser.parse_args()
    WalletApplication().run()
