"""
audit_protocol_sdk/client.py
==============================
Основной клиент SDK. Один класс, один метод.

Использование:
    from audit_protocol_sdk import AuditClient

    client = AuditClient("http://localhost:8000")
    reply  = client.ask("Что такое блокчейн?")

    print(reply.answer)          # текст ответа
    print(reply.confidence)      # 0.0–1.0
    print(reply.source)          # "direct" | "AI Protocol Consensus"
    print(reply.validated)       # True если прошёл через консенсус
    print(reply.domain)          # "tech" | "science" | ...
"""

from __future__ import annotations

import httpx
from typing import Optional
from .models import AskRequest, Reply, ConsensusStrategy
from .exceptions import AuditClientError, ServiceUnavailableError


class AuditClient:
    """
    Синхронный клиент к AI Audit Protocol.

    Args:
        base_url:    URL main_agent (по умолчанию http://localhost:8000)
        user_id:     Идентификатор пользователя / сессии
        strategy:    Стратегия консенсуса (weighted_score по умолчанию)
        timeout:     Таймаут запроса в секундах
        api_key:     Опциональный Bearer-ключ (если сервис защищён)
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

    # ── Основной метод ───────────────────────────────────────────────────────

    def ask(
        self,
        question: str,
        user_id:  Optional[str] = None,
        strategy: Optional[ConsensusStrategy] = None,
        extra_context: list[dict] | None = None,
    ) -> Reply:
        """
        Задать вопрос протоколу.

        Args:
            question:      Текст вопроса
            user_id:       Переопределить user_id для этого запроса
            strategy:      Переопределить стратегию консенсуса
            extra_context: Дополнительный контекст [{"role": "user", "content": "..."}]

        Returns:
            Reply с полями answer, confidence, source, domain, validated, ...

        Raises:
            ServiceUnavailableError: сервис недоступен
            AuditClientError:        ошибка протокола
        """
        payload = AskRequest(
            question      = question,
            user_id       = user_id or self.user_id,
            strategy      = strategy or self.strategy,
            extra_context = extra_context or [],
        )

        try:
            resp = httpx.post(
                f"{self.base_url}/ask",
                json    = payload.model_dump(),
                headers = self._headers,
                timeout = self._timeout,
            )
        except httpx.ConnectError:
            raise ServiceUnavailableError(
                f"Не удалось подключиться к {self.base_url}. "
                "Убедитесь что main_agent запущен."
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

    # ── Управление сессией ───────────────────────────────────────────────────

    def reset_session(self, user_id: Optional[str] = None) -> None:
        """Сбросить историю диалога для пользователя."""
        uid = user_id or self.user_id
        try:
            httpx.delete(
                f"{self.base_url}/session/{uid}",
                headers = self._headers,
                timeout = 10.0,
            )
        except httpx.HTTPError as e:
            raise AuditClientError(f"Ошибка сброса сессии: {e}")

    def get_log(self) -> list[dict]:
        """Получить лог всех кейсов с сервера."""
        try:
            resp = httpx.get(
                f"{self.base_url}/log",
                headers = self._headers,
                timeout = 10.0,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise AuditClientError(f"Ошибка получения лога: {e}")

    def health(self) -> dict:
        """Проверить статус сервиса."""
        try:
            resp = httpx.get(
                f"{self.base_url}/health",
                headers = self._headers,
                timeout = 5.0,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise ServiceUnavailableError(f"Сервис недоступен: {e}")

    # ── Context manager ──────────────────────────────────────────────────────

    def __enter__(self) -> "AuditClient":
        return self

    def __exit__(self, *_) -> None:
        self.reset_session()

    def __repr__(self) -> str:
        return (
            f"AuditClient(base_url={self.base_url!r}, "
            f"user_id={self.user_id!r}, strategy={self.strategy.value!r})"
        )
