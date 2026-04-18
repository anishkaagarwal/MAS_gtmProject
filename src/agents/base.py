"""
Base agent with retry logic, structured logging, and circuit-breaker pattern.
Every agent inherits from this — no exceptions.
"""

from __future__ import annotations

import asyncio
import time
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from src.models.schemas import AgentRole, AgentStepTrace, TaskStatus

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class AgentError(Exception):
    """Raised when an agent fails after exhausting retries."""

    def __init__(self, agent: str, message: str, last_error: Exception | None = None):
        self.agent = agent
        self.last_error = last_error
        super().__init__(f"[{agent}] {message}")


class CircuitBreaker:
    """
    Prevents cascading failures. If an agent fails N times in a window,
    the breaker opens and immediately rejects calls for a cooldown period.
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._state = "closed"  # closed = healthy, open = rejecting

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                "Circuit breaker OPEN — %d failures in window", self._failure_count
            )

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"

    def allow_request(self) -> bool:
        if self._state == "closed":
            return True
        # Half-open: check if cooldown has elapsed
        if (
            self._last_failure_time
            and time.monotonic() - self._last_failure_time > self.cooldown_seconds
        ):
            self._state = "half-open"
            return True
        return False


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """
    All agents implement `_execute`. The base class wraps it with:
    - Retry with exponential backoff + jitter
    - Circuit breaker
    - Structured trace emission
    - Timeout enforcement
    """

    role: AgentRole
    max_retries: int = 3
    base_delay: float = 1.0  # seconds, doubled each retry
    timeout: float = 30.0  # per-attempt timeout in seconds

    def __init__(self) -> None:
        self._circuit = CircuitBreaker()
        self._call_id: str = ""

    @abstractmethod
    async def _execute(self, input_data: InputT) -> OutputT:
        """Subclass implements the actual agent logic."""
        ...

    @abstractmethod
    def _validate_output(self, output: OutputT) -> list[str]:
        """
        Return a list of issues. Empty list = valid.
        This is the agent's OWN sanity check, separate from the Critic.
        """
        ...

    async def run(self, input_data: InputT) -> tuple[OutputT, AgentStepTrace]:
        """
        Public entry point. Handles retries, circuit-breaker, tracing.
        Returns (output, trace) or raises AgentError.
        """
        self._call_id = str(uuid.uuid4())[:8]
        trace = AgentStepTrace(
            agent=self.role,
            status=TaskStatus.RUNNING,
            started_at=datetime.utcnow(),
            attempt=0,
        )

        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            trace.attempt = attempt

            if not self._circuit.allow_request():
                raise AgentError(
                    self.role.value,
                    "Circuit breaker open — too many recent failures",
                    last_error,
                )

            try:
                logger.info(
                    "[%s][%s] attempt %d/%d",
                    self.role.value,
                    self._call_id,
                    attempt,
                    self.max_retries,
                )

                output = await asyncio.wait_for(
                    self._execute(input_data), timeout=self.timeout
                )

                # Self-validation before returning
                issues = self._validate_output(output)
                if issues:
                    logger.warning(
                        "[%s][%s] self-validation failed: %s",
                        self.role.value,
                        self._call_id,
                        issues,
                    )
                    raise ValueError(f"Self-validation: {issues}")

                self._circuit.record_success()
                trace.status = TaskStatus.SUCCESS
                trace.completed_at = datetime.utcnow()
                trace.duration_ms = int(
                    (trace.completed_at - trace.started_at).total_seconds() * 1000
                )
                trace.summary = f"Completed on attempt {attempt}"
                return output, trace

            except asyncio.TimeoutError:
                last_error = TimeoutError(f"Attempt {attempt} timed out after {self.timeout}s")
                self._circuit.record_failure()
                logger.warning("[%s][%s] timeout on attempt %d", self.role.value, self._call_id, attempt)

            except Exception as e:
                last_error = e
                self._circuit.record_failure()
                logger.warning(
                    "[%s][%s] error on attempt %d: %s",
                    self.role.value,
                    self._call_id,
                    attempt,
                    str(e),
                )

            # Exponential backoff with jitter
            if attempt < self.max_retries:
                import random
                delay = self.base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)

        trace.status = TaskStatus.FAILED
        trace.completed_at = datetime.utcnow()
        trace.duration_ms = int(
            (trace.completed_at - trace.started_at).total_seconds() * 1000
        )
        trace.error = str(last_error)
        raise AgentError(
            self.role.value,
            f"Failed after {self.max_retries} attempts: {last_error}",
            last_error,
        )
