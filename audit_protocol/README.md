# AI Audit Protocol v3 — FastAPI

## Структура

```
audit_protocol/
├── shared_models.py          # Pydantic-схемы для всех сервисов
├── main_agent/
│   └── main.py               # :8000 — основной агент
├── validator_service/
│   └── main.py               # :8001 — сеть валидаторов
└── consensus_service/
    └── main.py               # :8002 — движок консенсуса
```

## Установка и запуск

### 🐳 Docker (рекомендуется — одна команда)

```bash
cp .env.example .env
# вставь ANTHROPIC_API_KEY в .env

docker compose up --build
```

Сервисы поднимаются в правильном порядке автоматически:
`validator_service` и `consensus_service` → healthcheck → `main_agent`.

```bash
docker compose down          # остановить
docker compose logs -f       # логи всех сервисов
docker compose up -d         # в фоне
```

### 🐍 Локально (3 терминала)

```bash
pip install fastapi uvicorn httpx anthropic

# Терминал 1
uvicorn validator_service.main:app --port 8001 --reload

# Терминал 2
uvicorn consensus_service.main:app --port 8002 --reload

# Терминал 3
export ANTHROPIC_API_KEY="sk-ant-..."
uvicorn main_agent.main:app --port 8000 --reload
```

## Переменные окружения

| Переменная            | Default                    | Описание                        |
|-----------------------|----------------------------|---------------------------------|
| `ANTHROPIC_API_KEY`   | `YOUR_API_KEY_HERE`        | Ключ Anthropic (mock без него)  |
| `CONFIDENCE_THRESHOLD`| `0.60`                     | Порог уверенности               |
| `CONSISTENCY_RUNS`    | `3`                        | Прогонов для self-consistency   |
| `VALIDATOR_URL`       | `http://localhost:8001`    | URL validator_service           |
| `CONSENSUS_URL`       | `http://localhost:8002`    | URL consensus_service           |

## API

### POST /ask  (main_agent :8000)
```json
{
  "question": "Что такое блокчейн?",
  "user_id": "user_123",
  "strategy": "weighted_score"
}
```
Ответ:
```json
{
  "answer": "Блокчейн — распределённый реестр данных.",
  "confidence": 0.88,
  "source": "direct",
  "domain": "tech",
  "validators": 0,
  "validators_used": []
}
```

### POST /validate  (validator_service :8001)
```json
{
  "question": "Что такое антиматерия?",
  "domain": "science",
  "context": [],
  "n_validators": 3
}
```

### POST /consensus  (consensus_service :8002)
```json
{
  "responses": [...],
  "strategy": "weighted_score"
}
```

### GET  /health      — статус каждого сервиса
### GET  /log         — лог кейсов (main_agent)
### DELETE /session/{user_id} — сброс истории диалога

## Как работает confidence

Без logprobs (Anthropic API их не отдаёт) используется **self-consistency**:

```
вопрос задаётся 3 раза при temperature=1
confidence = количество совпадающих ответов / 3

→ 3/3 = 1.00  (полная уверенность)
→ 2/3 = 0.67  (на грани порога 0.60)
→ 1/3 = 0.33  (низкая уверенность → Audit Protocol)
```

## Поток при низком confidence

```
клиент
  → POST /ask (main_agent :8000)
      → уверенность < 60%
      → POST /validate (validator_service :8001)
          → выбирает специалистов по domain
          → каждый вызывает Claude со своим system prompt
          → возвращает list[AgentResponse]
      → POST /consensus (consensus_service :8002)
          → weighted_score / majority_vote / trust_ranking
          → возвращает ConsensusResult
  ← FinalAnswer { source: "AI Protocol Consensus" }
```
