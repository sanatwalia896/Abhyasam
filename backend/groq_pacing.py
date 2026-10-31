"""Process-wide pacing and bounded, Retry-After-aware Groq retries."""
import logging
import math
import os
import threading
import time
from collections import deque
from email.utils import parsedate_to_datetime
from functools import lru_cache

from langchain_core.runnables import Runnable

logger = logging.getLogger(__name__)


class ProviderRateLimitError(RuntimeError):
    def __init__(self, retry_after):
        self.retry_after = max(1, math.ceil(retry_after))
        super().__init__(f"Groq is rate-limiting requests. Please retry after {self.retry_after} seconds.")


def retry_seconds(error, default=10):
    headers = getattr(getattr(error, "response", None), "headers", {})
    value = headers.get("retry-after")
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return default


class Pacer:
    def __init__(self, rpm=None, tpm=None, retries=2, max_wait=60, clock=time.monotonic, sleep=time.sleep):
        self.rpm = max(1, float(rpm or os.getenv("GROQ_REQUESTS_PER_MINUTE", "20")))
        self.tpm = max(1, float(tpm or os.getenv("GROQ_TOKENS_PER_MINUTE", "8000")))
        self.retries, self.max_wait = retries, max_wait
        self.clock, self.sleep = clock, sleep
        self.blocked_until = 0
        self.history = deque()
        self.output_history = deque(maxlen=8)
        self.lock = threading.Lock()

    def budget_delay(self, estimate):
        now = self.clock()
        while self.history and self.history[0][0] <= now - 60:
            self.history.popleft()
        count, tokens = len(self.history), sum(item[1] for item in self.history)
        if count + 1 <= self.rpm and tokens + estimate <= self.tpm:
            return 0
        for timestamp, used in self.history:
            count -= 1; tokens -= used
            if count + 1 <= self.rpm and tokens + estimate <= self.tpm:
                return max(0, timestamp + 60 - now)
        raise ValueError("The estimated request exceeds GROQ_TOKENS_PER_MINUTE. Reduce context or configure your actual Groq quota.")

    def invoke(self, call, prompt, output_tokens):
        # A rolling budget allows immediate calls while capacity remains. Actual
        # usage replaces estimates after each response; unused output isn't charged.
        text = prompt.to_string() if hasattr(prompt, "to_string") else str(prompt)
        with self.lock:
            predicted_output = math.ceil(max(self.output_history, default=512) * 1.15)
            estimate = math.ceil(len(text) / 4) + min(output_tokens, predicted_output)
            waited = 0
            for attempt in range(self.retries + 1):
                delay = max(self.budget_delay(estimate), self.blocked_until - self.clock(), 0)
                if delay > self.max_wait - waited:
                    raise ProviderRateLimitError(delay)
                if delay:
                    logger.info("Groq rolling quota exhausted; waiting %.1fs", delay)
                    self.sleep(delay); waited += delay
                try:
                    result = call()
                    usage = getattr(result, "usage_metadata", None)
                    if usage:
                        logger.info("Groq token usage: %s", usage)
                    actual = usage.get("total_tokens") if isinstance(usage, dict) else None
                    self.history.append((self.clock(), max(0, int(actual)) if actual is not None else estimate))
                    if isinstance(usage, dict) and usage.get("output_tokens") is not None:
                        self.output_history.append(max(0, int(usage["output_tokens"])))
                    return result
                except Exception as error:
                    # Failed calls consume a request slot; 429s report no actual token usage.
                    self.history.append((self.clock(), 0))
                    if getattr(error, "status_code", None) != 429:
                        raise
                    retry = retry_seconds(error, default=10 * (attempt + 1))
                    self.blocked_until = max(self.blocked_until, self.clock() + retry)
                    if attempt == self.retries or retry > self.max_wait - waited:
                        raise ProviderRateLimitError(max(retry, self.blocked_until - self.clock())) from error
                    logger.warning("Groq 429: waiting at least %.1fs before bounded retry", retry)


@lru_cache(maxsize=1)
def get_pacer():
    # Construct after .env has been loaded by the application.
    return Pacer()


class PacedGroq(Runnable):
    def __init__(self, client):
        self.client = client

    def invoke(self, input, config=None, **kwargs):
        output_tokens = int(kwargs.get("max_tokens") or self.client.max_tokens or 2048)
        return get_pacer().invoke(lambda: self.client.invoke(input, config=config, **kwargs), input, output_tokens)
