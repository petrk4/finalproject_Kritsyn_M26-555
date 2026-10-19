"""HTTP-клиенты с единым контрактом пары → курс; URL с ключами не логируются."""

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from urllib.parse import quote

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import number

from .config import ParserConfig


class BaseApiClient(ABC):
    """Общий контракт клиента: получить словарь пар и числовых курсов."""

    source = "API"

    def __init__(self, config=None, session=None):
        self.config = config or ParserConfig.from_settings()
        self.session = session or requests
        self.metadata = {}
        self.timestamp = None

    @abstractmethod
    def fetch_rates(self) -> dict:
        """Возвращает {FROM_USD: float}; ошибки — ApiRequestError."""

    def _request(self, url, **kwargs):
        start = time.perf_counter()
        self.metadata = {}
        self.timestamp = None
        try:
            response = self.session.get(
                url,
                timeout=self.config.REQUEST_TIMEOUT,
                allow_redirects=False,
                **kwargs,
            )
        except requests.exceptions.RequestException as error:
            # str(error) содержит URL с секретом; не включаем его даже в цепочку.
            reason = (
                "таймаут"
                if isinstance(error, requests.exceptions.Timeout)
                else "ошибка сети"
            )
            raise ApiRequestError(f"{self.source}: {reason}") from None
        try:
            if response.status_code != 200:
                reason = {
                    401: "неверный API-ключ",
                    403: "доступ запрещён",
                    429: "лимит запросов превышен; повторите позже",
                }.get(response.status_code, "неуспешный ответ")
                raise ApiRequestError(
                    f"{self.source}: HTTP {response.status_code}, {reason}"
                )
            try:
                payload = response.json()
            except (ValueError, requests.exceptions.RequestException):
                raise ApiRequestError(f"{self.source}: некорректный JSON") from None
            if not isinstance(payload, dict):
                raise ApiRequestError(f"{self.source}: ожидается JSON-объект")
            self.timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self._request_meta = {
                "request_ms": round((time.perf_counter() - start) * 1000, 3),
                "status_code": response.status_code,
                "etag": response.headers.get("ETag"),
            }
            return payload
        finally:
            response.close()


class CoinGeckoClient(BaseApiClient):
    """Пакетный запрос криптовалют по идентификаторам CoinGecko."""

    source = "CoinGecko"

    def fetch_rates(self):
        """Получить проверенные пары к USD либо вызвать ApiRequestError."""
        ids = {
            code: self.config.CRYPTO_ID_MAP[code]
            for code in self.config.CRYPTO_CURRENCIES
        }
        headers = {}
        if self.config.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = self.config.COINGECKO_API_KEY
        payload = self._request(
            self.config.COINGECKO_URL,
            headers=headers,
            params={
                "ids": ",".join(ids.values()),
                "vs_currencies": "usd",
                "include_last_updated_at": "true",
            },
        )
        rates = {}
        try:
            for code, raw_id in ids.items():
                item = payload[raw_id]
                pair = f"{code}_USD"
                rates[pair] = number(item["usd"])
                self.metadata[pair] = {
                    **self._request_meta,
                    "raw_id": raw_id,
                    "provider_updated_at": item.get("last_updated_at"),
                }
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ApiRequestError(
                "CoinGecko: отсутствует или некорректен курс"
            ) from None
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Запрос фиата с переводом котировок USD в обратные пары."""

    source = "ExchangeRate-API"

    def fetch_rates(self):
        """Получить проверенные пары к USD либо вызвать ApiRequestError."""
        if not self.config.EXCHANGERATE_API_KEY:
            raise ApiRequestError("Не задана переменная EXCHANGERATE_API_KEY")
        url = (
            f"{self.config.EXCHANGERATE_API_URL.rstrip('/')}/"
            f"{quote(self.config.EXCHANGERATE_API_KEY, safe='')}/latest/USD"
        )
        payload = self._request(url)
        if payload.get("result") != "success":
            reason = {
                "invalid-key": "неверный API-ключ",
                "inactive-account": "аккаунт не активирован",
                "quota-reached": "исчерпана квота запросов",
            }.get(payload.get("error-type"), "API вернул ошибку")
            raise ApiRequestError(f"ExchangeRate-API: {reason}")
        if payload.get("base_code") != "USD":
            raise ApiRequestError("ExchangeRate-API: неожиданная базовая валюта")
        # Официальный v6 использует conversion_rates; rates — совместимость с ТЗ.
        values = payload.get("conversion_rates", payload.get("rates"))
        result = {}
        try:
            for code in self.config.FIAT_CURRENCIES:
                pair = f"{code}_USD"
                result[pair] = number(1 / number(values[code]))
                self.metadata[pair] = {
                    **self._request_meta,
                    "provider_updated_at": payload.get("time_last_update_utc"),
                }
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ApiRequestError(
                "ExchangeRate-API: отсутствует или некорректен курс"
            ) from None
        return result
