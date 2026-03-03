"""
Rate limiter and retry utilities for API clients.

This module provides exponential backoff and rate limiting functionality.
"""

import time
import requests
from typing import Callable, Any, Optional
from loguru import logger

from config import get_config


class RateLimiter:
    """Rate limiter with exponential backoff for API calls."""

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor

    def execute_with_retry(
        self,
        func: Callable,
        *args,
        retry_on: Optional[list[int]] = None,
        **kwargs,
    ) -> Any:
        """
        Execute a function with exponential backoff on failure.

        Args:
            func: Function to execute
            *args: Positional arguments for func
            retry_on: List of status codes to retry on (default: [429, 500, 502, 503, 504])
            **kwargs: Keyword arguments for func

        Returns:
            Result from func

        Raises:
            Last exception if all retries fail
        """
        if retry_on is None:
            retry_on = [429, 500, 502, 503, 504]

        last_exception = None
        delay = self.initial_delay

        for attempt in range(self.max_retries + 1):
            try:
                response = func(*args, **kwargs)

                if isinstance(response, requests.Response):
                    if response.status_code in retry_on:
                        if attempt < self.max_retries:
                            logger.warning(
                                "Request failed with status {}, retrying in {:.1f}s (attempt {}/{})",
                                response.status_code,
                                delay,
                                attempt + 1,
                                self.max_retries + 1,
                            )
                            time.sleep(delay)
                            delay = min(delay * self.backoff_factor, self.max_delay)
                            continue
                        else:
                            raise APIResponseError(
                                f"Max retries exceeded",
                                status_code=response.status_code,
                                response_body=response.text,
                            )

                return response

            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < self.max_retries:
                    logger.warning(
                        "Request exception: {}, retrying in {:.1f}s (attempt {}/{})",
                        str(e),
                        delay,
                        attempt + 1,
                        self.max_retries + 1,
                    )
                    time.sleep(delay)
                    delay = min(delay * self.backoff_factor, self.max_delay)
                else:
                    raise

        if last_exception:
            raise last_exception


from exceptions import APIResponseError
