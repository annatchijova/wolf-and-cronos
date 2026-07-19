# FORGE Audit Follow-up — CORVUS × CRONOS

**Date:** 2026-07-19  
**Method:** four independent FORGE frontends (CLI, Python API, MCP, and
orchestrator), followed by source-level review of every emitted category.  
**Scope:** `corvus-cronos-bridge` at the audit snapshot. The audit produced 73
observations across two independently sealed shards; observations were treated
as leads, not as defects, until re-verified against the live source.

**Rendered evidence:** [standard FORGE report](https://annatchijova.github.io/vigia/forge-report.html) · [extended FORGE report](https://annatchijova.github.io/vigia/forge-extended.html)

## Outcome

The audit did not identify a confirmed remote exploit in the exercised paths.
It did, however, expose five confirmed reliability/integrity defects. All five
are now corrected and verified.

This follow-up matters because several initially dismissed observations were
legitimate *anomaly signals*: the detector's literal classification was a false
positive, but following the surrounding code revealed a different, real
contract violation. A dismissal is therefore evidence to investigate, not a
license to stop reading.

## Confirmed and already corrected

| ID | Issue | Evidence | Status |
|---|---|---|---|
| F-001 | Malformed evidence bundles raised `JSONDecodeError` although `verify_bundle()` promised an integrity boolean. | Direct malformed-bundle induction reproduced the exception. | Corrected in `3b407c3`; malformed structures now fail closed. |
| F-002 | The legacy `Analyzer` folded a crashed detector into an apparent silent result. | Forced detector failure produced no explicit degradation state. | Corrected in `3b407c3`; crash state is represented separately. |

## Confirmed integrity gaps — corrected

| ID | Severity | Finding | Code evidence | Required invariant | Status |
|---|---|---|---|---|---|
| F-003 | High | The sealed-bundle claim was disconnected from the production verdict path. `seal_bundle()` existed, but the audit snapshot showed no production caller and `Verdict.bundle_path` was not assigned. Meanwhile CRITICAL-facing text claimed a sealed evidence bundle. | `corvus/corvus/verdict/bundle.py`, `corvus/corvus/models.py`, `corvus/corvus/verdict/engine.py`, `corvus/mcp_server.py`, `corvus_cronos/bridge.py`. | A CRITICAL result must either carry a successfully written, verifiable bundle path or explicitly report sealing failure; it must never claim a seal that was not produced. | Corrected in `7963581`. `VerdictEngine.compute()` calls `seal_bundle()` for every CRITICAL verdict — the one path both `mcp_server.py` and `bridge.py` pass through — and sets `bundle_path`. A sealing `OSError` does not crash analysis; it retracts the claim in `recommendation` instead of silently presenting success. |
| F-004 | Medium | The CORVUS memory audit-chain hash has canonical JSON but no schema/canonicalization version. | `corvus/corvus/memory/audit.py::_compute_entry_hash`. | A future serialized-schema change must be distinguishable from historical hashes and independently reproducible. | Corrected in `7963581`. Added `CANONICALIZE_VERSION` with the same backward-compatible migration already proven in `cronos/chain.py`: legacy rows (`version` NULL) recompute against their original unversioned form; new rows are versioned. |
| F-005 | Medium | Signal `audit_hash` payloads have no schema version in either the legacy Analyzer or bridge path. | `corvus/corvus/analysis/__init__.py` and `corvus_cronos/bridge.py` Phase 5. | A signal-schema evolution must be bound into the hashed bytes, rather than silently changing the interpretation of an identical-looking SHA-256 value. | Corrected in `7963581`. Both paths now stamp the same `corvus.analysis.CANONICALIZE_VERSION` instead of a silently divergent copy. No migration was needed: nothing re-derives this hash from historically stored data. |

A side effect surfaced by F-003 itself: once `seal_bundle()` actually runs, a
bare `Config()` in a test writes real files under the developer's
`~/.corvus/`. Fixed in the same commit with a repository-root `conftest.py`
that isolates `CORVUS_BUNDLE_DIR`/`CORVUS_DB_PATH` at module level (before
`corvus/mcp_server.py`'s module-level `Config()` singleton can resolve to the
real default), plus one existing test isolated to `tmp_path`.

## Dismissals verified as expected behavior

| FORGE observation | Review result | Why it is not a defect |
|---|---|---|
| Missing `prev_hash` linkage | False positive | Both `cronos/cronos/chain.py` and `corvus/corvus/memory/audit.py` persist, hash, and verify `prev_hash`. |
| Unversioned serialization in CRONOS chain and evidence bundle | False positive for those paths | CRONOS binds `CANONICALIZE_VERSION`; bundles bind `BUNDLE_VERSION`. The related F-004/F-005 gaps are separate paths discovered during review. |
| CRONOS step insertion loop / possible N+1 | False positive | `TraceStore.save_trace()` writes chain entry, header, and steps under one transaction with one final commit and rollback on error. |
| CORVUS baseline mutation without visible transaction | False positive | `store_message()`, the Welford update, and `AuditChain.append()` intentionally share one outer commit. |
| `json.loads()` of stored CRONOS data can raise | Expected fail-closed behavior | Corrupt or tampered persisted evidence must not be silently converted to a plausible trace. |
| Filesystem paths without detector-proven normalization | False positive in reviewed paths | The relevant database/bundle paths are configured/internal, not demonstrated request-controlled remote input. |
| Open API mode when `BRIDGE_API_TOKEN` is unset | Documented deployment choice | Startup emits a loud warning and the README documents it. A future fail-closed deployment policy may be desirable, but this audit did not relabel a documented choice as a hidden vulnerability. |
| Credential-like literals and subprocess calls in tests | Test-only false positives | They are fixed test fixtures and fixed-argument test invocations, not runtime credential or command sinks. |

## Lessons for FORGE

1. A code-fact pattern is not a vulnerability finding without reachability and
   contract context.
2. False positives should retain a review trail: they can identify adjacent
   architectural seams that a narrow detector rule did not model.
3. A green execution path is insufficient when product text makes an integrity
   claim. The claim must be connected to a concrete, tested runtime artifact.
4. Versioning must be assessed per hash domain. A versioned bundle or CRONOS
   chain does not automatically version a separate CORVUS audit hash.

## Verification performed for F-003 through F-005

- `TestCriticalBundleSealing` (`corvus/tests/test_verdict.py`): a CRITICAL
  verdict writes a real, `verify_bundle()`-passing bundle and sets
  `bundle_path`; a non-CRITICAL verdict never seals; a forced sealing failure
  (`OSError`) leaves `bundle_path=None` and visibly amends `recommendation`
  rather than failing silently.
- `test_legacy_unversioned_entry_still_verifies` (`corvus/tests/test_memory.py`):
  a hand-inserted pre-fix row (`version` NULL) still verifies against its
  original unversioned hash, alongside a new versioned entry in the same chain.
- `test_audit_hash_is_versioned` (`corvus/tests/test_analysis.py`) and
  `test_audit_hash_shares_the_analyzer_canonicalize_version`
  (`tests/test_bridge.py`): both signal-hash producers are pinned to the
  shared `CANONICALIZE_VERSION` constant, not independent copies.
- Full suite: 124 passed in `tests/` (default `testpaths`) + 106 passed in
  `corvus/tests/` (outside `testpaths`, run explicitly) = 230 passed, 51
  subtests passed. Confirmed no stray file lands under the real `~/.corvus`
  after a run.
- Fixing commit: `7963581`.

## Publication and restoration record

The complete remediation sequence is published on `origin/main` in
`wolf-and-cronos` (`905367b..7042537`):

- `3b407c3` — fail-closed malformed-bundle verification and visible legacy
  detector crashes (F-001/F-002).
- `e2b3c78` — initial FORGE audit follow-up record.
- `7963581` — production CRITICAL bundle sealing, two additional versioned
  hash domains, and test-environment isolation (F-003/F-004/F-005 plus the
  discovered test-side-effect correction).
- `7042537` — closure update documenting the corrected and verified state of
  all five findings.

Restoration points were retained with the release history, including
`pre-forge-fixes-20260719-182903` and
`pre-forge-anomalies-fix-20260719-185540`.

This report is the repository-level record of the FORGE audit: what was
observed, what was correctly dismissed, which anomalies led to actual defects,
and the code/test evidence that closed each confirmed finding.
