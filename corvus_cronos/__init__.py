"""
corvus_cronos — CORVUS + CRONOS integration bridge.

Public API
----------
    from corvus_cronos import CorvosCronosBridge, NegotiationResult, AgentTraceMeta
    from corvus_cronos.qwen_client import QwenClient
    from corvus_cronos.narrator import QwenNarrator

Note on lazy loading
---------------------
`bridge.py` imports the CORVUS and CRONOS packages (resolved from sibling
directories, see bridge.py's sys.path bootstrap) at module load time. Those
are not dependencies of `qwen_client.py`, which is a standalone HTTP client.
`CorvosCronosBridge` et al. are therefore exposed via module `__getattr__`
(PEP 562) so that `import corvus_cronos.qwen_client` — or any other submodule
that does not need the bridge — does not require CORVUS/CRONOS to be present.
"""

__all__ = [
    "CorvosCronosBridge",
    "NegotiationResult",
    "AgentTraceMeta",
]


def __getattr__(name: str):
    if name in __all__:
        from corvus_cronos.bridge import (
            AgentTraceMeta,
            CorvosCronosBridge,
            NegotiationResult,
        )
        globals().update(
            AgentTraceMeta=AgentTraceMeta,
            CorvosCronosBridge=CorvosCronosBridge,
            NegotiationResult=NegotiationResult,
        )
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
