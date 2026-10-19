"""Настройки API. Секреты читаются при создании, не при импорте."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.utils import number
from valutatrade_hub.infra.settings import SettingsLoader


@dataclass
class ParserConfig:
    """Параметры поставщиков, путей и интервала; секреты берутся из env."""

    EXCHANGERATE_API_KEY: str = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY", ""), repr=False
    )
    COINGECKO_API_KEY: str = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY", ""), repr=False
    )
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict = field(
        default_factory=lambda: {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    )
    RATES_FILE_PATH: str = "data/rates.json"
    HISTORY_FILE_PATH: str = "data/exchange_rates.json"
    REQUEST_TIMEOUT: float = 10
    UPDATE_INTERVAL_SECONDS: float = 3600

    def __post_init__(self):
        number(self.REQUEST_TIMEOUT)
        number(self.UPDATE_INTERVAL_SECONDS)
        if self.BASE_CURRENCY != "USD":
            raise ValueError("Parser Service использует USD как единую базу")
        for code in (*self.FIAT_CURRENCIES, *self.CRYPTO_CURRENCIES):
            get_currency(code)
        for code in self.CRYPTO_CURRENCIES:
            if not self.CRYPTO_ID_MAP.get(code):
                raise ValueError(f"Не указан CoinGecko ID для {code}")
        if (
            Path(self.RATES_FILE_PATH).resolve()
            == Path(self.HISTORY_FILE_PATH).resolve()
        ):
            raise ValueError("История и снимок должны храниться в разных файлах")

    @classmethod
    def from_settings(cls, directory=None):
        """Собрать конфигурацию из SettingsLoader с приоритетом directory."""
        settings = SettingsLoader()
        root = Path(directory if directory is not None else settings.get("DATA_DIR"))
        return cls(
            COINGECKO_URL=settings.get("COINGECKO_URL", cls.COINGECKO_URL),
            EXCHANGERATE_API_URL=settings.get(
                "EXCHANGERATE_API_URL", cls.EXCHANGERATE_API_URL
            ),
            FIAT_CURRENCIES=tuple(
                settings.get("FIAT_CURRENCIES", ("EUR", "GBP", "RUB"))
            ),
            CRYPTO_CURRENCIES=tuple(
                settings.get("CRYPTO_CURRENCIES", ("BTC", "ETH", "SOL"))
            ),
            RATES_FILE_PATH=str(root / settings.get("RATES_FILE")),
            HISTORY_FILE_PATH=str(
                root / settings.get("HISTORY_FILE", "exchange_rates.json")
            ),
            REQUEST_TIMEOUT=settings.get("REQUEST_TIMEOUT", 10),
            UPDATE_INTERVAL_SECONDS=settings.get("UPDATE_INTERVAL_SECONDS", 3600),
        )
