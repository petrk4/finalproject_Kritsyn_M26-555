"""Бизнес-сценарии приложения без консольного ввода и вывода."""

from datetime import UTC, datetime

from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager, database_operation
from valutatrade_hub.infra.settings import SettingsLoader

from .currencies import get_currency
from .exceptions import InsufficientFundsError
from .models import Portfolio, User, Wallet
from .rates import RateService
from .utils import number


class WalletService:
    def __init__(self, directory=None, *, rates=None):
        self.settings = SettingsLoader()
        self.database = DatabaseManager()
        self.storage = self.database.for_directory(directory)
        self.rates = rates or RateService(self.storage)
        self.current_user = None
        self._initialize_storage()

    @database_operation
    def _initialize_storage(self):
        for name, default in (
            ("users.json", []),
            ("portfolios.json", []),
        ):
            if not self.storage.exists(name):
                self.storage.write(name, default)

    @log_action
    @database_operation
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

    @log_action
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

    def show_portfolio(self, base=None):
        portfolio, _, _ = self._load_portfolio()
        base = get_currency(
            base if base is not None else self.settings.get("DEFAULT_BASE_CURRENCY")
        ).code
        self.rates.get_rate(base, "USD")
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

    @log_action
    def get_rate(self, source, target):
        return self.rates.get_rate(source, target)

    def update_rates(self, source=None):
        from valutatrade_hub.parser_service.updater import RatesUpdater

        return RatesUpdater.create(self.storage.directory, source).run_update()

    def show_rates(self, currency=None, top=None, base="USD"):
        return self.rates.show_rates(currency, top, base)

    @log_action(verbose=True)
    def buy(self, currency, amount):
        return self._trade("buy", currency, amount)

    @log_action(verbose=True)
    def sell(self, currency, amount):
        return self._trade("sell", currency, amount)

    @database_operation
    def _trade(self, operation, currency, amount):
        portfolio, records, record = self._load_portfolio()
        code, amount = get_currency(currency).code, number(amount)
        if code == "USD":
            raise ValueError(
                "USD — расчётная валюта. Выберите другую валюту для сделки."
            )
        rate = self.rates.get_rate(code, "USD")
        cost = number(amount * rate["rate"])
        before = portfolio.wallets[code].balance if code in portfolio.wallets else 0.0
        if operation == "buy":
            if "USD" not in portfolio.wallets:
                raise InsufficientFundsError(0.0, cost, "USD")
            usd = portfolio.get_wallet("USD")
            usd.withdraw(cost)
            wallet = (
                portfolio.get_wallet(code)
                if code in portfolio.wallets
                else portfolio.add_currency(code)
            )
            wallet.deposit(amount)
        else:
            if code not in portfolio.wallets:
                raise InsufficientFundsError(0.0, amount, code)
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
