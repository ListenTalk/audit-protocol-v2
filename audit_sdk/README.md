# audit-protocol-sdk

Python SDK для [AI Audit Protocol](../audit_protocol/).  
Один импорт — и любой агент подключается к протоколу консенсуса.

## Установка

```bash
pip install audit-protocol-sdk
# или из исходников:
pip install -e .
```

## Быстрый старт

```python
from audit_protocol_sdk import AuditClient

client = AuditClient("http://localhost:8000")
reply  = client.ask("Что такое блокчейн?")

print(reply.answer)       # Блокчейн — распределённый реестр данных.
print(reply.confidence)   # 0.88
print(reply.source)       # "direct"
print(reply.validated)    # False
print(reply.domain)       # "tech"
print(reply)              # [→ direct | 88% | tech] Блокчейн — ...
```

## Стратегии консенсуса

```python
from audit_protocol_sdk import AuditClient, ConsensusStrategy

client = AuditClient(
    base_url = "http://localhost:8000",
    user_id  = "my_agent",
    strategy = ConsensusStrategy.WEIGHTED_SCORE,  # default
    # strategy = ConsensusStrategy.MAJORITY_VOTE
    # strategy = ConsensusStrategy.TRUST_RANKING
)
```

## Сессии (история диалога)

```python
# Контекст накапливается автоматически по user_id
r1 = client.ask("Расскажи про блокчейн", user_id="alice")
r2 = client.ask("А как блокчейн связан с биткоином?", user_id="alice")

# Сбросить историю вручную
client.reset_session("alice")

# Или использовать context manager — сброс автоматически при выходе
with AuditClient("http://localhost:8000", user_id="alice") as c:
    r = c.ask("Расскажи про Python")
# ← здесь сессия уже сброшена
```

## Async (FastAPI, asyncio)

```python
from audit_protocol_sdk import AsyncAuditClient

async def handler(question: str) -> str:
    async with AsyncAuditClient("http://localhost:8000") as client:
        reply = await client.ask(question)
        return reply.answer
```

## Обработка ошибок

```python
from audit_protocol_sdk import (
    AuditClient,
    AuditClientError,
    ServiceUnavailableError,
    LowConfidenceError,
)

client = AuditClient("http://localhost:8000")

try:
    reply = client.ask("Что такое тёмная материя?")

    # опционально: бросить ошибку если уверенность слишком низкая
    if not reply.is_confident(threshold=0.7):
        raise LowConfidenceError(reply)

    print(reply.answer)

except ServiceUnavailableError:
    print("Сервис недоступен — проверь docker compose up")

except LowConfidenceError as e:
    print(f"Слишком низкая уверенность: {e.reply.confidence:.1%}")
    print(f"Ответ всё равно: {e.reply.answer}")

except AuditClientError as e:
    print(f"Ошибка протокола: {e}")
```

## Reply — все поля

| Поле              | Тип          | Описание                                         |
|-------------------|--------------|--------------------------------------------------|
| `answer`          | `str`        | Текст ответа                                     |
| `confidence`      | `float`      | Уверенность 0.0–1.0                              |
| `source`          | `str`        | `"direct"` или `"AI Protocol Consensus"`         |
| `domain`          | `str`        | `tech / science / medicine / finance / general`  |
| `validated`       | `bool`       | `True` если прошёл через консенсус               |
| `strategy`        | `str / None` | Стратегия консенсуса (если validated)            |
| `validators`      | `int`        | Кол-во валидаторов (если validated)              |
| `validators_used` | `list[str]`  | ID валидаторов (если validated)                  |

## Методы клиента

```python
client.ask(question, user_id, strategy, extra_context) → Reply
client.reset_session(user_id)      # сбросить историю сессии
client.get_log()                   # список всех кейсов с сервера
client.health()                    # {"status": "ok", ...}
```

## Тесты

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
