from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, cast
from urllib import request as urllib_request

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from http.client import HTTPResponse
    from typing import IO, Any


logger = logging.getLogger(__name__)


class NonRaisingHTTPErrorProcessor(urllib_request.HTTPErrorProcessor):
    http_response = https_response = lambda self, request, response: response


def get_and_cast[T](
    d: Mapping[str, Any],
    key: str | Iterable[str | int],
    default: T = None,
    strict: bool = False,
) -> T:
    if isinstance(key, str):
        key = [key]

    value = d
    for k in key:
        if (isinstance(value, dict) and k in value) or (
            isinstance(value, list) and isinstance(k, int) and 0 <= k < len(value)  # type: ignore
        ):
            value = value[k]  # type: ignore
        else:
            return default

    if default is None:
        return value  # type: ignore

    if not strict:
        return cast("T", value)

    _type = type(default)
    try:
        return _type(value)  # type: ignore
    except (ValueError, TypeError):
        return default


def human_readable_to_int(human_readable: str | Any) -> int:
    if not human_readable or not isinstance(human_readable, str):
        return 0

    text = human_readable.strip().lower()
    if "no views" in text or "no view" in text:
        return 0

    match = re.search(r"([\d,]+\.?\d*)\s*([kmb])?", text)
    if not match:
        return 0

    number_str = match.group(1)
    suffix = match.group(2)

    try:
        number = float(number_str.replace(",", ""))
    except ValueError:
        return 0

    multipliers = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
    }
    if suffix and suffix in multipliers:
        number *= multipliers[suffix]

    return int(number)


class StreamDataProcessor:
    @staticmethod
    def iterate_stream_chunks(
        data_source: IO[bytes] | HTTPResponse | None, chunk_size: int = 1024
    ) -> Iterable[bytes]:
        if not data_source:
            logger.warning("No data source provided to stream processor")
            return

        logger.debug(f"Starting stream processing with chunk size: {chunk_size}")

        try:
            chunk_count = 0
            for chunk in iter(lambda: data_source.read(chunk_size), b""):
                chunk_count += 1
                yield chunk

            logger.debug(f"Stream processing completed, processed {chunk_count} chunks")

        except Exception as e:
            logger.error(f"Error processing stream data: {e}")
            raise


def time_string_to_seconds(time_str: str | Any) -> float:
    if not time_str or not isinstance(time_str, str):
        logger.debug(f"invalid time string: {time_str}")
        return 0.0

    time_str = time_str.strip()
    if not time_str:
        return 0.0

    try:
        parts = time_str.split(":")
        if len(parts) > 3:
            logger.warning(f"time string has too many parts: {time_str}")
            return 0.0

        time_parts: list[int] = []
        for part in reversed(parts):
            try:
                time_parts.append(int(part))
            except ValueError:
                logger.warning(f"invalid time component '{part}' in: {time_str}")
                return 0.0

        total_seconds = 0.0
        multipliers = [1, 60, 3600]

        for i, value in enumerate(time_parts):
            if i < len(multipliers):
                total_seconds += value * multipliers[i]
            else:
                logger.warning(f"too many time components in: {time_str}")
                break

        logger.debug(f"converted '{time_str}' to {total_seconds} seconds")
        return total_seconds

    except Exception as e:
        logger.error(f"error converting time string '{time_str}': {e}")
        return 0.0


def seconds_to_time_string(seconds: int | float | Any) -> str:
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "0:00"

    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"
