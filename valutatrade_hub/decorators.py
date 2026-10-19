"""Структурированный журнал операций без паролей, солей и хешей."""

import inspect
import logging
import math
import time
from functools import wraps

from .logging_config import LOGGER_NAME


def safe_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return type(value).__name__


def log_action(function=None, *, verbose=False):
    def decorate(target):
        signature = inspect.signature(target)

        @wraps(target)
        def wrapped(*args, **kwargs):
            arguments = signature.bind(*args, **kwargs).arguments
            service = arguments.get("self")
            user = getattr(service, "current_user", None)
            action = target.__name__.upper()
            data = {
                "action": action,
                "username": safe_value(
                    arguments.get("username", getattr(user, "username", None))
                ),
                "user_id": (
                    None
                    if action in {"LOGIN", "REGISTER"}
                    else getattr(user, "user_id", None)
                ),
                "currency_code": safe_value(
                    arguments.get("currency", arguments.get("source"))
                ),
                "amount": safe_value(arguments.get("amount")),
                "rate": None,
                "base": arguments.get(
                    "target", "USD" if action in {"BUY", "SELL"} else None
                ),
            }
            start = time.perf_counter()
            try:
                result = target(*args, **kwargs)
            except Exception as error:
                data.update(
                    result="ERROR",
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
                raise
            else:
                data["result"] = "OK"
                if isinstance(result, dict):
                    data["rate"] = result.get("rate")
                    data["currency_code"] = result.get(
                        "currency", data["currency_code"]
                    )
                    data["user_id"] = result.get("user_id", data["user_id"])
                    if verbose:
                        data["context"] = {
                            key: result[key]
                            for key in ("before", "after", "usd_balance")
                            if key in result
                        }
                return result
            finally:
                data["duration_ms"] = round((time.perf_counter() - start) * 1000, 3)
                logging.getLogger(LOGGER_NAME).info(action, extra={"action_data": data})

        return wrapped

    return decorate(function) if function is not None else decorate
