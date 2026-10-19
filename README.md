# finalproject_Kritsyn_M26-555

Учебный валютный кошелёк: Core Service (пользователи, портфели, сделки)
и отдельный Parser Service (получение котировок, снимок и история).
Автор: Petr Kritsyn, группа M26-555.

## Установка и запуск

Требуются Python 3.12+ и uv:

```console
uv sync --locked
uv run wallet
```

Альтернативы: `uv run python main.py`, `uv run python -m valutatrade_hub`.
PyCharm на Windows: интерпретатор `.venv/Scripts/python.exe`.
`wallet --help` показывает параметры запуска; `help` внутри CLI — команды.
Другой каталог: `uv run wallet --data-dir ./my-wallet-data`.
Другие настройки: `uv run wallet --config config.json`.

## Ключи внешних API

Зарегистрируйтесь на [ExchangeRate-API](https://www.exchangerate-api.com/) и
задайте EXCHANGERATE_API_KEY в окружении процесса. Ключ не хранится в коде,
конфигурации TOML, репозитории или логах. Пример для PowerShell:

```powershell
$env:EXCHANGERATE_API_KEY = '<ваш ключ>'
# При необходимости — Demo-ключ CoinGecko:
$env:COINGECKO_API_KEY = '<ваш Demo-ключ>'
uv run wallet
```

Для bash: `export EXCHANGERATE_API_KEY='<ваш ключ>'`.
`.env.example` описывает имена переменных; файлы .env автоматически не читаются.
Не вставляйте настоящий ключ в отслеживаемые файлы. Текст сетевых исключений,
содержащий URL с ключом, не попадает в сообщения клиентских ошибок.

CoinGecko запрашивается через публичный endpoint; если сервис требует
авторизацию, задайте COINGECKO_API_KEY. Demo-ключ передаётся заголовком
x-cg-demo-api-key. Pro-ключи этим клиентом не поддерживаются.
Без EXCHANGERATE_API_KEY обновление фиата вернёт понятную ошибку, но успешно
полученные криптовалюты будут сохранены. Лимиты и частота обновления зависят
от тарифа API: приложение не повторяет запросы автоматически при HTTP 429.

## Пример сессии

Команды вводятся после запуска wallet:

```text
update-rates
show-rates
register --username alice --password 1234
login --username alice --password 1234
show-portfolio
buy --currency BTC --amount 0.01 --yes
sell --currency BTC --amount 0.005 --yes
get-rate --from USD --to BTC
show-rates --top 2
show-rates --currency RUB
show-rates --base EUR
show-portfolio --base EUR
currencies
history
logout
exit
```

Справка команды: `buy --help`. Имена/пароли с пробелами заключайте в кавычки.
Без --yes buy/sell запрашивают подтверждение. amount — количество валюты,
не стоимость в долларах. Новый пользователь получает **10 000 виртуальных USD**
по согласованному изменению ТЗ. Покупки списывают USD, продажи зачисляют USD.
Продажа USD за USD не разрешена. Поддерживаются USD, EUR, GBP, RUB, BTC, ETH, SOL.

## Parser Service

`update-rates` обновляет оба источника; `update-rates --source coingecko` или
`update-rates --source exchangerate` — только один. В случае частичного сбоя
CLI сообщает об этом и сохраняет данные работающего источника. При полном
отказе история и снимок не меняются. Отсутствие ключа не препятствует запуску CLI.

Отдельный процесс, без входа в кошелёк:

```console
uv run wallet-parser --once
uv run wallet-parser --once --source coingecko
uv run wallet-parser --interval 3600
uv run python -m valutatrade_hub.parser_service.scheduler --once
```

Без --once планировщик обновляет курсы сразу, затем ждёт заданный интервал
после завершения попытки. Ctrl+C останавливает процесс. Автозапуск в системе
не устанавливается. Для cron/Task Scheduler можно использовать команду --once.
Разовый запуск возвращает код 1 при полном или частичном отказе и 0 при успехе.
Интервал по умолчанию — 3600 секунд; выбирайте его с учётом тарифа API.

CoinGecko запрашивает bitcoin, ethereum, solana одним GET-запросом и возвращает
BTC_USD, ETH_USD, SOL_USD. ExchangeRate-API запрашивается с базой USD.
Его conversion_rates.EUR означает EUR за один USD, поэтому для EUR_USD
сохраняется **1 / conversion_rates.EUR**. Например, 0.8 превращается в 1.25.
Поле rates поддержано для совместимости с примером ТЗ. На неверные ключи,
HTTP 429/5xx, сетевые ошибки, некорректный JSON и значения возникает ApiRequestError.

Официальные контракты:
[ExchangeRate-API Standard](https://www.exchangerate-api.com/docs/standard-requests),
[CoinGecko Demo simple/price](https://docs.coingecko.com/demo/reference/simple-price).

## Снимок и история

Core читает только локальный rates.json. get-rate и сделки не обращаются к сети
и не подменяют отсутствующие котировки учебными. При истечении TTL требуется
update-rates. show-rates может показать старые значения со статусом «устарел»;
они не используются для сделок. --top выбирает N самых дорогих криптовалют
по цене единицы, не по капитализации. --base конвертирует через долларовые пары.

```json
{
  "pairs": {
    "EUR_USD": {
      "rate": 1.25,
      "updated_at": "2026-10-19T12:00:00Z",
      "source": "ExchangeRate-API"
    }
  },
  "last_refresh": "2026-10-19T12:00:01Z"
}
```

exchange_rates.json — массив измерений: id, from_currency, to_currency, rate,
timestamp, source, meta. Идентификатор: FROM_TO_ISO-UTC; повтор той же пары
и времени не дублируется. timestamp/updated_at — время успешного получения
и проверки ответа. Исходное время поставщика сохраняется отдельно в
meta.provider_updated_at: свежесть получения не означает, что поставщик
изменил котировку (фиатный API может публиковать значения реже запросов).
meta также содержит request_ms, status_code, etag и raw_id для криптовалют.

Новое значение заменяет пару только при более свежем timestamp. Старые
измерения остаются в истории. Каждый файл записывается атомарно через
временный файл и os.replace. Межпроцессная блокировка rates.lock защищает
одновременные записи CLI и отдельного парсера. История пишется первой:
если запись снимка не удалась, следующее успешное обновление восстанавливает
его из истории. Два файла не являются единой транзакцией. История хранится
целиком в JSON и не рассчитана на большой промышленный объём.

Старый плоский кэш читается для совместимости; записи с источником Demo
игнорируются. После обновления формат становится pairs/last_refresh.
Пользователи и портфели сохраняют прежний формат; их межпроцессная запись
не поддерживается — используйте один процесс Core на каталог данных.

## Архитектура

```text
valutatrade_hub/
    core/
        models.py          User, Wallet, Portfolio
        currencies.py      Currency, FiatCurrency, CryptoCurrency, реестр
        exceptions.py      пользовательские исключения
        usecases.py        сценарии CLI
        rates.py           чтение кэша, TTL, кросс-курсы, фильтры
        utils.py           валидация, JSON и замыкание кэширования
    infra/
        settings.py        Singleton SettingsLoader
        database.py        Singleton DatabaseManager и RLock
    parser_service/
        config.py          ParserConfig; ключи из окружения
        api_clients.py     BaseApiClient, CoinGeckoClient, ExchangeRateApiClient
        updater.py         RatesUpdater: получение → объединение → сохранение
        storage.py         история, снимок, дедупликация, блокировка
        scheduler.py       отдельная точка входа и периодический запуск
    cli/interface.py       команды, таблицы, обработка ошибок
    decorators.py          log_action
    logging_config.py      JSON-логи и ротация
main.py
pyproject.toml
uv.lock
tests/
.github/workflows/ci.yml
```

Currency — ABC с неизменяемыми публичными атрибутами. Код: 2–5 латинских
букв в верхнем регистре; CLI нормализует регистр. get_currency возвращает
объект из реестра. Капитализации в currencies — учебные справочные значения,
не данные API; нулевая капитализация SOL означает отсутствие оценки.
Пароли хранятся с солью и SHA-256 согласно учебному ТЗ, без открытого текста.
Для промышленной системы требуется специализированное хеширование паролей.

## Ошибки

- InsufficientFundsError: недостаточно средств; портфель не изменяется.
- CurrencyNotFoundError: неизвестная валюта; CLI показывает поддерживаемые коды.
- ApiRequestError: сеть, HTTP, ключ или некорректный ответ поставщика.
- Кэш пуст/устарел: сообщение с предложением выполнить update-rates.
- show-rates --currency ABC: курс для ABC не найден в кеше.
- Невалидные суммы, NaN, бесконечности, повреждённый JSON: ошибка без замены
  данных пустыми значениями.

## Настройки и логи

SettingsLoader лениво создаётся через __new__; get(key, default=None) читает
настройку, reload(path=None) перечитывает TOML/JSON с сохранением прежних
значений при ошибке. По умолчанию используется [tool.valutatrade] из
pyproject.toml текущего каталога, либо встроенные значения при отсутствии файла.
В config.json ключи задаются непосредственно в корневом объекте.

| Ключ | По умолчанию |
| --- | --- |
| DATA_DIR | data |
| USERS_FILE / PORTFOLIOS_FILE | users.json / portfolios.json |
| RATES_FILE / HISTORY_FILE | rates.json / exchange_rates.json |
| RATES_TTL_SECONDS | 300 |
| DEFAULT_BASE_CURRENCY | USD |
| REQUEST_TIMEOUT | 10 секунд |
| UPDATE_INTERVAL_SECONDS | 3600 секунд |
| FIAT_CURRENCIES | EUR, GBP, RUB |
| CRYPTO_CURRENCIES | BTC, ETH, SOL |
| LOG_FILE / PARSER_LOG_FILE | logs/actions.log / logs/parser.log |
| LOG_FORMAT / LOG_LEVEL | json / INFO |
| LOG_MAX_BYTES / LOG_BACKUP_COUNT | 1048576 / 3 |

COINGECKO_URL и EXCHANGERATE_API_URL также можно переопределить через настройки.
В ParserConfig доступны CRYPTO_ID_MAP и пути к снимку/истории. Ключи API —
только окружение. Пути относительны к рабочему каталогу; --data-dir имеет
приоритет над DATA_DIR. Расчёты сделок всегда в USD, DEFAULT_BASE_CURRENCY
задаёт базу представления портфеля. После изменения настроек перезапустите
сервисы для применения новых TTL и путей.

@log_action пишет INFO JSON Lines: timestamp (ISO UTC), action, username,
user_id, currency_code, amount, rate, base, result, duration_ms;
при ошибках — error_type/error_message. verbose=True добавляет before/after.
Пароли, соли и хеши не логируются. Парсер пишет этапы обновления и ошибки
в отдельный parser.log. Ротация по размеру: 1 МиБ, три архива. logs/ исключён из Git.

## Проверки и сборка

```console
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
uv build
```

Тесты работают без сети и реальных ключей: проверяют модели, сделки,
синглтоны, журнал, API-контракты, инверсию фиата, ошибки, TTL, историю,
восстановление снимка, фильтры CLI и планировщик. Для прежних сценариев
кошелька учебный поставщик внедряется только явно в тестах.
Сборка создаёт wheel и sdist в dist/. `uv tool install <путь-к-wheel>`
устанавливает wallet и wallet-parser. GitHub Actions запускает проверки.

Репозиторий: [finalproject_Kritsyn_M26-555](https://github.com/petrk4/finalproject_Kritsyn_M26-555).
Используйте осмысленные коммиты и ветки задач. Локальные data/, logs/,
окружение и секреты исключены из Git; пользовательские каталоги данных
внутри проекта добавляйте в .gitignore отдельно.
