"""
main_agent/main.py — сервис :8000
===================================
Принимает запрос от клиента, генерирует ответ через Claude,
при низком confidence отправляет в validator_service и consensus_service.

Запуск:
    uvicorn main_agent.main:app --port 8000 --reload
"""

import os
import uuid
import datetime
import httpx
from contextlib import asynccontextmanager
from collections import Counter

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from shared_models import (
    AskRequest, FinalAnswer, AuditPayload,
    ValidateRequest, ConsensusRequest,
    Domain, AgentResponse,
)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import init_db, CaseStore, SessionStore

# ─── Конфиг ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
CLAUDE_MODEL         = "claude-sonnet-4-20250514"
CONSISTENCY_RUNS     = int(os.getenv("CONSISTENCY_RUNS", "3"))
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.77"))
VALIDATOR_URL        = os.getenv("VALIDATOR_URL",  "http://localhost:8001")
CONSENSUS_URL        = os.getenv("CONSENSUS_URL",  "http://localhost:8002")
AGENT_ID             = os.getenv("AGENT_ID", f"main_agent_{uuid.uuid4().hex[:6]}")

# ─── Домены: ключевые слова ───────────────────────────────────────────────────

DOMAIN_KEYWORDS: dict[Domain, list[str]] = {
    Domain.SCIENCE:  ["физик", "химия", "астро", "квант", "антиматерия",
                      "тёмная энергия", "темная энергия", "фрактал", "молекул"],
    Domain.TECH:     ["python", "блокчейн", "нейросет", "алгоритм",
                      "программ", "код", "api", "база данных"],
    Domain.MEDICINE: ["болезн", "лечени", "вирус", "ген", "днк", "мозг", "клетк"],
    Domain.FINANCE:  ["акци", "инвест", "банк", "криптовалют", "биткоин", "экономик"],
}

def classify_domain(text: str) -> Domain:
    t = text.lower()
    scores = {d: sum(1 for kw in kws if kw in t)
              for d, kws in DOMAIN_KEYWORDS.items()}
    best = max(scores, key=scores.__getitem__)
    return best if scores[best] > 0 else Domain.GENERAL

# ─── Claude Engine ───────────────────────────────────────────────────────────

async def claude_generate(
    question: str,
    context: list[dict],
    system: str = "Ты — точный ассистент. Отвечай кратко и по существу.",
) -> tuple[str, float]:
    """
    Вызывает Claude CONSISTENCY_RUNS раз, считает self-consistency confidence.
    Если ключ — placeholder, возвращает mock-ответ (для локального теста).
    """
    if ANTHROPIC_API_KEY == "YOUR_API_KEY_HERE":
        # ── mock режим ──────────────────────────────────────────────────────
        import random
        mock = {
            "python": ("Python — высокоуровневый язык программирования.", 0.95),
            "блокчейн": ("Блокчейн — распределённый реестр данных.", 0.88),
            "квант": ("Квантовые вычисления используют кубиты.", 0.62),
            "антиматерия": ("Антиматерия состоит из античастиц.", 0.40),
        }
        q = question.lower()
        for kw, (ans, conf) in mock.items():
            if kw in q:
                return ans, round(conf + random.gauss(0, 0.02), 3)
        return "Не уверен в ответе.", round(random.uniform(0.15, 0.45), 3)

    # ── реальный API ─────────────────────────────────────────────────────────
    import anthropic
    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [
        *[{"role": m["role"], "content": m["content"]}
          for m in context[-6:] if m.get("role") in ("user", "assistant")],
        {"role": "user", "content": question},
    ]
    answers = []
    for _ in range(CONSISTENCY_RUNS):
        resp = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=512,
            system=system, messages=messages,
        )
        answers.append(resp.content[0].text.strip())

    best, count = Counter(answers).most_common(1)[0]
    return best, round(count / CONSISTENCY_RUNS, 3)

# ─── App ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print(f"[main_agent] запуск | id={AGENT_ID} | порог={CONFIDENCE_THRESHOLD}")
    print(f"  validator → {VALIDATOR_URL}")
    print(f"  consensus → {CONSENSUS_URL}")
    print(f"  db        → {__import__('os').getenv('DB_PATH', '/data/audit_protocol.db')}")
    yield

app = FastAPI(title="AI Audit Protocol — Main Agent", version="3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"service": "main_agent", "agent_id": AGENT_ID, "status": "ok"}


@app.post("/ask", response_model=FinalAnswer)
async def ask(req: AskRequest):
    context = SessionStore.get(req.user_id) + list(req.extra_context)
    domain  = classify_domain(req.question)

    # 1. Генерируем ответ
    raw_answer, confidence = await claude_generate(req.question, context)

    # Сохраняем вопрос в сессию
    SessionStore.append(req.user_id, {"role": "user", "content": req.question})

    # 2. Высокий confidence → прямой ответ
    if confidence >= CONFIDENCE_THRESHOLD:
        SessionStore.append(req.user_id, {"role": "assistant", "content": raw_answer})
        final = FinalAnswer(
            answer=raw_answer, confidence=confidence,
            source="direct", domain=domain.value,
        )
        _log_case(req, raw_answer, confidence, domain, final)
        return final

    # 3. Низкий confidence → Audit Protocol
    payload = AuditPayload(
        agent_id=AGENT_ID, user_id=req.user_id,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        input=req.question, output=raw_answer,
        confidence=confidence, domain=domain.value,
        context=context[-6:],
    )

    async with httpx.AsyncClient(timeout=60) as client:
        # 4. Запрос к validator_service
        try:
            val_resp = await client.post(
                f"{VALIDATOR_URL}/validate",
                json=ValidateRequest(
                    question=req.question, domain=domain,
                    context=context[-6:], n_validators=3,
                ).model_dump(),
            )
            val_resp.raise_for_status()
            validator_responses = [AgentResponse(**r) for r in val_resp.json()]
        except httpx.HTTPError as e:
            raise HTTPException(502, f"validator_service недоступен: {e}")

        # 5. Запрос к consensus_service
        try:
            con_resp = await client.post(
                f"{CONSENSUS_URL}/consensus",
                json=ConsensusRequest(
                    responses=validator_responses,
                    strategy=req.strategy,
                ).model_dump(),
            )
            con_resp.raise_for_status()
            consensus = con_resp.json()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"consensus_service недоступен: {e}")

    final = FinalAnswer(
        answer=consensus["answer"],
        confidence=consensus["confidence"],
        source="AI Protocol Consensus",
        domain=domain.value,
        strategy=consensus["strategy"],
        validators=len(validator_responses),
        validators_used=[r.agent_id for r in validator_responses],
    )
    SessionStore.append(req.user_id, {"role": "assistant", "content": final.answer})
    _log_case(req, raw_answer, confidence, domain, final, payload)
    return final


@app.delete("/session/{user_id}")
async def reset_session(user_id: str):
    SessionStore.delete(user_id)
    return {"user_id": user_id, "reset": True}


@app.get("/log")
async def get_log(
    limit:     int  = 100,
    offset:    int  = 0,
    user_id:   str  = None,
    domain:    str  = None,
    validated: bool = None,
):
    return CaseStore.get_all(limit=limit, offset=offset,
                             user_id=user_id, domain=domain, validated=validated)


@app.get("/log/stats")
async def get_stats():
    return CaseStore.stats()


@app.get("/log/{case_id}")
async def get_case(case_id: int):
    case = CaseStore.get_by_id(case_id)
    if not case:
        from fastapi import HTTPException
        raise HTTPException(404, f"Кейс {case_id} не найден")
    return case


def _log_case(req, raw_answer, confidence, domain, final, payload=None):
    CaseStore.save(
        agent_id         = AGENT_ID,
        user_id          = req.user_id,
        question         = req.question,
        raw_answer       = raw_answer,
        raw_confidence   = confidence,
        domain           = domain.value,
        validated        = final.source != "direct",
        final_answer     = final.answer,
        final_confidence = final.confidence,
        source           = final.source,
        strategy         = final.strategy,
        validators       = final.validators,
        validators_used  = final.validators_used,
        context          = (payload.context if payload else []),
    )
