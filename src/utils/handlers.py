from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flask import Response, abort, json, request

if TYPE_CHECKING:
    from typing import Iterable


logger = logging.getLogger(__name__)


def is_value_present(arg) -> bool:
    if arg is None:
        return False

    if isinstance(arg, (list, dict, str)):
        return len(arg) > 0

    return bool(arg)


def create_response(
    data=None,
    message: str = "success",
    is_error: bool = False,
    status_code: int = 200,
    additional_data=None,
) -> Response:
    response_body = {
        "msg": message,
        "error": is_error,
        "data": data if is_value_present(data) else None,
    }

    if additional_data:
        response_body.update({"additional_data": additional_data})

    return Response(
        response=json.dumps(response_body),
        status=status_code,
        content_type="application/json",
    )


def create_error_response(*args, **kwargs):
    return create_response(*args, is_error=True, **kwargs)


def get_args(
    data: dict,
    check_args: Iterable[str | tuple[str, type]],
    raise_on_missing: bool = False,
) -> dict:
    extracted_args = {}
    for arg in check_args:
        if isinstance(arg, tuple):
            arg_name, arg_type = arg
        else:
            arg_name, arg_type = arg, str

        if arg_name in data:
            extracted_args[arg_name] = arg_type(data.get(arg_name))
        else:
            if raise_on_missing:
                raise KeyError(f"{arg_name} is required")

    return extracted_args


def validate_request_args(
    required_args: Iterable[str | tuple[str, type]],
    optional_args: Iterable[str | tuple[str, type]] | None = None,
):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                if request.method != "GET":
                    logger.warning(f"Unsupported request method: {request.method}")
                    return abort(
                        create_error_response(
                            message="Unsupported request method", status_code=405
                        )
                    )

                data = request.args
                if data is None:
                    logger.warning("No data provided in request")
                    return abort(
                        create_error_response(
                            message="No data provided", status_code=400
                        )
                    )

                kwargs.update(get_args(data, required_args, raise_on_missing=True))
                if optional_args is not None:
                    kwargs.update(get_args(data, optional_args, raise_on_missing=False))

                return func(*args, **kwargs)

            except KeyError as e:
                logger.error(f"Missing argument: {e}")
                return abort(
                    create_error_response(
                        message=f"Missing argument: {e}", status_code=400
                    )
                )

            except Exception as e:
                logger.error(f"Error validating request arguments: {e}")
                return abort(
                    create_error_response(
                        message="Internal Server Error", status_code=500
                    )
                )

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator
