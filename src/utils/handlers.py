import logging

from flask import Response, abort, jsonify, request

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
) -> tuple[Response, int]:
    response_body = {
        "msg": message,
        "error": is_error,
        "data": data if is_value_present(data) else None,
    }

    if additional_data:
        response_body.update({"additional_data": additional_data})

    return jsonify(response_body), status_code


def create_error_response(*args, **kwargs):
    return create_response(*args, is_error=True, **kwargs)


def validate_request_args(required_args: list):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                # Get data based on request method
                if request.method == "GET":
                    data = request.args
                elif request.method == "POST":
                    if request.is_json:
                        data = request.json
                    else:
                        data = request.form
                else:
                    logger.warning(f"Unsupported request method: {request.method}")
                    return abort(500)

                # Validate required arguments
                if data is None:
                    logger.warning("No data provided in request")
                    return abort(400)

                for arg in required_args:
                    if arg not in data:
                        logger.warning(f"Missing required argument: {arg}")
                        return abort(400)
                    else:
                        kwargs[arg] = data.get(arg)

                return func(*args, **kwargs)

            except Exception as e:
                logger.error(f"Error validating request arguments: {e}")
                return abort(500)

        wrapper.__name__ = func.__name__
        return wrapper

    return decorator
