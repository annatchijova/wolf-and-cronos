"""
api_server.py — CORVUS + CRONOS as a hosted product
====================================================
FastAPI service that exposes the sealed-verdict pipeline over HTTPS,
designed for Alibaba Cloud ECS deployment (Docker + Caddy, same pattern
as the rebound and raven-memory deployments).

Endpoints
---------
    POST /analyze   text in -> sealed CORVUS verdict + CRONOS trace ids
                    + optional qwen-plus narration in the caller's language
    GET  /verify    recompute and verify the full CRONOS hash chain
    GET  /traces    recent sealed trace headers
    GET  /health    liveness + configuration surface (no secrets)

Security
--------
- X-API-Token required on all data endpoints when BRIDGE_API_TOKEN is set
  (constant-time comparison). The server logs loudly at startup when it
  is NOT set, so "silently open" is never silent.
- CORS restricted to BRIDGE_ALLOWED_ORIGINS (comma-separated; no
  wildcard-with-credentials).
- Text size is capped by the bridge itself (MAX_TEXT_CHARS).

Architectural invariant
-----------------------
The verdict is sealed by the deterministic engine BEFORE any Qwen call.
Narration is language-flavored prose over a read-only summary; swapping
or removing the narrator cannot move the verdict by a single bit.

Run
---
    uvicorn api_server:app --host 0.0.0.0 --port 8022
"""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from corvus_cronos.bridge import CorvosCronosBridge, MAX_TEXT_CHARS
from corvus_cronos.narrator import _sanitize_text
from corvus_cronos.qwen_client import QwenClient

log = logging.getLogger("qwen_track3.api")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_TOKEN = os.environ.get("BRIDGE_API_TOKEN", "")
DB_PATH = os.environ.get("BRIDGE_DB_PATH", "negotiation.db")
MEMORY_DB_PATH = os.environ.get("BRIDGE_MEMORY_DB_PATH", "corvus_memory.db")
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("BRIDGE_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]

_SUPPORTED_LANGS = {"en", "es", "zh"}

_NARRATION_SYSTEM = {
    "en": (
        "You are a security analyst explaining a manipulation-detection "
        "verdict to a non-technical user, in English. The verdict, score, "
        "and agent votes below are SEALED and immutable — you cannot change "
        "or second-guess any figure. Explain in plain language (max 150 "
        "words) what was detected and what the user should do."
    ),
    "es": (
        "Sos un analista de seguridad explicando un veredicto de deteccion "
        "de manipulacion a una persona no tecnica, en espanol rioplatense. "
        "El veredicto, el puntaje y los votos de los agentes de abajo estan "
        "SELLADOS y son inmutables: no podes cambiar ni cuestionar ninguna "
        "cifra. Explica en lenguaje claro (maximo 150 palabras) que se "
        "detecto y que deberia hacer la persona."
    ),
    "zh": (
        "You are a security analyst. Explain the manipulation-detection "
        "verdict below to a non-technical user, in Simplified Chinese. The "
        "verdict, score, and agent votes are SEALED and immutable — you "
        "cannot change or question any figure. Use plain language, max 150 "
        "words."
    ),
}


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.bridge = CorvosCronosBridge(
        db_path=DB_PATH, memory_db_path=MEMORY_DB_PATH,
    )
    app.state.qwen = QwenClient(model="qwen-plus")
    if not API_TOKEN:
        log.warning(
            "BRIDGE_API_TOKEN is NOT set — all endpoints are open. "
            "Set it before exposing this server to the internet."
        )
    log.info("Bridge ready — db=%s memory=%s qwen=%s",
             DB_PATH, MEMORY_DB_PATH,
             "configured" if app.state.qwen.available else "offline")
    yield
    app.state.bridge.close()
    app.state.qwen.close()


app = FastAPI(
    title="CORVUS + CRONOS",
    description="Sealed manipulation verdicts with a tamper-evident audit chain.",
    version="0.2.0",
    lifespan=_lifespan,
)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Token", "Content-Type"],
    )


def _require_token(request: Request) -> None:
    if not API_TOKEN:
        return  # open mode — loudly logged at startup
    supplied = request.headers.get("X-API-Token", "")
    if not hmac.compare_digest(supplied.encode(), API_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Token.")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    user_id: str = Field(default="anonymous", max_length=128)
    artifact_id: str = Field(default="api", max_length=256)
    lang: str = Field(default="en", description="Narration language: en, es, zh.")
    narrate: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """Live console — analyze messages and watch the chain from a browser."""
    return FileResponse(os.path.join(_WEB_DIR, "dashboard.html"))


@app.get("/health")
def health(request: Request) -> dict:
    return {
        "status": "ok",
        "qwen_narration": (
            "configured" if request.app.state.qwen.available else "offline"
        ),
        "auth": "token" if API_TOKEN else "open",
        "version": app.version,
    }


@app.post("/analyze", dependencies=[Depends(_require_token)])
def analyze(body: AnalyzeRequest, request: Request) -> dict:
    if body.lang not in _SUPPORTED_LANGS:
        raise HTTPException(
            status_code=422,
            detail=f"lang must be one of {sorted(_SUPPORTED_LANGS)}.",
        )
    bridge: CorvosCronosBridge = request.app.state.bridge
    result = bridge.analyze(
        body.text,
        artifact_id=body.artifact_id,
        user_id=body.user_id,
    )

    narration: dict = {"requested": body.narrate, "lang": body.lang}
    if body.narrate:
        qwen: QwenClient = request.app.state.qwen
        if qwen.available:
            summary = (
                f"VERDICT: {result.verdict_level.value}\n"
                f"SCORE: {int(round(float(result.score) * 100))}%\n"
                f"AGENTS FIRED: {', '.join(result.active_agents) or 'none'}\n"
                f"AGENTS SILENT: {', '.join(result.silent_agents) or 'none'}\n"
                f"RATIONALE: {result.verdict_rationale[:800]}\n"
                f"USER MESSAGE (sanitized excerpt): "
                f"{_sanitize_text(body.text, max_chars=300)}"
            )
            narration["text"] = qwen.complete(
                summary, system_prompt=_NARRATION_SYSTEM[body.lang],
            )
            narration["model"] = qwen.model
        else:
            narration["text"] = None
            narration["note"] = (
                "Narration offline — DASHSCOPE_API_KEY not configured. "
                "The sealed verdict below is complete without it."
            )

    return {
        "verdict": result.verdict_level.value,
        "score": {
            "exact": f"{result.score.numerator}/{result.score.denominator}",
            "percent": int(round(float(result.score) * 100)),
        },
        "active_agents": result.active_agents,
        "silent_agents": result.silent_agents,
        "crashed_agents": result.crashed_agents,
        "recommendation": result.verdict_recommendation,
        "devils_advocate": result.devils_advocate,
        "audit": {
            "signal_hash": result.audit_hash,
            "verdict_hash": result.verdict_audit_hash,
            "trace_ids": result.trace_ids,
            "chain_valid": result.chain_valid,
            "warnings": result.audit_warnings,
        },
        "narration": narration,
    }


@app.get("/verify", dependencies=[Depends(_require_token)])
def verify(request: Request) -> dict:
    ok, errors = request.app.state.bridge.verify_chain()
    return {"chain_ok": ok, "errors": errors}


@app.get("/traces", dependencies=[Depends(_require_token)])
def traces(request: Request, agent_id: Optional[str] = None, limit: int = 10) -> dict:
    limit = max(1, min(limit, 50))
    rows = request.app.state.bridge.get_recent_traces(agent_id=agent_id, limit=limit)
    return {"count": len(rows), "traces": rows}
