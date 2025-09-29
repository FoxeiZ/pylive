import json
import logging
from http.client import HTTPResponse
from queue import Queue
from random import randint
from threading import Thread
from typing import IO, Callable, Iterable, Literal, TypeVar, Union, overload
from urllib import request as urllib_request

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
