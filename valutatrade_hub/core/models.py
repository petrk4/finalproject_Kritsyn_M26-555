"""Пользователь, валютный кошелёк и портфель."""

import hashlib
import hmac
import secrets
from datetime import datetime

from .utils import currency_code, number


class User:
    def __init__(self, user_id, username, hashed_password, salt, registration_date):
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ValueError("user_id должен быть положительным целым числом")
        if not isinstance(registration_date, datetime):
            raise ValueError("registration_date должен быть datetime")
        if not isinstance(hashed_password, str) or not hashed_password:
            raise ValueError("Хеш пароля не может быть пустым")
        if not isinstance(salt, str) or not salt:
            raise ValueError("Соль не может быть пустой")
        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @property
    def user_id(self):
        return self._user_id

    @property
    def username(self):
        return self._username

    @username.setter
    def username(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self):
        return self._hashed_password

    @property
    def salt(self):
        return self._salt

    @property
    def registration_date(self):
        return self._registration_date

    def get_user_info(self):
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": self.registration_date.isoformat(),
        }

    def change_password(self, new_password: str):
        if not isinstance(new_password, str) or len(new_password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")
        self._salt = secrets.token_hex(16)
        self._hashed_password = self._hash(new_password)

    def _hash(self, password):
        return hashlib.sha256((password + self.salt).encode()).hexdigest()

    def verify_password(self, password: str):
        return isinstance(password, str) and hmac.compare_digest(
            self._hash(password), self.hashed_password
        )

    def to_dict(self):
        return {
            **self.get_user_info(),
            "hashed_password": self.hashed_password,
            "salt": self.salt,
        }

    @classmethod
    def from_dict(cls, record):
        return cls(
            record["user_id"],
            record["username"],
            record["hashed_password"],
            record["salt"],
            datetime.fromisoformat(record["registration_date"]),
        )


class Wallet:
    def __init__(self, currency_code: str, balance: float = 0.0):
        self.currency_code = currency_code
        self.balance = balance

    @property
    def currency_code(self):
        return self._currency_code

    @currency_code.setter
    def currency_code(self, value):
        self._currency_code = currency_code(value)

    @property
    def balance(self):
        return self._balance

    @balance.setter
    def balance(self, value):
        self._balance = number(value, positive=False)

    def deposit(self, amount: float):
        self.balance = self.balance + number(amount)

    def withdraw(self, amount: float):
        amount = number(amount)
        if amount > self.balance:
            raise ValueError(
                f"Недостаточно средств: доступно {self.balance:.8f} "
                f"{self.currency_code}, требуется {amount:.8f} {self.currency_code}"
            )
        self.balance = self.balance - amount

    def get_balance_info(self):
        return {"currency_code": self.currency_code, "balance": self.balance}


class Portfolio:
    def __init__(self, user_id: int, wallets=None, *, user=None, rate_provider=None):
        if user is not None and user.user_id != user_id:
            raise ValueError("Пользователь не соответствует портфелю")
        self._user_id = user_id
        self._user = user
        self._wallets = dict(wallets or {})
        for code, wallet in self._wallets.items():
            if not isinstance(wallet, Wallet) or code != wallet.currency_code:
                raise ValueError("Некорректный словарь кошельков")
        self._rate_provider = rate_provider

    @property
    def user(self):
        return self._user

    @property
    def user_id(self):
        return self._user_id

    @property
    def wallets(self):
        return self._wallets.copy()

    def add_currency(self, code: str):
        code = currency_code(code)
        if code in self._wallets:
            raise ValueError(f"Кошелёк '{code}' уже существует")
        self._wallets[code] = Wallet(code)
        return self._wallets[code]

    def get_wallet(self, code: str):
        code = currency_code(code)
        if code not in self._wallets:
            raise ValueError(
                f"У вас нет кошелька '{code}'. "
                "Он создаётся автоматически при первой покупке."
            )
        return self._wallets[code]

    def get_total_value(self, base_currency="USD"):
        if self._rate_provider is None:
            from .rates import RateService

            self._rate_provider = RateService().get_rate
        base_currency = currency_code(base_currency)
        self._rate_provider(base_currency, "USD")
        return sum(
            wallet.balance * self._rate_provider(code, base_currency)["rate"]
            for code, wallet in self._wallets.items()
        )

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "wallets": {
                code: wallet.get_balance_info()
                for code, wallet in self._wallets.items()
            },
        }
