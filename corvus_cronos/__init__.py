"""
corvus_cronos — CORVUS + CRONOS integration bridge.

Public API
----------
    from corvus_cronos import CorvosCronosBridge, NegotiationResult, AgentTraceMeta
    from corvus_cronos.qwen_client import QwenClient
    from corvus_cronos.narrator import QwenNarrator
"""

from corvus_cronos.bridge import AgentTraceMeta, CorvosCronosBridge, NegotiationResult

__all__ = [
    "CorvosCronosBridge",
    "NegotiationResult",
    "AgentTraceMeta",
]
