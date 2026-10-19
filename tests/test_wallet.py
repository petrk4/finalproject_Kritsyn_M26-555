"""Проверки денежных операций, хранения, авторизации и кэша."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from valutatrade_hub.cli.interface import WalletApplication
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.rates import RateService
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.core.utils import JsonStorage, cached


class ModelTests(unittest.TestCase):
    def test_password_change(self):
        user = User(1, " alice ", "hash", "salt", datetime.now(UTC))
        user.change_password("1234")
        old_salt = user.salt
        self.assertTrue(user.verify_password("1234"))
        user.change_password("5678")
        self.assertNotEqual(old_salt, user.salt)
        self.assertFalse(user.verify_password("1234"))
        self.assertTrue(user.verify_password("5678"))
        self.assertNotIn("salt", user.get_user_info())
        self.assertNotIn("hashed_password", user.get_user_info())
        with self.assertRaises(ValueError):
            user.change_password("123")
        with self.assertRaises(ValueError):
            user.username = " "

    def test_wallet_validation(self):
        wallet = Wallet("btc", 1)
        for invalid in (True, "1", None, -1, float("inf"), float("nan")):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    wallet.balance = invalid
                with self.assertRaises(ValueError):
                    wallet.deposit(invalid)
        with self.assertRaises(ValueError):
            wallet.withdraw(2)
        with self.assertRaises(ValueError):
            wallet.deposit(0)
        wallet.withdraw(1)
        self.assertEqual(wallet.balance, 0)
        self.assertEqual(wallet.currency_code, "BTC")

    def test_portfolio(self):
        user = User(1, "alice", "hash", "salt", datetime.now(UTC))

        def rate(source, target):
            return {"rate": {"USD": 1, "EUR": 2}[source]}

        portfolio = Portfolio(1, user=user, rate_provider=rate)
        portfolio.add_currency("EUR").deposit(5)
        portfolio.add_currency("USD").deposit(10)
        self.assertEqual(portfolio.get_total_value(), 20)
        self.assertIs(portfolio.user, user)
        portfolio.wallets.clear()
        self.assertEqual(len(portfolio.wallets), 2)
        with self.assertRaises(ValueError):
            portfolio.add_currency("eur")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.service = WalletService(self.directory)
        self.service.register("alice", "1234")

    def login(self):
        self.service.login("alice", "1234")

    def test_registration_and_login(self):
        with self.assertRaisesRegex(ValueError, "занято"):
            self.service.register("alice", "5678")
        with self.assertRaisesRegex(ValueError, "пароль"):
            self.service.login("alice", "bad")
        with self.assertRaisesRegex(ValueError, "не найден"):
            self.service.login("bob", "1234")
        self.login()
        self.assertEqual(self.service.show_portfolio()["total"], 10000)
        self.assertNotIn('"password"', (self.directory / "users.json").read_text())
        self.service.logout()
        with self.assertRaisesRegex(ValueError, "login"):
            self.service.show_portfolio()

    def test_auth_required(self):
        for operation in (self.service.buy, self.service.sell):
            with self.assertRaisesRegex(ValueError, "login"):
                operation("BTC", 0.01)

    def test_trade_and_restart(self):
        self.login()
        result = self.service.buy("btc", 0.05)
        self.assertAlmostEqual(result["usd_balance"], 10000 - 0.05 * 59337.21)
        self.assertAlmostEqual(self.service.show_portfolio()["total"], 10000)
        self.service.sell("BTC", 0.02)
        restarted = WalletService(self.directory)
        restarted.login("alice", "1234")
        self.assertEqual(len(restarted.history()), 2)
        balances = {
            row["currency"]: row["balance"]
            for row in restarted.show_portfolio()["wallets"]
        }
        self.assertAlmostEqual(balances["BTC"], 0.03)
        self.assertAlmostEqual(balances["USD"], 10000 - 0.03 * 59337.21)

    def test_failed_trades_do_not_change_portfolio(self):
        self.login()
        path = self.directory / "portfolios.json"
        before = path.read_bytes()
        for operation, code, amount in (
            ("buy", "BTC", 1),
            ("sell", "BTC", 1),
            ("buy", "USD", 1),
            ("buy", "ABC", 1),
            ("buy", "BTC", 0),
            ("buy", "BTC", -1),
            ("buy", "BTC", float("nan")),
            ("sell", "BTC", float("inf")),
        ):
            with self.subTest(operation=operation, code=code, amount=amount):
                with self.assertRaises(ValueError):
                    getattr(self.service, operation)(code, amount)
                self.assertEqual(path.read_bytes(), before)

    def test_oversell_does_not_change_portfolio(self):
        self.login()
        self.service.buy("BTC", 0.01)
        before = self.service.storage.read("portfolios.json", [])
        with self.assertRaisesRegex(ValueError, "Недостаточно"):
            self.service.sell("BTC", 0.02)
        self.assertEqual(self.service.storage.read("portfolios.json", []), before)

    def test_users_are_isolated(self):
        self.login()
        self.service.buy("EUR", 100)
        self.service.register("bob", "5678")
        self.service.login("bob", "5678")
        self.assertEqual(self.service.history(), [])
        self.assertEqual(len(self.service.show_portfolio()["wallets"]), 1)

    def test_base_currency_and_empty_portfolio(self):
        self.login()
        self.assertAlmostEqual(
            self.service.show_portfolio("EUR")["total"], 10000 / 1.0786
        )
        with self.assertRaisesRegex(ValueError, "Неизвестная"):
            self.service.show_portfolio("ABC")
        self.service.storage.write("portfolios.json", [{"user_id": 1, "wallets": {}}])
        self.assertEqual(self.service.show_portfolio()["total"], 0)

    def test_corrupt_json_is_not_overwritten(self):
        path = self.directory / "users.json"
        path.write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.service.register("bob", "1234")
        self.assertEqual(path.read_text(), "broken")

    def test_write_failure_preserves_balances(self):
        self.login()
        self.service.get_rate("BTC", "USD")
        path = self.directory / "portfolios.json"
        before = path.read_bytes()
        with patch(
            "valutatrade_hub.core.utils.os.replace", side_effect=OSError("disk")
        ):
            with self.assertRaises(OSError):
                self.service.buy("BTC", 0.01)
        self.assertEqual(path.read_bytes(), before)

    def test_cli_and_confirmation(self):
        app = WalletApplication(self.service)
        commands = [
            "login --username alice --password 1234",
            "buy --currency BTC --amount 0.01 --yes",
            "show-portfolio",
            "get-rate --from USD --to BTC",
            "history",
        ]
        with redirect_stdout(io.StringIO()) as output:
            for command in commands:
                self.assertTrue(app.execute(command))
            with patch("builtins.input", return_value="n"):
                app.execute("sell --currency BTC --amount 0.01")
        self.assertIn("отменена", output.getvalue())
        self.assertEqual(len(self.service.history()), 1)
        self.assertFalse(app.execute("exit"))
        with self.assertRaises(ValueError):
            app.execute("buy --amount wrong")


class RateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.storage = JsonStorage(temporary.name)

    def test_fresh_cache_and_expired_refresh(self):
        provider = Mock(
            return_value={
                "rate": 3.0,
                "updated_at": datetime.now(UTC).isoformat(),
                "source": "test",
            }
        )
        self.storage.write(
            "rates.json",
            {"EUR_USD": {"rate": 2.0, "updated_at": datetime.now(UTC).isoformat()}},
        )
        rates = RateService(self.storage, provider=provider)
        self.assertEqual(rates.get_rate("EUR", "USD")["rate"], 2)
        provider.assert_not_called()
        old = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()
        self.storage.write("rates.json", {"EUR_USD": {"rate": 2, "updated_at": old}})
        self.assertEqual(rates.get_rate("EUR", "USD")["rate"], 3)
        provider.assert_called_once()
        self.assertEqual(self.storage.read("rates.json", {})["EUR_USD"]["rate"], 3)

    def test_cross_and_inverse_rates(self):
        rates = RateService(self.storage)
        self.assertAlmostEqual(rates.get_rate("EUR", "BTC")["rate"], 1.0786 / 59337.21)
        self.assertAlmostEqual(
            rates.get_rate("USD", "BTC")["rate"] * rates.get_rate("BTC", "USD")["rate"],
            1,
        )
        self.assertEqual(rates.get_rate("USD", "USD")["rate"], 1)
        with self.assertRaises(ValueError):
            rates.get_rate("ABC", "USD")

    def test_provider_failure(self):
        rates = RateService(self.storage, provider=Mock(side_effect=OSError("offline")))
        with self.assertRaisesRegex(ValueError, "недоступен"):
            rates.get_rate("BTC", "USD")

    def test_local_reverse_and_cross_do_not_use_demo(self):
        now = datetime.now(UTC).isoformat()
        self.storage.write(
            "rates.json",
            {
                "BTC_USD": {"rate": 100000, "updated_at": now},
                "EUR_USD": {"rate": 2, "updated_at": now},
                "source": "ParserService",
            },
        )
        provider = Mock(side_effect=AssertionError("Provider must not run"))
        rates = RateService(self.storage, provider=provider)
        self.assertAlmostEqual(rates.get_rate("USD", "BTC")["rate"], 0.00001)
        self.assertAlmostEqual(rates.get_rate("EUR", "BTC")["rate"], 0.00002)

    def test_closure_cache_expiry(self):
        function = Mock(return_value=42)
        wrapped = cached(300)(function)
        with patch(
            "valutatrade_hub.core.utils.time.monotonic", side_effect=[0, 299, 301]
        ):
            for _ in range(3):
                self.assertEqual(wrapped("key"), 42)
        self.assertEqual(function.call_count, 2)


if __name__ == "__main__":
    unittest.main()
