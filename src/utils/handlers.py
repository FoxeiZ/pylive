from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from quart import Response, abort, json, request

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
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
        response_body.update({"extra": extra})

    return Response(
        response=json.dumps(response_body),
        status=status_code,
        content_type="application/json",
    )


async def create_error_response(*args: Any, **kwargs: Any) -> Response:
    return await create_response(*args, is_error=True, **kwargs)


def get_args(
    data: dict[str, str],
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
            if arg_type is bool:
                extracted_args[arg_name] = data.get(arg_name) in ("1", "true", "True")
            else:
                extracted_args[arg_name] = arg_type(data.get(arg_name))
        elif raise_on_missing:
            raise KeyError(f"{arg_name} is required")

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
                    logger.warning(f"Unsupported request method: {request.method}")
                    return abort(
                        await create_error_response(
                            message="Unsupported request method", status_code=405
                        )
                    )

                if data is None:
                    logger.warning("No data provided in request")
                    return abort(
                        await create_error_response(
                            message="No data provided", status_code=400
                        )
                    )

                kwargs.update(get_args(data, required_args, raise_on_missing=True))
                if optional_args is not None:
                    kwargs.update(get_args(data, optional_args, raise_on_missing=False))

                return await func(*args, **kwargs)

            except KeyError as e:
                logger.error(f"Missing argument: {e}")
                return abort(
                    await create_error_response(
                        message=f"Missing argument: {e}", status_code=400
                    )
                )

            except Exception as e:
                logger.error(f"Error validating request arguments: {e}")
                return abort(
                    await create_error_response(
                        message="Internal Server Error", status_code=500
                    )
                )

        wrapper.__name__ = func.__name__  # type: ignore
        return wrapper

    return decorator
