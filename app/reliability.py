
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Callable

from app.provider import Provider


class CircuitOpenError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 2
    base_delay_ms: int = 200
    max_delay_ms: int = 2000
    jitter_ratio: float = 0.1


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout_s: int = 30) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self._state = "closed"
        self._failure_count = 0
        self._opened_at = 0.0

    def allow(self) -> bool:
        if self._state == "open":
            if time.monotonic() - self._opened_at >= self.reset_timeout_s:
                self._state = "half_open"
                return True
            return False
        return True

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self) -> bool:
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()
            return True
        return False


class ResilientProvider(Provider):
    def __init__(
        self,
        provider: Provider,
        name: str,
        retry: RetryConfig,
        circuit_breaker: CircuitBreaker,
        on_error: Callable[[str, str, Exception], None] | None = None,
        on_retry: Callable[[str, str, int], None] | None = None,
        on_circuit_open: Callable[[str], None] | None = None,
    ) -> None:
        self._provider = provider
        self._name = name
        self._retry = retry
        self._breaker = circuit_breaker
        self._on_error = on_error
        self._on_retry = on_retry
        self._on_circuit_open = on_circuit_open

    async def generate(self, request):
        await self._ensure_circuit()
        attempt = 0
        while True:
            try:
                result = await self._provider.generate(request)
                self._breaker.record_success()
                return result
            except Exception as exc:
                opened = self._breaker.record_failure()
                self._emit_error("generate", exc)
                if opened:
                    self._emit_circuit_open()
                if attempt >= self._retry.max_attempts:
                    raise
                attempt += 1
                self._emit_retry("generate", attempt)
                await asyncio.sleep(self._backoff_delay(attempt))

    async def stream(self, request):
        await self._ensure_circuit()
        attempt = 0
        while True:
            yielded = False
            try:
                async for chunk in self._provider.stream(request):
                    yielded = True
                    yield chunk
                self._breaker.record_success()
                return
            except Exception as exc:
                opened = self._breaker.record_failure()
                self._emit_error("stream", exc)
                if opened:
                    self._emit_circuit_open()
                if yielded or attempt >= self._retry.max_attempts:
                    raise
                attempt += 1
                self._emit_retry("stream", attempt)
                await asyncio.sleep(self._backoff_delay(attempt))

    async def _ensure_circuit(self) -> None:
        if not self._breaker.allow():
            self._emit_circuit_open()
            raise CircuitOpenError(f"circuit open for provider {self._name}")

    def _emit_error(self, stage: str, exc: Exception) -> None:
        if self._on_error:
            self._on_error(self._name, stage, exc)

    def _emit_retry(self, stage: str, attempt: int) -> None:
        if self._on_retry:
            self._on_retry(self._name, stage, attempt)

    def _emit_circuit_open(self) -> None:
        if self._on_circuit_open:
            self._on_circuit_open(self._name)

    def _backoff_delay(self, attempt: int) -> float:
        delay_ms = min(
            self._retry.max_delay_ms,
            self._retry.base_delay_ms * (2 ** (attempt - 1)),
        )
        jitter = delay_ms * self._retry.jitter_ratio
        delay_ms += random.uniform(0, jitter)
        return delay_ms / 1000
