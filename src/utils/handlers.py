from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from quart import Response, json, request

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from typing import Any


logger = logging.getLogger(__name__)


async def create_response(
    data: Any = None,
    message: str = "success",
    is_error: bool = False,
    status_code: int = 200,
    extra: Any = None,
) -> Response:
    response_body = {
        "msg": message,
        "error": is_error,
        "data": data or None,
    }

    if extra:
        response_body["extra"] = extra

    try:
        response_json = json.dumps(response_body)
    except (TypeError, ValueError):
        logger.warning("failed to serialize response body directly, falling back to default string conversion")
        response_json = json.dumps(response_body, default=str)

    return Response(
        response=response_json,
        status=status_code,
        content_type="application/json",
    )


async def create_error_response(*args: Any, **kwargs: Any) -> Response:
    return await create_response(*args, is_error=True, **kwargs)


def get_args(
    data: Mapping[str, Any],
    check_args: Iterable[str | tuple[str, type]],
    raise_on_missing: bool = False,
) -> dict[str, Any]:
    extracted_args: dict[str, Any] = {}
    for arg in check_args:
        if isinstance(arg, tuple):
            arg_name, arg_type = arg
        else:
            arg_name, arg_type = arg, str

        if arg_name in data:
            val = data.get(arg_name)
            if arg_type is bool:
                extracted_args[arg_name] = str(val).lower() in ("1", "true", "yes")
            else:
                try:
                    extracted_args[arg_name] = arg_type(val)
                except (ValueError, TypeError) as e:
                    raise ValueError(
                        f"invalid type for argument '{arg_name}': expected {arg_type.__name__}"
                    ) from e
        elif raise_on_missing:
            raise KeyError(f"'{arg_name}' is required")

    return extracted_args


def validate_request_args(
    required_args: Iterable[str | tuple[str, type]],
    optional_args: Iterable[str | tuple[str, type]] | None = None,
):
    def decorator(func: Callable[..., Any]):
        async def wrapper(*args: Any, **kwargs: Any) -> Response:
            try:
                if request.method == "GET":
                    data = request.args
                elif request.method == "POST":
                    if request.is_json:
                        data = await request.get_json()
                    else:
                        data = cast("Any", await request.form)
                else:
                    logger.warning(f"unsupported request method: {request.method}")
                    return await create_error_response(
                        message="Unsupported request method", status_code=405
                    )

                if data is None:
                    logger.warning("no data provided in request")
                    return await create_error_response(
                        message="No data provided", status_code=400
                    )

                kwargs.update(get_args(data, required_args, raise_on_missing=True))
                if optional_args is not None:
                    kwargs.update(get_args(data, optional_args, raise_on_missing=False))

                return await func(*args, **kwargs)

            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"invalid request arguments: {e}")
                return await create_error_response(
                    message=str(e).strip("'\""), status_code=400
                )

            except Exception as e:
                logger.error(f"error validating request arguments: {e}", exc_info=True)
                return await create_error_response(
                    message="Internal Server Error", status_code=500
                )

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator
