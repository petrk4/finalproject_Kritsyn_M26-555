"""Типы и реестр поддерживаемых валют. Капитализация — учебные данные."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .exceptions import CurrencyNotFoundError
from .utils import currency_code, number


def nonempty(value, field):
    """Отклонить пустое или нестроковое значение указанного поля."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} не может быть пустым")


@dataclass(frozen=True)
class Currency(ABC):
    """Абстрактная валюта с неизменяемыми именем и кодом."""

    name: str
    code: str

    def __post_init__(self):
        nonempty(self.name, "name")
        if currency_code(self.code) != self.code:
            raise ValueError("Код валюты должен быть в верхнем регистре")

    @abstractmethod
    def get_display_info(self) -> str:
        """Вернуть строку для UI и журналов."""


@dataclass(frozen=True)
class FiatCurrency(Currency):
    """Фиатная валюта с указанием страны или зоны эмиссии."""

    issuing_country: str

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.issuing_country, "issuing_country")

    def get_display_info(self) -> str:
        """Представить тип валюты и её атрибуты для UI и журналов."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


@dataclass(frozen=True)
class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и справочной капитализацией."""

    algorithm: str
    market_cap: float

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.algorithm, "algorithm")
        number(self.market_cap, positive=False)

    def get_display_info(self) -> str:
        """Представить тип валюты и её атрибуты для UI и журналов."""
        mantissa, exponent = f"{self.market_cap:.2e}".split("e")
        cap = f"{mantissa}e{int(exponent)}"
        return (
            f"[CRYPTO] {self.code} — {self.name} (Algo: {self.algorithm}, MCAP: {cap})"
        )


CURRENCIES = {
    currency.code: currency
    for currency in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        FiatCurrency("Pound Sterling", "GBP", "United Kingdom"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
        CryptoCurrency("Ethereum", "ETH", "Proof-of-Stake", 4.5e11),
        CryptoCurrency("Solana", "SOL", "Proof-of-Stake", 0),
    )
}


def get_currency(code: str) -> Currency:
    """Вернуть валюту по коду либо вызвать CurrencyNotFoundError."""
    try:
        normalized = currency_code(code)
    except ValueError as error:
        raise CurrencyNotFoundError(code) from error
    if normalized not in CURRENCIES:
        raise CurrencyNotFoundError(normalized)
    return CURRENCIES[normalized]
