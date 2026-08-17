import logging
import types
import typing
from collections.abc import Mapping
from typing import (
    Any,
    NotRequired,
    get_args,
    get_origin,
    get_type_hints,
)

__all__ = [
    "is_valid_typed_dict",
    "validate_typed_dict",
]

logger = logging.getLogger(__name__)


def _get_base_type(type_hint: type) -> type | tuple[type, ...]:
    """extract base type from type hint, handling Optional/NotRequired/Union."""
    origin = get_origin(type_hint)

    # handle NotRequired
    if origin is NotRequired:
        args = get_args(type_hint)
        return _get_base_type(args[0]) if args else object

    # handle Union (both | and typing.Union)
    if origin is types.UnionType or origin is typing.Union:
        args = get_args(type_hint)
        # filter out NoneType and get remaining types
        non_none_types: list[type] = []
        for arg in args:
            if arg is type(None):
                continue
            base = _get_base_type(arg)
            if isinstance(base, tuple):
                non_none_types.extend(base)
            else:
                non_none_types.append(base)

        if len(non_none_types) == 1:
            return non_none_types[0]
        return tuple(non_none_types) if non_none_types else object

    # handle Literal
    if origin is typing.Literal:
        return type_hint

    # handle generic types like dict[Any, Any], list[str]
    if origin is not None:
        return origin

    return type_hint


def _check_type(value: object, expected_type: type | tuple[type, ...]) -> bool:
    """check if value matches expected type."""
    if expected_type is Any or expected_type is object:
        return True

    # handle Literal
    if get_origin(expected_type) is typing.Literal:
        return value in get_args(expected_type)

    if isinstance(expected_type, tuple):
        return any(_check_type(value, t) for t in expected_type)

    # handle int/float compatibility
    if expected_type is float and isinstance(value, (int, float)):
        return True

    try:
        return isinstance(value, expected_type)
    except TypeError:
        return True


def _is_optional(type_hint: type) -> bool:
    """check if type hint allows None."""
    origin = get_origin(type_hint)

    if origin is NotRequired:
        inner = get_args(type_hint)
        return _is_optional(inner[0]) if inner else True

    if origin is types.UnionType or origin is typing.Union:
        return type(None) in get_args(type_hint)

    return False


def validate_typed_dict[T](
    data: Mapping[str, Any],
    model: type[T],
    *,
    strict: bool = False,
) -> T:
    hints = get_type_hints(model, include_extras=True)
    required_keys: frozenset[str] = getattr(model, "__required_keys__", frozenset())
    optional_keys: frozenset[str] = getattr(model, "__optional_keys__", frozenset())
    all_keys = required_keys | optional_keys

    # check for missing required keys
    missing = required_keys - data.keys()
    if missing:
        raise ValueError(f"missing required keys: {missing}")

    # check for extra keys in strict mode
    if strict:
        extra = data.keys() - all_keys
        if extra:
            raise ValueError(f"unexpected keys: {extra}")

    # validate types for present keys
    errors: list[str] = []
    for key, value in data.items():
        if key not in hints:
            continue

        expected_type = _get_base_type(hints[key])
        if value is None:
            if not _is_optional(hints[key]):
                errors.append(f"key '{key}' cannot be None")
        elif not _check_type(value, expected_type):
            errors.append(
                f"key '{key}' expected {expected_type}, got {type(value).__name__}"
            )

    if errors:
        raise TypeError("; ".join(errors))

    return data  # pyright: ignore[reportReturnType]


def is_valid_typed_dict[T](data: Mapping[str, Any], model: type[T]) -> bool:
    """check if data conforms to TypedDict schema without raising."""
    try:
        validate_typed_dict(data, model)
        return True
    except (ValueError, TypeError) as e:
        logger.debug(f"validation failed for {model.__name__}: {e}")
        return False
