"""
audit_protocol_sdk
===================
Python SDK для AI Audit Protocol.

Быстрый старт:
    from audit_protocol_sdk import AuditClient

    client = AuditClient("http://localhost:8000")
    reply  = client.ask("Что такое блокчейн?")
    print(reply)
"""

from .client       import AuditClient
from .async_client import AsyncAuditClient
from .models       import Reply, ConsensusStrategy
from .exceptions   import AuditClientError, ServiceUnavailableError, LowConfidenceError

__version__ = "1.0.0"
__all__ = [
    "AuditClient",
    "AsyncAuditClient",
    "Reply",
    "ConsensusStrategy",
    "AuditClientError",
    "ServiceUnavailableError",
    "LowConfidenceError",
]
