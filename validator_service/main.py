"""
validator_service/main.py — сервис :8001  [v4 — parallel]
============================================================
Ключевое изменение vs v3:
  - все валидаторы вызываются ПАРАЛЛЕЛЬНО через asyncio.gather()
  - Semaphore ограничивает одновременные запросы к API (защита от rate-limit)
  - каждый вызов имеет индивидуальный timeout
  - упавший валидатор не роняет весь запрос (return_exceptions=True)
  - добавлен бенчмарк: заголовок X-Elapsed-Ms в ответе

До:  N валидаторов × T секунд = N×T  (последовательно)
После: max(T1, T2, ..., TN) ≈ T      (параллельно)
"""

import os, sys, asyncio, random, time
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from shared_models import ValidateRequest, AgentResponse, Domain

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
CLAUDE_MODEL      = "claude-sonnet-4-20250514"
CONSISTENCY_RUNS  = int(os.getenv("CONSISTENCY_RUNS", "3"))
VALIDATOR_TIMEOUT = float(os.getenv("VALIDATOR_TIMEOUT", "30"))
MAX_CONCURRENT    = int(os.getenv("MAX_CONCURRENT", "5"))

VALIDATOR_POOL = [
    {"id": "val_science_1",  "spec": [Domain.SCIENCE],  "trust_rank": 0.95,
     "system": "Ты — эксперт в точных науках: физика, химия, астрономия. Отвечай точно."},
    {"id": "val_science_2",  "spec": [Domain.SCIENCE],  "trust_rank": 0.88,
     "system": "Ты — учёный-исследователь в области физики и химии. Давай строгие ответы."},
    {"id": "val_tech_1",     "spec": [Domain.TECH],     "trust_rank": 0.93,
     "system": "Ты — senior software engineer. Отвечай технически точно."},
    {"id": "val_tech_2",     "spec": [Domain.TECH],     "trust_rank": 0.87,
     "system": "Ты — эксперт в ИИ и блокчейн-технологиях. Давай конкретные ответы."},
    {"id": "val_medicine_1", "spec": [Domain.MEDICINE], "trust_rank": 0.91,
     "system": "Ты — медицинский эксперт. Отвечай точно, рекомендуй врача при необходимости."},
    {"id": "val_finance_1",  "spec": [Domain.FINANCE],  "trust_rank": 0.89,
     "system": "Ты — финансовый аналитик с 10-летним опытом. Давай точные финансовые ответы."},
    {"id": "val_general_1",  "spec": [Domain.GENERAL],  "trust_rank": 0.75,
     "system": "Ты — универсальный ассистент. Отвечай честно и по существу."},
    {"id": "val_general_2",  "spec": [Domain.GENERAL],  "trust_rank": 0.70,
     "system": "Ты — энциклопедист широкого профиля. Давай взвешенные ответы."},
    {"id": "val_broad_1",    "spec": [Domain.TECH, Domain.SCIENCE, Domain.FINANCE],
     "trust_rank": 0.80,
     "system": "Ты — эрудит в науке, технологиях и финансах. Отвечай точно."},
]

_semaphore: asyncio.Semaphore | None = None


def select_validators(domain: Domain, n: int) -> list[dict]:
    specialists = [v for v in VALIDATOR_POOL if domain in v["spec"]]
    if len(specialists) < n:
        generals = [v for v in VALIDATOR_POOL
                    if Domain.GENERAL in v["spec"] and v not in specialists]
        specialists += generals[: n - len(specialists)]
    return specialists[: n + 1]


async def call_claude_async(question: str, context: list[dict], system: str) -> tuple[str, float]:
    """Async вызов Claude. Mock: asyncio.sleep(0) для честного event loop."""
    if ANTHROPIC_API_KEY == "YOUR_API_KEY_HERE":
        await asyncio.sleep(0)
        mock = {
            "python":      ("Python — высокоуровневый язык программирования.", 0.95),
            "блокчейн":    ("Блокчейн — распределённый реестр данных.", 0.90),
            "квант":       ("Квантовые вычисления используют кубиты.", 0.67),
            "антиматерия": ("Антиматерия состоит из античастиц.", 0.67),
        }
        q = question.lower()
        for kw, (ans, conf) in mock.items():
            if kw in q:
                return ans, round(conf + random.gauss(0, 0.03), 3)
        return "Не уверен в ответе.", round(random.uniform(0.33, 0.67), 3)

    import anthropic

    def _sync_call() -> tuple[str, float]:
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

    # Синхронный SDK — запускаем в thread чтобы не блокировать event loop
    return await asyncio.to_thread(_sync_call)


async def _run_validator(v: dict, question: str, context: list[dict]) -> AgentResponse | None:
    """
    Один валидатор с Semaphore + timeout + перехватом ошибок.
    Возвращает None если упал — не роняет весь gather.
    """
    async with _semaphore:
        try:
            answer, conf = await asyncio.wait_for(
                call_claude_async(question, context, v["system"]),
                timeout=VALIDATOR_TIMEOUT,
            )
            return AgentResponse(
                agent_id       = v["id"],
                answer         = answer,
                confidence     = conf,
                trust_rank     = v["trust_rank"],
                specialization = [d.value for d in v["spec"]],
            )
        except asyncio.TimeoutError:
            print(f"[validator] TIMEOUT: {v['id']} ({VALIDATOR_TIMEOUT}s)")
            return None
        except Exception as e:
            print(f"[validator] ERROR: {v['id']}: {e}")
            return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _semaphore
    _semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    print(f"[validator_service] v4-parallel | pool={len(VALIDATOR_POOL)} "
          f"| concurrent={MAX_CONCURRENT} | timeout={VALIDATOR_TIMEOUT}s")
    yield

app = FastAPI(title="AI Audit Protocol — Validator Service", version="4.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"service": "validator_service", "validators": len(VALIDATOR_POOL),
            "max_concurrent": MAX_CONCURRENT, "timeout": VALIDATOR_TIMEOUT, "status": "ok"}


@app.post("/validate", response_model=list[AgentResponse])
async def validate(req: ValidateRequest, response: Response):
    selected = select_validators(req.domain, req.n_validators)
    t0       = time.perf_counter()

    # ── ВСЕ ПАРАЛЛЕЛЬНО ──────────────────────────────────────────────────────
    tasks   = [_run_validator(v, req.question, req.context) for v in selected]
    results = await asyncio.gather(*tasks)
    # ─────────────────────────────────────────────────────────────────────────

    valid      = [r for r in results if r is not None]
    elapsed_ms = round((time.perf_counter() - t0) * 1000)

    response.headers["X-Elapsed-Ms"]       = str(elapsed_ms)
    response.headers["X-Validators-Total"] = str(len(selected))
    response.headers["X-Validators-Ok"]    = str(len(valid))

    print(f"[validator_service] {len(valid)}/{len(selected)} OK | {elapsed_ms}ms")

    if not valid:
        raise HTTPException(503, "Все валидаторы вернули ошибку")

    return valid
