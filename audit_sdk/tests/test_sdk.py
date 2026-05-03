"""
tests/test_sdk.py
==================
Тесты SDK без реального сервера — используем respx для mock httpx.
"""

import pytest
import respx
import httpx

from audit_protocol_sdk import (
    AuditClient, AsyncAuditClient,
    Reply, ConsensusStrategy,
    AuditClientError, ServiceUnavailableError,
)

BASE = "http://localhost:8000"

# ── Фикстуры ─────────────────────────────────────────────────────────────────

DIRECT_RESPONSE = {
    "answer":          "Python — высокоуровневый язык программирования.",
    "confidence":      0.95,
    "source":          "direct",
    "domain":          "tech",
    "strategy":        None,
    "validators":      0,
    "validators_used": [],
}

CONSENSUS_RESPONSE = {
    "answer":          "Антиматерия состоит из античастиц.",
    "confidence":      0.67,
    "source":          "AI Protocol Consensus",
    "domain":          "science",
    "strategy":        "weighted_score",
    "validators":      3,
    "validators_used": ["val_science_1", "val_science_2", "val_broad_1"],
}

# ── Синхронный клиент ─────────────────────────────────────────────────────────

class TestAuditClient:

    @respx.mock
    def test_ask_direct(self):
        """Высокий confidence — ответ direct, validated=False."""
        respx.post(f"{BASE}/ask").mock(
            return_value=httpx.Response(200, json=DIRECT_RESPONSE)
        )
        client = AuditClient(BASE, user_id="tester")
        reply  = client.ask("Расскажи про Python")

        assert isinstance(reply, Reply)
        assert reply.answer     == DIRECT_RESPONSE["answer"]
        assert reply.confidence == 0.95
        assert reply.source     == "direct"
        assert reply.validated  is False
        assert reply.domain     == "tech"
        assert reply.validators == 0

    @respx.mock
    def test_ask_consensus(self):
        """Низкий confidence — ответ через консенсус, validated=True."""
        respx.post(f"{BASE}/ask").mock(
            return_value=httpx.Response(200, json=CONSENSUS_RESPONSE)
        )
        client = AuditClient(BASE)
        reply  = client.ask("Что такое антиматерия?")

        assert reply.validated        is True
        assert reply.source           == "AI Protocol Consensus"
        assert reply.strategy         == "weighted_score"
        assert reply.validators       == 3
        assert "val_science_1"        in reply.validators_used

    @respx.mock
    def test_ask_strategy_override(self):
        """Передаём стратегию на уровне запроса."""
        route = respx.post(f"{BASE}/ask").mock(
            return_value=httpx.Response(200, json=DIRECT_RESPONSE)
        )
        client = AuditClient(BASE, strategy=ConsensusStrategy.WEIGHTED_SCORE)
        client.ask("вопрос", strategy=ConsensusStrategy.MAJORITY_VOTE)

        sent = route.calls[0].request
        import json
        body = json.loads(sent.content)
        assert body["strategy"] == "majority_vote"

    @respx.mock
    def test_service_unavailable(self):
        """ConnectError → ServiceUnavailableError."""
        respx.post(f"{BASE}/ask").mock(side_effect=httpx.ConnectError("refused"))
        client = AuditClient(BASE)
        with pytest.raises(ServiceUnavailableError):
            client.ask("вопрос")

    @respx.mock
    def test_server_error(self):
        """HTTP 500 → AuditClientError."""
        respx.post(f"{BASE}/ask").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        client = AuditClient(BASE)
        with pytest.raises(AuditClientError, match="500"):
            client.ask("вопрос")

    @respx.mock
    def test_reset_session(self):
        """DELETE /session/{user_id} вызывается без ошибок."""
        respx.delete(f"{BASE}/session/tester").mock(
            return_value=httpx.Response(200, json={"reset": True})
        )
        client = AuditClient(BASE, user_id="tester")
        client.reset_session()   # не должно бросать

    @respx.mock
    def test_health(self):
        respx.get(f"{BASE}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        client = AuditClient(BASE)
        h = client.health()
        assert h["status"] == "ok"

    @respx.mock
    def test_context_manager_resets_session(self):
        """with AuditClient() → reset_session() при выходе."""
        respx.post(f"{BASE}/ask").mock(
            return_value=httpx.Response(200, json=DIRECT_RESPONSE)
        )
        respx.delete(f"{BASE}/session/cm_user").mock(
            return_value=httpx.Response(200, json={"reset": True})
        )
        with AuditClient(BASE, user_id="cm_user") as c:
            c.ask("вопрос")
        # __exit__ должен был вызвать reset_session — тест упадёт если нет mock


# ── Reply модель ──────────────────────────────────────────────────────────────

class TestReply:

    def _make(self, **kw) -> Reply:
        defaults = {**DIRECT_RESPONSE, "validated": False}
        defaults.update(kw)
        return Reply(**defaults)

    def test_str_direct(self):
        r = self._make()
        assert "direct"  in str(r)
        assert "95%"     in str(r)

    def test_str_consensus(self):
        r = self._make(**CONSENSUS_RESPONSE, validated=True)
        assert "consensus" in str(r)

    def test_is_confident(self):
        r = self._make(confidence=0.80)
        assert r.is_confident(0.75) is True
        assert r.is_confident(0.90) is False

    def test_summary_contains_key_fields(self):
        r = self._make()
        s = r.summary()
        assert "Ответ"       in s
        assert "Уверенность" in s
        assert "Домен"       in s


# ── Async клиент ─────────────────────────────────────────────────────────────

class TestAsyncAuditClient:

    @pytest.mark.asyncio
    @respx.mock
    async def test_ask_async_direct(self):
        respx.post(f"{BASE}/ask").mock(
            return_value=httpx.Response(200, json=DIRECT_RESPONSE)
        )
        async with AsyncAuditClient(BASE, user_id="async_tester") as client:
            respx.delete(f"{BASE}/session/async_tester").mock(
                return_value=httpx.Response(200, json={"reset": True})
            )
            reply = await client.ask("Расскажи про Python")

        assert reply.answer     == DIRECT_RESPONSE["answer"]
        assert reply.validated  is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_ask_async_consensus(self):
        respx.post(f"{BASE}/ask").mock(
            return_value=httpx.Response(200, json=CONSENSUS_RESPONSE)
        )
        client = AsyncAuditClient(BASE)
        reply  = await client.ask("Что такое антиматерия?")

        assert reply.validated is True
        assert reply.validators == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_async_service_unavailable(self):
        respx.post(f"{BASE}/ask").mock(side_effect=httpx.ConnectError("refused"))
        client = AsyncAuditClient(BASE)
        with pytest.raises(ServiceUnavailableError):
            await client.ask("вопрос")
