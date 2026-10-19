"""Координатор обновления. Отказ одного источника не отменяет другой."""

import logging
from datetime import UTC, datetime

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import number

from .api_clients import CoinGeckoClient, ExchangeRateApiClient
from .config import ParserConfig
from .storage import ParserStorage, utc_time

LOGGER_NAME = "valutatrade.parser"


class RatesUpdater:
    def __init__(self, clients, storage):
        self.clients, self.storage = clients, storage

    @classmethod
    def create(cls, directory=None, source=None):
        config = ParserConfig.from_settings(directory)
        factories = {
            "coingecko": CoinGeckoClient,
            "exchangerate": ExchangeRateApiClient,
        }
        if source is not None and source not in factories:
            raise ValueError("Источник должен быть coingecko или exchangerate")
        selected = [factories[source]] if source else list(factories.values())
        return cls([factory(config) for factory in selected], ParserStorage(config))

    def run_update(self):
        logger = logging.getLogger(LOGGER_NAME)
        logger.info("Starting rates update")
        measurements, errors, counts = [], [], {}
        for client in self.clients:
            logger.info("Fetching from %s", client.source)
            try:
                rates = client.fetch_rates()
                if not rates:
                    raise ApiRequestError(f"{client.source}: пустой ответ")
                batch = []
                timestamp = (
                    getattr(client, "timestamp", None) or datetime.now(UTC).isoformat()
                )
                utc_time(timestamp)
                for pair, value in rates.items():
                    source, target = pair.split("_")
                    get_currency(source)
                    get_currency(target)
                    batch.append(
                        {
                            "from_currency": source,
                            "to_currency": target,
                            "rate": number(value),
                            "timestamp": timestamp,
                            "source": client.source,
                            "meta": getattr(client, "metadata", {}).get(pair, {}),
                        }
                    )
                measurements.extend(batch)
                counts[client.source] = len(batch)
                logger.info("%s OK (%s rates)", client.source, len(batch))
            except (ApiRequestError, ValueError, TypeError) as error:
                message = f"{client.source}: {error}"
                errors.append(message)
                logger.error("Failed to fetch: %s", message)
        if not measurements:
            logger.error("Update failed: no valid rates; cache unchanged")
            raise ApiRequestError("; ".join(errors) or "Нет источников котировок")
        try:
            result = self.storage.save(measurements)
        except (ValueError, OSError, KeyError, TypeError):
            logger.error(
                "Storage update failed; inspect local JSON files and permissions"
            )
            raise
        result.update(errors=errors, sources=counts)
        logger.info(
            "Update finished: updated=%s errors=%s", result["updated"], len(errors)
        )
        return result
