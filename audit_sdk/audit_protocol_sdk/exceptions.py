"""
audit_protocol_sdk/exceptions.py
"""


class AuditClientError(Exception):
    """Базовая ошибка SDK."""


class ServiceUnavailableError(AuditClientError):
    """Сервис недоступен (connection refused, timeout при старте)."""


class LowConfidenceError(AuditClientError):
    """
    Опциональное исключение — можно бросать вручную если
    confidence ниже приемлемого порога для вашей задачи.

    Пример:
        reply = client.ask("...")
        if not reply.is_confident(0.8):
            raise LowConfidenceError(reply)
    """

    def __init__(self, reply):
        self.reply = reply
        super().__init__(
            f"Низкая уверенность: {reply.confidence:.1%} "
            f"(домен={reply.domain}, источник={reply.source})"
        )
