# finalproject_Kritsyn_M26-555

Консольное приложение для управления виртуальным валютным портфелем.
Core Service отвечает за пользователей и сделки, Parser Service получает
курсы криптовалют из CoinGecko и фиатных валют из ExchangeRate-API.

## Демо

[Смотреть демонстрацию на asciinema](https://asciinema.org/a/qcB7tebHfqUdZfZ1)

Демо использует фиксированные ответы API.

## Структура

```text
valutatrade_hub/
    core/              модели, валюты, бизнес-логика и исключения
    cli/               командный интерфейс
    infra/             настройки и JSON-хранилище
    parser_service/    API-клиенты, обновление курсов и планировщик
    decorators.py      логирование операций
    logging_config.py  настройка и ротация логов
data/                  пользователи, портфели, кэш и история курсов
tests/                 автоматические тесты
main.py                точка входа
pyproject.toml         зависимости и настройки проекта
uv.lock                зафиксированные версии зависимостей
```

## Установка и запуск

Требуются Python 3.12+ и uv.

```console
uv sync --locked
uv run wallet
```

## Ключи API

Получите ключ на [ExchangeRate-API](https://www.exchangerate-api.com/) и задайте
его в переменной окружения. Пример для PowerShell:

```powershell
$env:EXCHANGERATE_API_KEY = '<ваш ключ>'
uv run wallet
```

Ключ CoinGecko Demo, если нужен: `COINGECKO_API_KEY`.
Переменные задаются в терминале; `.env` автоматически не загружается.

## Команды

После запуска приложения:

```text
register --username alice --password 1234
login --username alice --password 1234
update-rates
show-rates --top 2
buy --currency BTC --amount 0.01
sell --currency BTC --amount 0.005
show-portfolio --base USD
get-rate --from USD --to BTC
exit
```

Стартовый баланс — 10 000 виртуальных USD. `amount` — количество валюты.
Покупка и продажа требуют подтверждения. Справка: `help`.

## Обновление курсов и хранение

`update-rates` обновляет оба источника. Для одного источника используйте
`update-rates --source coingecko` или `update-rates --source exchangerate`.
Без ключа ExchangeRate-API доступно отдельное обновление криптовалют.

Отдельный запуск Parser Service:

```console
uv run wallet-parser --once
uv run wallet-parser --interval 3600
```

JSON-файлы создаются автоматически в `data/`: `users.json`, `portfolios.json`,
`rates.json` (последние курсы) и `exchange_rates.json` (история измерений).
Core читает локальный кэш. TTL по умолчанию — 300 секунд; при устаревании
курсов нужно выполнить `update-rates`. Настройки находятся в
`[tool.valutatrade]` файла `pyproject.toml`.

## Проверки и сборка

```console
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
uv build
```
