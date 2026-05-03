"""
audit_protocol_sdk/async_client.py
====================================
Async-версия клиента для использования в async-коде (FastAPI, asyncio и т.д.).

Использование:
    from audit_protocol_sdk import AsyncAuditClient

    async with AsyncAuditClient("http://localhost:8000") as client:
        reply = await client.ask("Что такое блокчейн?")
        print(reply.answer)
"""

from __future__ import annotations

import httpx
from typing import Optional
from .models import AskRequest, Reply, ConsensusStrategy
from .exceptions import AuditClientError, ServiceUnavailableError


class AsyncAuditClient:
    """
    Асинхронный клиент к AI Audit Protocol.

    Args:
        base_url:  URL main_agent
        user_id:   Идентификатор пользователя / сессии
        strategy:  Стратегия консенсуса
        timeout:   Таймаут запроса в секундах
        api_key:   Опциональный Bearer-ключ
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        user_id:  str = "sdk_user",
        strategy: ConsensusStrategy = ConsensusStrategy.WEIGHTED_SCORE,
        timeout:  float = 60.0,
        api_key:  Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_id  = user_id
        self.strategy = strategy
        self._timeout = timeout
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers = self._headers,
                timeout = self._timeout,
            )
        return self._client

    # ── Основной метод ───────────────────────────────────────────────────────

    async def ask(
        self,
        question: str,
        user_id:  Optional[str] = None,
        strategy: Optional[ConsensusStrategy] = None,
        extra_context: list[dict] | None = None,
    ) -> Reply:
        """Async-версия ask(). Полная документация — в AuditClient.ask()."""
        payload = AskRequest(
            question      = question,
            user_id       = user_id or self.user_id,
            strategy      = strategy or self.strategy,
            extra_context = extra_context or [],
        )

        client = await self._get_client()

        try:
            resp = await client.post(
                f"{self.base_url}/ask",
                json = payload.model_dump(),
            )
        except httpx.ConnectError:
            raise ServiceUnavailableError(
                f"Не удалось подключиться к {self.base_url}."
            )
        except httpx.TimeoutException:
            raise AuditClientError(f"Таймаут запроса ({self._timeout}s)")

        if resp.status_code != 200:
            raise AuditClientError(
                f"Ошибка сервера [{resp.status_code}]: {resp.text[:200]}"
            )

        data = resp.json()
        return Reply(
            answer          = data["answer"],
            confidence      = data["confidence"],
            source          = data["source"],
            domain          = data["domain"],
            validated       = data["source"] != "direct",
            strategy        = data.get("strategy"),
            validators      = data.get("validators", 0),
            validators_used = data.get("validators_used", []),
        )

    async def reset_session(self, user_id: Optional[str] = None) -> None:
        """Async сброс сессии."""
        uid    = user_id or self.user_id
        client = await self._get_client()
        try:
            await client.delete(f"{self.base_url}/session/{uid}")
        except httpx.HTTPError as e:
            raise AuditClientError(f"Ошибка сброса сессии: {e}")

    async def get_log(self) -> list[dict]:
        """Async получение лога."""
        client = await self._get_client()
        try:
            resp = await client.get(f"{self.base_url}/log")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise AuditClientError(f"Ошибка получения лога: {e}")

    async def health(self) -> dict:
        """Async health check."""
        client = await self._get_client()
        try:
            resp = await client.get(f"{self.base_url}/health")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise ServiceUnavailableError(f"Сервис недоступен: {e}")

    # ── Async context manager ────────────────────────────────────────────────

    async def __aenter__(self) -> "AsyncAuditClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.reset_session()
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def __repr__(self) -> str:
        return (
            f"AsyncAuditClient(base_url={self.base_url!r}, "
            f"user_id={self.user_id!r}, strategy={self.strategy.value!r})"
        )
