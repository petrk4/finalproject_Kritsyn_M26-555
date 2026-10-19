"""Ошибки предметной области с сообщениями для CLI."""


class InsufficientFundsError(ValueError):
    def __init__(self, available, required, code):
        self.available, self.required, self.code = available, required, code
        super().__init__(
            f"Недостаточно средств: доступно {available} {code}, "
            f"требуется {required} {code}"
        )


class CurrencyNotFoundError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class ApiRequestError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")
