"""Записать настоящий вывод CLI в asciicast v2 с фиксированными HTTP-ответами."""

import argparse
import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from valutatrade_hub.cli.interface import WalletApplication
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import ParserStorage
from valutatrade_hub.parser_service.updater import RatesUpdater

COMMANDS = (
    "register --username demo --password demo1234",
    "login --username demo --password demo1234",
    "update-rates",
    "show-rates --top 2",
    "buy --currency BTC --amount 0.01 --yes",
    "sell --currency BTC --amount 0.005 --yes",
    "show-portfolio",
    "get-rate --from USD --to BTC",
    "sell --currency BTC --amount 1 --yes",
    "get-rate --from ABC --to USD",
    "show-rates --currency RUB",
    "history",
    "exit",
)


def fake_get(url, **kwargs):
    """Вернуть фикстуру HTTP; сеть и реальные ключи не используются."""
    if "coingecko" in url:
        payload = {
            "bitcoin": {"usd": 60000},
            "ethereum": {"usd": 3000},
            "solana": {"usd": 150},
        }
    else:
        payload = {
            "result": "success",
            "base_code": "USD",
            "conversion_rates": {"EUR": 0.8, "GBP": 0.5, "RUB": 100},
        }
    response = Mock(status_code=200, headers={})
    response.json.return_value = payload
    return response


def record_session():
    """Исполнить сценарий с временным портфелем и вернуть реальный stdout."""
    output = io.StringIO()
    with tempfile.TemporaryDirectory() as directory:
        config = ParserConfig(
            EXCHANGERATE_API_KEY="demo-placeholder",
            COINGECKO_API_KEY="",
            RATES_FILE_PATH=str(Path(directory) / "rates.json"),
            HISTORY_FILE_PATH=str(Path(directory) / "exchange_rates.json"),
        )
        session = Mock()
        session.get.side_effect = fake_get
        updater = RatesUpdater(
            [CoinGeckoClient(config, session), ExchangeRateApiClient(config, session)],
            ParserStorage(config),
        )
        commands = iter(COMMANDS)

        def read_command(prompt):
            command = next(commands)
            print(prompt + command)
            return command

        service = WalletService(directory)
        with (
            redirect_stdout(output),
            patch("builtins.input", side_effect=read_command),
            patch.object(RatesUpdater, "create", return_value=updater),
        ):
            print("DEMO: фиксированные HTTP-ответы; котировки не рыночные.")
            print("CLI, API-клиенты, хранилище и операции выполняются настоящим кодом.")
            WalletApplication(service).run()
        history = service.history()
        if len(history) != 2 or history[-1]["usd_balance"] != 9700:
            raise RuntimeError("Демосценарий завершился с неверным результатом")
    transcript = output.getvalue()
    for expected in (
        "Обновлено курсов: 6",
        "Недостаточно средств",
        "Неизвестная валюта",
    ):
        if expected not in transcript:
            raise RuntimeError(f"Демо не содержит ожидаемое сообщение: {expected}")
    return transcript


def main():
    """Сохранить ответы целыми блоками, оставив паузы только перед командами."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/demo.cast"))
    args = parser.parse_args()
    transcript = record_session()
    shell_prompt = f"PS {Path.cwd()}> "
    blocks = transcript.split("wallet> ")
    opening = shell_prompt + "uv run python -m tools.record_demo\n" + blocks[0]
    events = [[0.0, "o", opening.replace("\n", "\r\n") + "wallet> "]]
    elapsed = 0.0
    for index, block in enumerate(blocks[1:]):
        elapsed += 3.0
        prompt = "wallet> " if index < len(blocks) - 2 else shell_prompt
        events.append([elapsed, "o", block.replace("\n", "\r\n") + prompt])
    elapsed += 2.0
    events.append([elapsed, "o", ""])
    header = {
        "version": 2,
        "width": 132,
        "height": 32,
        "title": "ValutaTrade Hub — offline API fixtures",
        "duration": elapsed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in [header, *events])
        + "\n",
        encoding="utf-8",
    )
    print(f"Демо записано: {args.output} ({elapsed:.1f} с)")


if __name__ == "__main__":
    main()
