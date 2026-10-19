"""Бизнес-сценарии приложения без консольного ввода и вывода."""

import logging
import time
from datetime import UTC, datetime
from functools import wraps

from .models import Portfolio, User, Wallet
from .rates import RateService
from .utils import JsonStorage, currency_code, number


def logged_action(function):
    """Логирует операцию и длительность без паролей и аргументов."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = function(*args, **kwargs)
        except Exception:
            logging.getLogger(__name__).info("%s failed", function.__name__)
            raise
        logging.getLogger(__name__).info(
            "%s success %.6fs", function.__name__, time.perf_counter() - start
        )
        return result

    return wrapped


class WalletService:
    def __init__(self, directory="data", *, rates=None):
        self.storage = JsonStorage(directory)
        self.rates = rates or RateService(self.storage)
        self.current_user = None
        for name, default in (
            ("users.json", []),
            ("portfolios.json", []),
            ("rates.json", {}),
        ):
            if not (self.storage.directory / name).exists():
                self.storage.write(name, default)

    @logged_action
    def register(self, username, password):
        users = self.storage.read("users.json", [])
        user_id = max((item["user_id"] for item in users), default=0) + 1
        user = User(user_id, username, "pending", "pending", datetime.now(UTC))
        if any(item["username"] == user.username for item in users):
            raise ValueError(f"Имя пользователя '{user.username}' уже занято")
        user.change_password(password)
        portfolio = Portfolio(user_id, {"USD": Wallet("USD", 10_000)}, user=user)
        portfolios = self.storage.read("portfolios.json", [])
        old_portfolios = portfolios.copy()
        portfolios.append(portfolio.to_dict())
        self.storage.write("portfolios.json", portfolios)
        try:
            self.storage.write("users.json", [*users, user.to_dict()])
        except OSError:
            self.storage.write("portfolios.json", old_portfolios)
            raise
        return user.get_user_info()

    @logged_action
    def login(self, username, password):
        for record in self.storage.read("users.json", []):
            if record["username"] == username:
                user = User.from_dict(record)
                if not user.verify_password(password):
                    raise ValueError("Неверный пароль")
                self.current_user = user
                return user.get_user_info()
        raise ValueError(f"Пользователь '{username}' не найден")

    def logout(self):
        self.current_user = None

    def _require_login(self):
        if self.current_user is None:
            raise ValueError("Сначала выполните login")
        return self.current_user

    def _load_portfolio(self):
        user = self._require_login()
        records = self.storage.read("portfolios.json", [])
        for record in records:
            if record["user_id"] == user.user_id:
                portfolio = Portfolio(
                    user.user_id,
                    {
                        code: Wallet(code, item["balance"])
                        for code, item in record["wallets"].items()
                    },
                    user=user,
                    rate_provider=self.rates.get_rate,
                )
                return portfolio, records, record
        raise ValueError("Портфель пользователя не найден")

    def show_portfolio(self, base="USD"):
        portfolio, _, _ = self._load_portfolio()
        base = currency_code(base)
        try:
            self.rates.get_rate(base, "USD")
        except ValueError as error:
            raise ValueError(f"Неизвестная базовая валюта '{base}'") from error
        rows = []
        sources = set()
        for code, wallet in portfolio.wallets.items():
            rate = self.rates.get_rate(code, base)
            sources.add(rate.get("source", "Локальный кеш"))
            rows.append(
                {
                    "currency": code,
                    "balance": wallet.balance,
                    "value": wallet.balance * rate["rate"],
                }
            )
        return {
            "username": portfolio.user.username,
            "base": base,
            "wallets": rows,
            "total": sum(row["value"] for row in rows),
            "sources": sorted(sources),
        }

    def get_rate(self, source, target):
        return self.rates.get_rate(source, target)

    @logged_action
    def buy(self, currency, amount):
        return self._trade("buy", currency, amount)

    @logged_action
    def sell(self, currency, amount):
        return self._trade("sell", currency, amount)

    def _trade(self, operation, currency, amount):
        portfolio, records, record = self._load_portfolio()
        code, amount = currency_code(currency), number(amount)
        if code == "USD":
            raise ValueError(
                "USD — расчётная валюта. Выберите другую валюту для сделки."
            )
        rate = self.rates.get_rate(code, "USD")
        cost = number(amount * rate["rate"])
        before = portfolio.wallets[code].balance if code in portfolio.wallets else 0.0
        if operation == "buy":
            usd = portfolio.get_wallet("USD")
            usd.withdraw(cost)
            wallet = (
                portfolio.get_wallet(code)
                if code in portfolio.wallets
                else portfolio.add_currency(code)
            )
            wallet.deposit(amount)
        else:
            wallet = portfolio.get_wallet(code)
            wallet.withdraw(amount)
            usd = (
                portfolio.get_wallet("USD")
                if "USD" in portfolio.wallets
                else portfolio.add_currency("USD")
            )
            usd.deposit(cost)
        transaction = {
            "operation": operation,
            "currency": code,
            "amount": amount,
            "rate": rate["rate"],
            "cost": cost,
            "before": before,
            "after": wallet.balance,
            "usd_balance": usd.balance,
            "timestamp": datetime.now(UTC).isoformat(),
            "source": rate.get("source", "Локальный кеш"),
        }
        record.update(portfolio.to_dict())
        record.setdefault("transactions", []).append(transaction)
        self.storage.write("portfolios.json", records)
        return transaction

    def history(self):
        _, _, record = self._load_portfolio()
        return list(record.get("transactions", []))
