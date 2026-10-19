"""Контракты валют, исключений, конфигурации и журнала операций."""

import io
import json
import logging
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from valutatrade_hub.cli.interface import WalletApplication
from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    Currency,
    FiatCurrency,
    get_currency,
)
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
)
from valutatrade_hub.core.models import Wallet
from valutatrade_hub.core.rates import RateService
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import LOGGER_NAME, setup_logging


class CurrencyTests(unittest.TestCase):
    def test_abstract_and_display(self):
        with self.assertRaises(TypeError):
            Currency("Dollar", "USD")
        self.assertEqual(
            get_currency("usd").get_display_info(),
            "[FIAT] USD — US Dollar (Issuing: United States)",
        )
        self.assertEqual(
            get_currency("BTC").get_display_info(),
            "[CRYPTO] BTC — Bitcoin (Algo: SHA-256, MCAP: 1.12e12)",
        )

    def test_invariants_and_unknown_code(self):
        for code in ("usd", "A", "ABCDEF", "U SD", "US1", ""):
            with self.subTest(code=code), self.assertRaises(ValueError):
                FiatCurrency("Dollar", code, "USA")
        with self.assertRaises(ValueError):
            FiatCurrency(" ", "USD", "USA")
        with self.assertRaises(ValueError):
            CryptoCurrency("Bitcoin", "BTC", "SHA-256", float("nan"))
        with self.assertRaises(FrozenInstanceError):
            get_currency("USD").code = "bad"
        for code in ("ABC", "", "U SD", None):
            with self.assertRaises(CurrencyNotFoundError):
                get_currency(code)

    def test_insufficient_funds_contract(self):
        wallet = Wallet("USD", 5)
        with self.assertRaises(InsufficientFundsError) as caught:
            wallet.withdraw(6)
        self.assertEqual(
            str(caught.exception),
            "Недостаточно средств: доступно 5.0 USD, требуется 6.0 USD",
        )
        self.assertEqual(wallet.balance, 5)


class InfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.settings = SettingsLoader()
        self.old_values = self.settings._values.copy()
        self.old_path = self.settings._path
        logger = logging.getLogger(LOGGER_NAME)
        self.old_handlers = logger.handlers[:]
        self.old_level, self.old_propagate = logger.level, logger.propagate
        logger.handlers = []
        self.addCleanup(self.cleanup)
        rates_patch = patch(
            "valutatrade_hub.core.usecases.RateService",
            side_effect=lambda storage: RateService(
                storage, provider=RateService._demo_rate
            ),
        )
        rates_patch.start()
        self.addCleanup(rates_patch.stop)

    def cleanup(self):
        logger = logging.getLogger(LOGGER_NAME)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        logger.handlers = self.old_handlers
        logger.setLevel(self.old_level)
        logger.propagate = self.old_propagate
        self.settings._values = self.old_values
        self.settings._path = self.old_path
        self.temporary.cleanup()

    def configure(self, **overrides):
        path = self.directory / "config.json"
        values = {
            "DATA_DIR": str(self.directory / "data"),
            "LOG_FILE": str(self.directory / "actions.log"),
            **overrides,
        }
        path.write_text(json.dumps(values), encoding="utf-8")
        self.settings.reload(path)
        return path

    def test_singletons_and_no_reinitialization(self):
        self.configure(RATES_TTL_SECONDS=42)
        self.assertIs(self.settings, SettingsLoader())
        self.assertIs(DatabaseManager(), DatabaseManager())
        with ThreadPoolExecutor(max_workers=4) as pool:
            instances = list(pool.map(lambda _: SettingsLoader(), range(10)))
        self.assertTrue(all(item is self.settings for item in instances))
        self.assertEqual(SettingsLoader().get("RATES_TTL_SECONDS"), 42)
        self.assertEqual(self.settings.get("missing", "fallback"), "fallback")

    def test_configured_paths_ttl_and_base(self):
        self.configure(
            USERS_FILE="people.json", RATES_TTL_SECONDS=12, DEFAULT_BASE_CURRENCY="EUR"
        )
        service = WalletService()
        service.register("alice", "1234")
        service.login("alice", "1234")
        self.assertTrue((self.directory / "data" / "people.json").exists())
        self.assertFalse((self.directory / "data" / "users.json").exists())
        self.assertEqual(service.rates.ttl, 12)
        self.assertEqual(service.show_portfolio()["base"], "EUR")
        alternate = WalletService(self.directory / "alternate")
        self.assertNotEqual(alternate.storage.directory, service.storage.directory)

    def test_reload_toml_and_invalid_config_preserves_state(self):
        path = self.directory / "project.toml"
        path.write_text(
            "[tool.valutatrade]\nRATES_TTL_SECONDS = 27\n", encoding="utf-8"
        )
        self.settings.reload(path)
        self.assertEqual(self.settings.get("RATES_TTL_SECONDS"), 27)
        path.write_text(
            "[tool.valutatrade]\nRATES_TTL_SECONDS = -1\n", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            self.settings.reload()
        self.assertEqual(self.settings.get("RATES_TTL_SECONDS"), 27)

    def test_parallel_trades_preserve_balances_and_history(self):
        self.configure()
        service = WalletService()
        service.register("alice", "1234")
        sessions = [WalletService() for _ in range(4)]
        for session in sessions:
            session.login("alice", "1234")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda session: session.buy("EUR", 10), sessions))
        service.login("alice", "1234")
        self.assertEqual(len(service.history()), 4)
        rows = {
            row["currency"]: row["balance"]
            for row in service.show_portfolio()["wallets"]
        }
        self.assertEqual(rows["EUR"], 40)
        self.assertAlmostEqual(rows["USD"], 10000 - 40 * 1.0786)

    def test_json_logs_success_error_verbose_no_password(self):
        self.configure()
        setup_logging()
        service = WalletService()
        service.register("alice", "secret-password")
        service.login("alice", "secret-password")
        service.buy(currency="eur", amount=5)
        with self.assertRaises(InsufficientFundsError):
            service.sell("EUR", 6)
        with self.assertRaises(ValueError):
            service.login("alice", "incorrect-secret")
        text = (self.directory / "actions.log").read_text(encoding="utf-8")
        entries = [json.loads(line) for line in text.splitlines()]
        buy = next(row for row in entries if row["action"] == "BUY")
        self.assertEqual(buy["result"], "OK")
        self.assertEqual(buy["currency_code"], "EUR")
        self.assertEqual(buy["amount"], 5)
        self.assertEqual(buy["rate"], 1.0786)
        self.assertEqual(buy["base"], "USD")
        self.assertEqual(buy["username"], "alice")
        self.assertEqual(
            buy["context"],
            {"before": 0.0, "after": 5.0, "usd_balance": 10000 - 5 * 1.0786},
        )
        sell = next(row for row in entries if row["action"] == "SELL")
        self.assertEqual(sell["error_type"], "InsufficientFundsError")
        self.assertEqual(sell["result"], "ERROR")
        self.assertNotIn("secret-password", text)
        self.assertNotIn("incorrect-secret", text)
        self.assertNotIn(service.current_user.salt, text)
        datetime.fromisoformat(buy["timestamp"])

    def test_log_rotation_and_repeat_setup(self):
        self.configure(LOG_MAX_BYTES=600, LOG_BACKUP_COUNT=2)
        logger = setup_logging()
        setup_logging()
        self.assertEqual(len(logger.handlers), 1)
        for _ in range(30):
            logger.info("x" * 100)
        self.assertTrue((self.directory / "actions.log.1").exists())
        self.assertTrue((self.directory / "actions.log.2").exists())
        self.assertFalse((self.directory / "actions.log.3").exists())

    def test_api_and_currency_errors_are_distinct(self):
        self.configure()
        provider = Mock(side_effect=OSError("offline"))
        rates = RateService(provider=provider)
        with self.assertRaises(CurrencyNotFoundError):
            rates.get_rate("ABC", "USD")
        provider.assert_not_called()
        with self.assertRaisesRegex(ApiRequestError, "Ошибка при обращении"):
            rates.get_rate("BTC", "USD")
        stale = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        rates = RateService(
            provider=Mock(return_value={"rate": 1, "updated_at": stale})
        )
        with self.assertRaises(ApiRequestError):
            rates.get_rate("BTC", "USD")

    def test_missing_wallet_raises_insufficient_funds(self):
        self.configure()
        service = WalletService()
        service.register("alice", "1234")
        service.login("alice", "1234")
        with self.assertRaises(InsufficientFundsError) as caught:
            service.sell("BTC", 1)
        self.assertEqual(caught.exception.available, 0)

    def test_cli_special_errors_and_continuation(self):
        self.configure()
        service = WalletService()
        service.get_rate = Mock(
            side_effect=[CurrencyNotFoundError("ABC"), ApiRequestError("offline")]
        )
        app = WalletApplication(service)
        with (
            patch(
                "builtins.input",
                side_effect=[
                    "get-rate --from ABC --to USD",
                    "get-rate --from BTC --to USD",
                    "exit",
                ],
            ),
            redirect_stdout(io.StringIO()) as output,
        ):
            app.run()
        self.assertIn("Поддерживаемые валюты", output.getvalue())
        self.assertIn("проверьте подключение", output.getvalue())
        self.assertIn("До свидания", output.getvalue())
