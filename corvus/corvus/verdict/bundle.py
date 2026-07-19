"""
CORVUS Evidence Bundle Sealer
=============================
Writes a deterministic, tamper-evident evidence bundle for CRITICAL verdicts.

A CRITICAL alert claims the evidence was "sealed"; this module makes that claim
true. The bundle is a canonical JSON document plus a SHA-256 seal computed over
it. The seal is float-free by construction — it carries only strings and
integers (Fraction values are serialized as "numerator/denominator" and the
existing analysis/verdict audit hashes are chained in), so it is reproducible
independently of any float formatting.

The seal chains the two hashes CORVUS already computes deterministically
(result.audit_hash over the canonical analysis, verdict.audit_hash over the
score+level), so a verifier can confirm a CRITICAL decision end to end without
trusting the surrounding prose.
"""

import hashlib
import json
import os
import re

from corvus.models import AnalysisResult, Verdict

# Bump when the sealed payload schema changes so old and new seals never collide.
BUNDLE_VERSION = 1


def _safe_name(message_id: str) -> str:
    """Filesystem-safe file stem derived from a message id (which contains ':')."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", message_id)[:120] or "bundle"


def _bundle_payload(result: AnalysisResult, verdict: Verdict) -> dict:
    """The exact, float-free content that the seal is computed over."""
    return {
        "bundle_version": BUNDLE_VERSION,
        "message_id": result.message_id,
        "user_id": result.user_id,
        "channel_id": result.channel_id,
        "timestamp": result.timestamp,
        "verdict_level": verdict.level.value,
        "score": f"{verdict.score.numerator}/{verdict.score.denominator}",
        "active_signals": result.active_signals,
        "baseline_delta": (
            f"{result.baseline_delta.numerator}/{result.baseline_delta.denominator}"
        ),
        "signals_fired": list(verdict.signals_fired),
        "recommendation": verdict.recommendation,
        "analysis_audit_hash": result.audit_hash,
        "verdict_audit_hash": verdict.audit_hash,
    }


def _seal_of(payload: dict) -> str:
    """SHA-256 over the canonical (key-sorted) JSON of the payload."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_seal(result: AnalysisResult, verdict: Verdict) -> str:
    """Return the SHA-256 seal for a (result, verdict) pair without writing it."""
    return _seal_of(_bundle_payload(result, verdict))


def seal_bundle(result: AnalysisResult, verdict: Verdict, bundle_dir: str) -> str:
    """
    Write a sealed evidence bundle to ``bundle_dir`` and return its path.

    The write is atomic (temp file + os.replace) so a reader never observes a
    half-written bundle. Returns the absolute path to the sealed JSON file.
    """
    os.makedirs(bundle_dir, exist_ok=True)
    payload = _bundle_payload(result, verdict)
    bundle = {
        "payload": payload,
        "seal": _seal_of(payload),
        "seal_algorithm": "SHA-256",
    }
    path = os.path.join(bundle_dir, f"{_safe_name(result.message_id)}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, sort_keys=True, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def verify_bundle(path: str) -> bool:
    """
    Recompute the seal from a bundle file and compare it to the stored seal.
    Returns True if the bundle is intact, False if it was tampered with or
    malformed in any way (invalid JSON, missing fields, wrong types).
    Stdlib-only, independent of the producing code.

    FIX: this used to assume a well-formed bundle and let JSONDecodeError,
    KeyError, or TypeError propagate for a malformed file — contradicting its
    own fail-closed contract. A verifier that crashes on a malformed bundle
    is not fail-closed; it is fail-loud-and-then-the-caller-decides, which is
    exactly the ambiguity this function exists to remove.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            bundle = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(bundle, dict):
        return False
    payload = bundle.get("payload")
    if not isinstance(payload, dict):
        return False
    try:
        return _seal_of(payload) == bundle.get("seal")
    except (TypeError, ValueError):
        # _seal_of/json.dumps can reject a payload with non-serializable
        # values (e.g. a tampered field replaced by a non-JSON type upstream).
        return False
