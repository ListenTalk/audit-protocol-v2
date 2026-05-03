"""
consensus_service/main.py — сервис :8002
==========================================
Принимает список AgentResponse, применяет стратегию консенсуса,
возвращает ConsensusResult.

Запуск:
    uvicorn consensus_service.main:app --port 8002 --reload
"""

import os
import sys
from collections import Counter
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from shared_models import ConsensusRequest, ConsensusResult, ConsensusStrategy

# ─── App ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[consensus_service] запуск | стратегии: majority_vote, weighted_score, trust_ranking")
    yield

app = FastAPI(title="AI Audit Protocol — Consensus Service", version="3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"service": "consensus_service", "status": "ok"}


@app.post("/consensus", response_model=ConsensusResult)
async def consensus(req: ConsensusRequest):
    if not req.responses:
        raise HTTPException(400, "responses пустой — консенсус невозможен")

    responses = req.responses

    if req.strategy == ConsensusStrategy.MAJORITY_VOTE:
        votes       = Counter(r.answer for r in responses)
        best, cnt   = votes.most_common(1)[0]
        avg_conf    = sum(r.confidence for r in responses if r.answer == best) / cnt

    elif req.strategy == ConsensusStrategy.WEIGHTED_SCORE:
        score_map: dict[str, float] = {}
        for r in responses:
            w = r.confidence * r.trust_rank
            score_map[r.answer] = score_map.get(r.answer, 0) + w
        best        = max(score_map, key=score_map.__getitem__)
        total       = sum(r.confidence * r.trust_rank for r in responses)
        avg_conf    = score_map[best] / total if total else 0.0

    elif req.strategy == ConsensusStrategy.TRUST_RANKING:
        top         = max(responses, key=lambda r: r.trust_rank)
        best        = top.answer
        avg_conf    = top.confidence

    else:
        best     = responses[0].answer
        avg_conf = responses[0].confidence

    return ConsensusResult(
        answer     = best,
        confidence = round(avg_conf, 3),
        strategy   = req.strategy.value,
    )
