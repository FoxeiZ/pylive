from __future__ import annotations

import json
import logging
import re
from queue import Queue
from random import randint
from threading import Thread
from typing import TYPE_CHECKING, TypeVar, overload
from urllib import request as urllib_request

if TYPE_CHECKING:
    from http.client import HTTPResponse
    from typing import IO, Callable, Iterable, Literal, Union

logger = logging.getLogger(__name__)


class NonRaisingHTTPErrorProcessor(urllib_request.HTTPErrorProcessor):
    http_response = https_response = lambda self, request, response: response


class MissingValueType:
    def __getattribute__(self, _):
        return self.__class__

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING_TYPE = MissingValueType

T = TypeVar("T")


@overload
def execute_in_thread(
    callable_func: Callable[..., T], *args, wait_for_result: Literal[True], **kwargs
) -> T: ...
@overload
def execute_in_thread(
    callable_func: Callable[..., T], *args, wait_for_result: Literal[False], **kwargs
) -> None: ...
def execute_in_thread(
    callable_func: Callable[..., T], *args, wait_for_result: bool = True, **kwargs
) -> Union[None, T]:
    def thread_wrapper(result_queue: Queue):
        try:
            result = callable_func(*args, **kwargs)
            result_queue.put(result)
            logger.debug(f"Thread execution completed: {callable_func.__name__}")
        except Exception as e:
            logger.error(f"Error in thread execution: {e}")
            result_queue.put(None)

    result_queue = Queue()
    thread = Thread(
        target=thread_wrapper,
        args=(result_queue,),
        name=f"thread-{callable_func.__name__}-{id(result_queue):#x}",
        daemon=True,
    )

    logger.debug(f"Starting thread: {thread.name}")
    thread.start()

    if not wait_for_result:
        return None

    thread.join()
    return result_queue.get_nowait()


T = TypeVar("T")


def get_and_cast(d: dict, key: str | Iterable[str | int], default: T = None) -> T:
    if isinstance(key, str):
        key = [key]

    value = d
    for k in key:
        if isinstance(value, dict) and k in value:
            value = value[k]
        elif isinstance(value, list) and isinstance(k, int) and 0 <= k < len(value):
            value = value[k]
        else:
            return default

    if default is None:
        return value  # pyright: ignore[reportReturnType]

    _type = type(default)
    try:
        return _type(value)  # pyright: ignore[reportCallIssue]
    except (ValueError, TypeError):
        return default


def human_readable_to_int(human_readable: str) -> int:
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


class HTTPRequestManager:
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Connection": "keep-alive",
    }

    @staticmethod
    def make_request(
        url: str,
        method: str = "GET",
        data=None,
        headers=None,
        enable_compression: bool = False,
        use_proxy: bool = True,
        *args,
        **kwargs,
    ) -> HTTPResponse:
        logger.debug(f"Making {method} request to: {url}")

        request_headers = HTTPRequestManager.DEFAULT_HEADERS.copy()
        if headers:
            request_headers.update(headers)

        if enable_compression:
            request_headers["Accept-Encoding"] = "gzip, deflate, br"
        else:
            request_headers["Accept-Encoding"] = "identity"

        request_data = None
        if data:
            if isinstance(data, dict):
                request_data = bytes(json.dumps(data), encoding="utf-8")
                if "Content-Type" not in request_headers:
                    request_headers["Content-Type"] = "application/json"
            else:
                request_data = data

        try:
            request_obj = urllib_request.Request(
                url=url,
                data=request_data,
                headers=request_headers,
                method=method,
            )

            opener = urllib_request.build_opener(NonRaisingHTTPErrorProcessor())
            response = opener.open(request_obj, *args, **kwargs)

            if response.getcode() >= 400:
                logger.warning(f"HTTP error {response.getcode()} for {url}")
                if use_proxy:
                    logger.info("Attempting proxy request")
                    return HTTPRequestManager._make_proxy_request(url, *args, **kwargs)

            logger.debug(f"Request successful: {response.getcode()}")
            return response

        except Exception as e:
            logger.error(f"Request failed for {url}: {e}")
            if use_proxy:
                logger.info("Attempting proxy request due to exception")
                return HTTPRequestManager._make_proxy_request(url, *args, **kwargs)
            raise

    @staticmethod
    def _make_proxy_request(url: str, *args, **kwargs) -> HTTPResponse:
        logger.debug(f"Making proxy request for: {url}")

        if "proxysite" in url:
            logger.warning("Proxy URL detected, returning error page")
            return HTTPRequestManager.make_request(
                "https://catbox.moe/error.html",
                method="GET",
                use_proxy=False,
                *args,
                **kwargs,
            )

        proxy_number = randint(1, 15)
        proxy_url = (
            f"https://eu{proxy_number}.proxysite.com/includes/process.php?action=update"
        )

        proxy_data = {"d": url, "allowCookies": "on"}

        return HTTPRequestManager.make_request(
            proxy_url,
            method="POST",
            data=proxy_data,
            use_proxy=False,  # Prevent recursive proxy calls
            *args,
            **kwargs,
        )


class StreamDataProcessor:
    @staticmethod
    def iterate_stream_chunks(
        data_source: Union[IO, HTTPResponse, None], chunk_size: int = 1024
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


def time_string_to_seconds(time_str: str) -> float:
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

        time_parts = []
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


def seconds_to_time_string(seconds: Union[int, float]) -> str:
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
