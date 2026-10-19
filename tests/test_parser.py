"""Parser Service: без внешней сети, с реальными временными JSON-файлами."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

import requests

from valutatrade_hub.cli.interface import WalletApplication
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.rates import RateService
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.core.utils import JsonStorage
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.scheduler import run_scheduler
from valutatrade_hub.parser_service.storage import ParserStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.config = ParserConfig(EXCHANGERATE_API_KEY="secret-api-key")
        self.response = Mock(status_code=200, headers={"ETag": 'W/"test"'})
        self.session = Mock()
        self.session.get.return_value = self.response

    def test_coingecko_mapping_metadata_and_timeout(self):
        self.response.json.return_value = {
            "bitcoin": {"usd": 60000, "last_updated_at": 123},
            "ethereum": {"usd": 3000},
            "solana": {"usd": 150},
        }
        client = CoinGeckoClient(self.config, self.session)
        self.assertEqual(
            client.fetch_rates(), {"BTC_USD": 60000, "ETH_USD": 3000, "SOL_USD": 150}
        )
        kwargs = self.session.get.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(kwargs["params"]["ids"], "bitcoin,ethereum,solana")
        self.assertEqual(client.metadata["BTC_USD"]["raw_id"], "bitcoin")
        self.assertEqual(client.metadata["BTC_USD"]["status_code"], 200)
        self.response.close.assert_called_once()

    def test_fiat_inverse_and_legacy_field(self):
        client = ExchangeRateApiClient(self.config, self.session)
        for field in ("conversion_rates", "rates"):
            self.response.json.return_value = {
                "result": "success",
                "base_code": "USD",
                field: {"EUR": 0.8, "GBP": 0.5, "RUB": 100},
            }
            self.assertEqual(
                client.fetch_rates(), {"EUR_USD": 1.25, "GBP_USD": 2, "RUB_USD": 0.01}
            )

    def test_missing_key_never_sends_request(self):
        client = ExchangeRateApiClient(
            ParserConfig(EXCHANGERATE_API_KEY=""), self.session
        )
        with self.assertRaisesRegex(ApiRequestError, "EXCHANGERATE_API_KEY"):
            client.fetch_rates()
        self.session.get.assert_not_called()

    def test_http_and_network_errors_hide_key(self):
        client = ExchangeRateApiClient(self.config, self.session)
        for status in (401, 403, 429, 500, 302):
            self.response.status_code = status
            with self.assertRaises(ApiRequestError) as caught:
                client.fetch_rates()
            self.assertNotIn("secret-api-key", str(caught.exception))
            self.assertIn(str(status), str(caught.exception))
        for error in (
            requests.Timeout("secret-api-key"),
            requests.ConnectionError("secret-api-key"),
        ):
            self.session.get.side_effect = error
            with self.assertRaises(ApiRequestError) as caught:
                client.fetch_rates()
            self.assertNotIn("secret-api-key", str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)

    def test_invalid_json_and_invalid_prices(self):
        client = CoinGeckoClient(self.config, self.session)
        self.response.json.side_effect = ValueError("not JSON")
        with self.assertRaises(ApiRequestError):
            client.fetch_rates()
        self.response.json.side_effect = None
        for value in (0, -1, True, "100", float("nan"), float("inf"), None):
            self.response.json.return_value = {"bitcoin": {"usd": value}}
            with self.subTest(value=value), self.assertRaises(ApiRequestError):
                client.fetch_rates()

    def test_api_error_payload(self):
        self.response.json.return_value = {
            "result": "error",
            "error-type": "quota-reached",
        }
        with self.assertRaisesRegex(ApiRequestError, "квота"):
            ExchangeRateApiClient(self.config, self.session).fetch_rates()

    def test_environment_read_at_construction_not_import(self):
        with patch.dict("os.environ", {"EXCHANGERATE_API_KEY": "new-secret"}):
            config = ParserConfig()
        self.assertEqual(config.EXCHANGERATE_API_KEY, "new-secret")
        self.assertNotIn("new-secret", repr(config))


class ParserTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config = ParserConfig(
            RATES_FILE_PATH=str(self.directory / "rates.json"),
            HISTORY_FILE_PATH=str(self.directory / "exchange_rates.json"),
        )
        self.storage = ParserStorage(self.config)
        self.json = JsonStorage(self.directory)
        self.now = datetime.now(UTC)

    def measurement(self, code="BTC", rate=60000, timestamp=None):
        return {
            "from_currency": code,
            "to_currency": "USD",
            "rate": rate,
            "timestamp": (timestamp or self.now).isoformat(),
            "source": "test",
            "meta": {"status_code": 200},
        }

    def client(self, source, rates):
        client = Mock(source=source, metadata={}, timestamp=self.now.isoformat())
        client.fetch_rates.return_value = rates
        return client

    def test_history_dedup_newest_wins_and_format(self):
        item = self.measurement()
        self.assertEqual(self.storage.save([item])["updated"], 1)
        self.assertEqual(self.storage.save([item])["updated"], 0)
        self.storage.save(
            [self.measurement(rate=10, timestamp=self.now - timedelta(days=1))]
        )
        snapshot = self.json.read("rates.json", {})
        self.assertEqual(snapshot["pairs"]["BTC_USD"]["rate"], 60000)
        history = self.json.read("exchange_rates.json", [])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["id"], f"BTC_USD_{history[0]['timestamp']}")

    def test_failed_validation_keeps_files(self):
        self.storage.save([self.measurement()])
        before = Path(self.config.RATES_FILE_PATH).read_bytes()
        with self.assertRaises(ValueError):
            self.storage.save([self.measurement(rate=float("nan"))])
        self.assertEqual(Path(self.config.RATES_FILE_PATH).read_bytes(), before)

    def test_partial_failure_keeps_old_pairs(self):
        self.storage.save([self.measurement("EUR", 1.2)])
        failed = self.client("fiat", {})
        failed.fetch_rates.side_effect = ApiRequestError("offline")
        good = self.client("crypto", {"BTC_USD": 60000})
        result = RatesUpdater([failed, good], self.storage).run_update()
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(
            set(self.json.read("rates.json", {})["pairs"]), {"EUR_USD", "BTC_USD"}
        )

    def test_total_failure_preserves_snapshot(self):
        self.storage.save([self.measurement()])
        before = Path(self.config.RATES_FILE_PATH).read_bytes()
        failed = self.client("broken", {})
        failed.fetch_rates.side_effect = ApiRequestError("offline")
        with self.assertRaises(ApiRequestError):
            RatesUpdater([failed], self.storage).run_update()
        self.assertEqual(Path(self.config.RATES_FILE_PATH).read_bytes(), before)

    def test_recovery_after_snapshot_write_failure(self):
        original = self.storage.rates.write
        with patch.object(self.storage.rates, "write", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.storage.save([self.measurement()])
        self.assertEqual(len(self.json.read("exchange_rates.json", [])), 1)
        self.assertFalse(Path(self.config.RATES_FILE_PATH).exists())
        self.storage.rates.write = original
        self.storage.save([self.measurement("EUR", 1.2)])
        self.assertEqual(len(self.json.read("rates.json", {})["pairs"]), 2)

    def test_core_stale_no_network_or_demo_and_show_status(self):
        old = self.now - timedelta(minutes=6)
        self.storage.save([self.measurement(timestamp=old)])
        rates = RateService(self.json)
        with patch("requests.get", side_effect=AssertionError("Core must not request")):
            with self.assertRaisesRegex(ValueError, "update-rates"):
                rates.get_rate("BTC", "USD")
            self.assertTrue(rates.show_rates()["rows"][0]["stale"])

    def test_cross_rates_top_currency_and_base_filters(self):
        self.storage.save(
            [
                self.measurement(),
                self.measurement("ETH", 3000),
                self.measurement("SOL", 150),
                self.measurement("EUR", 1.25),
            ]
        )
        rates = RateService(self.json)
        rows = rates.show_rates(top=2, base="EUR")["rows"]
        self.assertEqual([item["pair"] for item in rows], ["BTC_EUR", "ETH_EUR"])
        self.assertEqual(rows[0]["rate"], 48000)
        self.assertEqual(len(rates.show_rates(currency="SOL")["rows"]), 1)
        with self.assertRaisesRegex(ValueError, "не найден"):
            rates.show_rates(currency="ABC")
        with self.assertRaises(ValueError):
            rates.show_rates(top=0)

    def test_demo_legacy_cache_cannot_be_used_for_real_trades(self):
        self.json.write(
            "rates.json",
            {
                "BTC_USD": {
                    "rate": 1,
                    "updated_at": self.now.isoformat(),
                    "source": "Demo (учебная заглушка)",
                }
            },
        )
        with self.assertRaisesRegex(ValueError, "update-rates"):
            RateService(self.json).get_rate("BTC", "USD")

    def test_cli_update_and_show_rates(self):
        service = WalletService(self.directory)
        updater = RatesUpdater(
            [self.client("crypto", {"BTC_USD": 60000})], self.storage
        )
        app = WalletApplication(service)
        with patch.object(RatesUpdater, "create", return_value=updater) as create:
            with redirect_stdout(io.StringIO()) as output:
                app.execute("update-rates --source coingecko")
                app.execute("show-rates --top 1")
        create.assert_called_once_with(self.directory, "coingecko")
        self.assertIn("BTC_USD", output.getvalue())
        self.assertIn("Обновлено курсов: 1", output.getvalue())

    def test_scheduler_stops_and_survives_failure(self):
        updater = Mock()
        updater.run_update.side_effect = [ApiRequestError("offline"), {}]
        stop = Mock(spec=Event)
        stop.is_set.return_value = False
        stop.wait.side_effect = [False, True]
        run_scheduler(updater, 60, stop)
        self.assertEqual(updater.run_update.call_count, 2)
        self.assertEqual(stop.wait.call_args.args, (60.0,))
