"""Контракт курсов и учебная заглушка вместо будущего Parser Service."""

from datetime import UTC, datetime

from valutatrade_hub.infra.database import DatabaseManager, database_operation
from valutatrade_hub.infra.settings import SettingsLoader

from .currencies import get_currency
from .exceptions import ApiRequestError
from .utils import cached, number

DEMO_RATES = {"USD": 1.0, "EUR": 1.0786, "BTC": 59337.21, "RUB": 0.01016, "ETH": 3720.0}


class RateService:
    def __init__(self, storage=None, ttl=None, provider=None):
        self.storage = storage or DatabaseManager().for_directory()
        self.ttl = SettingsLoader().get("RATES_TTL_SECONDS") if ttl is None else ttl
        self.provider = provider or self._demo_rate
        self._fetch = cached(self.ttl)(self.provider)

    @staticmethod
    def _demo_rate(source, target):
        if source not in DEMO_RATES or target not in DEMO_RATES:
            raise ApiRequestError(
                f"Курс {source}→{target} недоступен. Повторите попытку позже."
            )
        return {
            "rate": DEMO_RATES[source] / DEMO_RATES[target],
            "updated_at": datetime.now(UTC).isoformat(),
            "source": "Demo (учебная заглушка)",
        }

    @database_operation
    def get_rate(self, source, target):
        source, target = get_currency(source).code, get_currency(target).code
        rates = self.storage.read("rates.json", {})
        key = f"{source}_{target}"
        record = rates.get(key)
        if isinstance(record, dict):
            try:
                updated = datetime.fromisoformat(record["updated_at"])
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=UTC)
                age = (datetime.now(UTC) - updated).total_seconds()
                number(record["rate"])
                if 0 <= age < self.ttl:
                    return {
                        **record,
                        "source": record.get(
                            "source", rates.get("source", "Локальный кеш")
                        ),
                    }
            except (KeyError, TypeError, ValueError):
                pass

        # Сохраняем согласованность с локальными котировками Parser Service:
        # обратный и кросс-курс выводим из свежих записей, а не из Demo.
        def fresh(pair):
            item = rates.get(pair, {})
            try:
                updated = datetime.fromisoformat(item["updated_at"])
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=UTC)
                age = (datetime.now(UTC) - updated).total_seconds()
                if 0 <= age < self.ttl:
                    return (
                        number(item["rate"]),
                        updated,
                        item.get("source", rates.get("source", "Локальный кеш")),
                    )
            except (KeyError, TypeError, ValueError):
                pass
            return None

        reverse = fresh(f"{target}_{source}")
        if reverse:
            return {
                "rate": 1 / reverse[0],
                "updated_at": reverse[1].isoformat(),
                "source": reverse[2],
            }
        left, right = fresh(f"{source}_USD"), fresh(f"{target}_USD")
        if left and right:
            return {
                "rate": left[0] / right[0],
                "updated_at": min(left[1], right[1]).isoformat(),
                "source": ", ".join(sorted({left[2], right[2]})),
            }
        try:
            record = dict(self._fetch(source, target))
            number(record["rate"])
            updated = datetime.fromisoformat(record["updated_at"])
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - updated).total_seconds()
            if age < 0 or (self.ttl > 0 and age >= self.ttl):
                raise ValueError("Поставщик вернул устаревшую котировку")
        except ApiRequestError:
            raise
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise ApiRequestError(
                f"Курс {source}→{target} недоступен: {error}"
            ) from error
        rates[key] = record
        rates["source"] = record.get("source", "ParserService")
        rates["last_refresh"] = record["updated_at"]
        self.storage.write("rates.json", rates)
        return record.copy()
