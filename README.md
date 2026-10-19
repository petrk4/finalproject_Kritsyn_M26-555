# finalproject_Kritsyn_M26-555

Учебное консольное приложение для имитации валютного кошелька.
Автор: Petr Kritsyn, группа M26-555.

На текущем этапе настроена инфраструктура проекта и базовый интерфейс.
Операции с валютами, хранение в JSON, декораторы логирования и подтверждения,
замыкание для кэширования и измерение времени будут добавлены по следующим
подразделам задания. Сейчас доступны только команды `help`, `exit` и `quit`.

## Окружение и запуск

Требуются Python 3.12+ и uv. Из корня проекта выполните:

```console
uv sync --locked
uv run wallet
```

Другие способы запуска и справка:

```console
uv run python -m finalproject_kritsyn_m26_555
uv run wallet --help
uv run wallet --version
```

`uv sync` устанавливает пакет и зависимости в локальную `.venv`.
В PyCharm выберите интерпретатор `.venv/Scripts/python.exe` на Windows.
Имена дистрибутива при сборке нормализуются; имя Python-модуля использует
нижний регистр и подчёркивания вместо дефисов.

## Структура

```text
.github/workflows/ci.yml       проверки GitHub Actions
src/finalproject_kritsyn_m26_555/
    __init__.py               Python-пакет
    __main__.py               запуск через python -m
    cli.py                    класс приложения и консольный цикл
.python-version               версия Python для uv
pyproject.toml                метаданные, зависимости и настройки Ruff
uv.lock                       зафиксированные версии зависимостей
```

Внешняя зависимость приложения — `prettytable`; инструмент разработки — `ruff`.
Для сборки через `uv build` используется backend `hatchling`.
`argparse` и `shlex` входят в стандартную библиотеку.
`shlex` разбирает собственные команды приложения по правилам Unix-кавычек;
команды не передаются системной оболочке. Поддержка путей Windows пока не нужна.

## Качество кода и сборка

```console
uv run ruff check .
uv run ruff format --check .
uv run ruff format .
uv build
```

Артефакты сборки появляются в `dist/`. Для установки готового wheel
передайте его путь команде `uv tool install` — после установки доступна `wallet`.
GitHub Actions проверяет линтер, форматирование, точки входа и сборку пакета.

## Работа с Git

Используется GitHub Flow: создавайте ветку от `main` для каждой задачи,
делайте осмысленные коммиты после проверки и объединяйте через pull request.

```console
git switch -c feature/wallet-model
uv run ruff check .
uv run ruff format --check .
git add src README.md
git commit -m "feat: add wallet model"
```

Не добавляйте в Git окружение, ключи доступа и локальные данные кошелька:
они исключены в `.gitignore`.
