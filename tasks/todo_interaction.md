# SHEA — Todo (Execution Plane / "Interaction" track)

Separate from `todo_core.md`'s Task/Decision/Execution/Recovery phases.
This tracks `shea.app` — the execution-plane subsystem from
`Shea_Execution_Plane_Research_01-13.md` / `execution-plane-architecture.txt`:
the controlled boundary between authorized work and platform adapters
(application/process/filesystem/browser/network), with receipts-before-
invocation, identity resolution/revalidation, and scope enforcement as
first-class concepts distinct from the Task state machine.

**Current status: wired into the main tool-execution path.**
`ExecutionService.execute()` still calls `SecurityService.enforce()`,
the idempotency-key check, and `_verify_authorization_binding()` — all
of Phase 6/8's hardening — *before* building an `ExecutionContract` and
calling `ExecutionSupervisor.execute()`. `ExecutionSupervisor` routes
that contract through `ToolExecutorAdapter`, which calls the same
`ToolExecutor.execute()` as before. So this is a wrapping layer added
underneath the existing hardened path, not a second path around it —
worth stating explicitly since a naive first read (a new
`ExecutionSupervisor.execute()` that runs a tool) could easily look like
exactly that kind of bypass, and it was the first thing checked here.
`InteractionService` (raw text → plan → `PlanRunner`) does not go
through `shea.app` at all — it's built on `PlanningService`/`PlanRunner`,
which already goes through `DecisionService`/`ExecutionService` per
step. A CLI (`python -m shea`) and `build_runtime()` bootstrap now exist
as the first real entry point, calling `runtime.reconcile_app_plane()`
on startup to finalize any receipts left stuck by a previous crash.
Native application/browser adapters remain out of scope; only one
adapter (`ToolExecutorAdapter`) is actually registered in
`build_runtime()` — `FilesystemLocalAdapter` and `ApplicationStubAdapter`
exist as code but aren't in the runtime's adapter list.

## EP Phase 1: Contracts, Receipts, Attempts, Supervisor (foundation)

- [x] `shea/app/contracts.py` — `ExecutionContract` (frozen; the
      authorized-work value object — capability, operation, target,
      optional `scope`/`identity_requirements`/`requested_target`),
      `ExecutionReceipt` (mutable, durable — must exist before any
      adapter invoke), `ExecutionAttempt` (one physical invoke under a
      receipt; a retry is a new attempt, same receipt — matches EP
      research's "Execution / Attempt" separation), `AdapterResult`
      (facts only: outcome + evidence + error, never authority).
- [x] `shea/app/enums.py` — `AppOutcome` (SUCCESS/FAILURE/UNKNOWN/
      CANCELLED — the same four-way split as the rest of the codebase,
      not collapsed to a boolean), `ReceiptState` (CREATED → ATTEMPTING →
      FINALIZED), `AttemptState` (CREATED → INVOKED → FINALIZED).
- [x] `shea/app/exceptions.py` — `ContractValidationError`,
      `ReceiptRequiredError` (the receipt-before-invoke invariant made
      into a concrete, raiseable check rather than just a comment).
- [x] `shea/app/supervisor.py` — `ExecutionSupervisor`, "sole entry for
      privileged app-plane work." Ordering is fixed and documented in the
      class docstring: validate → resolve/verify identity → evaluate
      scope → persist receipt+attempt → revalidate → invoke adapter →
      finalize. Concretely:
      - `_validate()` checks required fields present and `expires_at` not
        already passed (handles naive `expires_at` by assuming UTC rather
        than raising a `TypeError` on datetime comparison).
      - Identity is resolved once (`IdentityResolver.resolve()`) then
        revalidated at two phases — `pre_receipt` and `pre_invoke` — so a
        target that changed identity between those two points is caught
        before the adapter ever runs, not after.
      - After persisting the receipt, `execute()` immediately reads it
        back (`self._receipts.get(receipt.id)`) and raises
        `ReceiptRequiredError` if it isn't there — the invariant is
        checked, not just hoped for.
      - **Bug found and fixed this session**: `adapter.invoke()` was
        called with no exception handling. Confirmed by direct
        reproduction (constructing a contract that fails
        `LocalProcessAdapter`'s own executable-allowlist check, which
        raises `ContractValidationError` from inside `invoke()` rather
        than returning an `AdapterResult`): the receipt was left stuck in
        `ATTEMPTING` and the attempt stuck in `INVOKED`, forever, with no
        `outcome` recorded — exactly the "crash mid-operation leaves an
        unreconcilable record" failure mode research doc Section 12.13 /
        the execution-plane docs' UNKNOWN-semantics sections exist to
        prevent. Fixed: `adapter.invoke()` is now wrapped, and any
        exception is captured into `AdapterResult(outcome=FAILURE,
        error=str(exc))` — deliberately FAILURE and not UNKNOWN, since an
        exception raised before any external side effect was attempted
        (the common case: argument validation, policy/allowlist checks)
        means nothing happened. An adapter that genuinely can't tell
        whether its side effect occurred should report UNKNOWN itself
        (see `LocalProcessAdapter`'s own `subprocess.TimeoutExpired`
        handling below) — the supervisor's catch-all is a backstop for
        adapters that raise instead of reporting, not a replacement for
        adapters reporting UNKNOWN accurately themselves. Test:
        `test_supervisor_finalizes_receipt_and_attempt_when_adapter_raises`
        (`tests/unit/test_app_supervisor.py`).
- [x] `shea/app/memory.py` — `InMemoryReceiptRepository` /
      `InMemoryAttemptRepository`, the test doubles used above and in
      `test_app_identity_scope.py`.
- [x] `shea/persistence/sqlite/app_receipt_repository.py` /
      `app_attempt_repository.py` (`SqliteAppReceiptRepository` /
      `SqliteAppAttemptRepository`) + migration `0006_app_execution.sql`
      (`app_receipts`, `app_attempts`, with a `FOREIGN KEY` from attempts
      to receipts and indexes on `contract_id`/`receipt_id`). Not yet
      confirmed whether these follow the same `UnitOfWork`-sharing
      pattern `SqliteTaskRepository`/`SqliteAuditSink` use — check before
      assuming receipt+attempt writes are atomic together the way
      Task+Audit writes are.
- [x] `tests/unit/test_app_sqlite_supervisor.py` — the SQLite-backed
      repositories exercised through the same `ExecutionSupervisor` path
      as the in-memory tests, not just tested for CRUD in isolation.

## EP Phase 2: Identity

- [x] `shea/app/identities.py` — `IdentityKind` (PATH/PROCESS/HOST/URL/
      APPLICATION/OPAQUE), `IdentityAssurance` (BASIC/STRICT/INTEGRITY/
      HIGH_ASSURANCE, matching the macOS-adapter research doc's identity
      assurance levels), `RequestedTarget` → `ResolvedIdentity` →
      `VerifiedIdentity` as three distinct types, not one mutating
      object — matches EP research's identity chain
      (Requested → Resolved → Verified → Executed → Observed).
      `IdentityRequirements.allowed_kinds` defaults to
      `{PATH, PROCESS, HOST, OPAQUE}` — **URL and APPLICATION are not
      allowed unless a contract explicitly opts in** by setting
      `allowed_kinds` itself. Worth confirming this is the intended
      default (conservative-by-default fits the project's general
      posture) rather than an oversight nobody's hit yet, since nothing
      currently exercises a URL-kind contract end to end.
- [x] `shea/app/identity/resolver.py` — `IdentityResolver.resolve()`.
      PATH expands `~` and resolves via `Path.resolve(strict=False)`
      (doesn't require the target to already exist — deliberate, since a
      write target may not exist yet). HOST lowercases/strips. URL
      requires both scheme and hostname present. PROCESS notes explicitly
      that a numeric PID "is not durable identity" and records it as
      requested-only, deferring to the revalidator for anything stronger.
- [x] `shea/app/identity/revalidator.py` — `IdentityRevalidator.verify()`,
      called at `phase="pre_receipt"` and again at `phase="pre_invoke"`.
      PATH at BASIC only checks canonical form; at STRICT+ requires the
      parent directory to actually exist; at INTEGRITY/HIGH_ASSURANCE
      additionally rejects the target if it already exists as a symlink.
      PROCESS at STRICT+ requires an `executable` attribute be present —
      PID alone is rejected, matching macOS-adapter invariant M16 ("PID
      alone cannot establish application identity"). HOST/URL/OPAQUE are
      accepted as "literal identity" at every assurance level — **these
      three get no real verification regardless of assurance**, which
      matters in practice because `IdentityRequirements`' default
      `assurance=BASIC` combined with the default `allowed_kinds` means
      most contracts that don't explicitly ask for something stronger
      will pass through here as a formality. Not a bug — V1 scope, per
      the research doc's own phased approach — but worth being clear-eyed
      about rather than assuming "identity revalidation" means the same
      level of real checking for every kind.
- [x] `tests/unit/test_app_identity_scope.py` + `tests/property/
      test_app_properties.py` — identity resolve/revalidate and scope
      enforcement, property-tested for at least some inputs (haven't
      audited exactly which properties beyond confirming the file exists
      and the suite passes; worth a closer look before calling this
      phase's testing complete).

## EP Phase 3: Scope Enforcement

- [x] `shea/app/scopes.py` — `ExecutionScope` (resources: `wall_time_ms`,
      `output_bytes`, `memory_bytes`; process: `allowed_executables`,
      `allow_shell`, `inherit_environ`; isolation: `require_cgroup`,
      `require_new_session`), `EnforcementStatus` (ENFORCED/
      PARTIALLY_ENFORCED/UNSUPPORTED/NOT_REQUESTED), `ScopeEnforcementReport`.
- [x] `shea/app/scope_enforce.py` — `evaluate_scope()`. Honest about what
      V1 can and can't actually do: `wall_time_ms`/`output_bytes` report
      ENFORCED (and — see Phase 4 below — actually are, in
      `LocalProcessAdapter`), `memory_bytes` and `require_cgroup` report
      UNSUPPORTED, `require_new_session` reports only
      PARTIALLY_ENFORCED. If a *required* control (one the contract's
      scope actually asked for) comes back UNSUPPORTED, `evaluate_scope`
      raises `ContractValidationError` rather than silently proceeding —
      fail-closed on unenforceable requirements, not fail-open.

## EP Phase 4: Adapters

- [x] `shea/app/adapters/base.py` — `Adapter` protocol
      (`name`/`supports(contract)`/`invoke(contract, receipt, attempt)`).
- [x] `shea/app/adapters/stub.py` — `StubAdapter`, no side effects,
      always SUCCESS with echo evidence — the test double used above.
- [x] `shea/app/adapters/process_local.py` — `LocalProcessAdapter`, the
      one adapter with a real side effect so far:
      - No shell: explicitly returns FAILURE if `scope.process.allow_shell`
        is requested, rather than quietly running one — matches AD-006
        ("No Generic Shell Fallback") from the execution-plane
        architecture doc by name.
      - `argv` must be a `list[str]`; anything else is FAILURE before a
        process is ever spawned.
      - Executable allowlist genuinely checked (`_check_executable_allowed`)
        before invocation, not just accepted.
      - `wall_time_ms` is a *real* `subprocess.run(timeout=...)`, and a
        timeout is correctly reported as **UNKNOWN**, not FAILURE — the
        process may have partially run before being killed, so "definitely
        failed" would overstate what's actually known. This is the
        adapter behaving exactly the way the supervisor's catch-all
        (Phase 1 above) assumes well-behaved adapters will.
      - `output_bytes` is a real truncation of captured stdout/stderr,
        not just a declared limit.
      - Environment is NOT inherited from the parent process by default
        (`env = {}` unless an allowlist or `inherit_environ` says
        otherwise) — closes the "ambient environment credentials
        inherited by default" gap the EP research explicitly calls out.
- [x] `shea/app/ports/process.py` — `AdapterContext` (bundles verified
      identity + scope + enforcement report for an adapter to consume).
- [x] **Cleanup this session**: deleted `src/shea/app/ports.py`, a stale
      duplicate of `src/shea/app/ports/__init__.py` (same two Protocols,
      tab-indented instead of space-indented, missing `__all__`) left
      over from converting `ports.py` into a `ports/` package without
      removing the original file. Harmless in practice — Python's import
      system silently prefers the package over the same-named module, so
      `ports.py` was dead code nothing ever actually imported — but
      exactly the kind of divergent-duplicate-copy risk worth deleting on
      sight rather than leaving for someone to edit the wrong one later.
- [x] `shea/app/environment.py` — `probe_environment()`, captures
      platform/runtime facts at invoke time (referenced by the
      supervisor for the `_adapter_context`/metadata it attaches to a
      contract before invoke).

## EP Phase 5: Verified against the actual current code (not just commit titles)

- [x] **`ExecutionSupervisor` wired into the main pipeline** — confirmed
      true. See the header above for the exact call chain and why it's
      a wrap, not a bypass.
- [x] **`SqliteAppReceiptRepository`/`SqliteAppAttemptRepository` share
      `UnitOfWork` with the rest of the system** — confirmed true.
      `build_runtime()` constructs one `SqliteUnitOfWork` and passes the
      same instance to every repository, `Orchestrator`, `SecurityService`,
      and `ExecutionSupervisor`. `ExecutionSupervisor` itself wraps its
      receipt/attempt/evidence writes in `with self._uow:` at 5 separate
      points in `supervisor.py` — genuinely atomic with everything else
      sharing that instance, not just plumbed through and unused.
- [x] **Recovery/reconciliation for `AppOutcome.UNKNOWN` is now built**
      — `shea/app/recovery.py`'s `classify_stuck_attempt()` (pure) +
      `ExecutionSupervisor.reconcile_stuck()`/`reconcile_receipt()`
      (called from `RecoveryService.reconcile_app_plane()`, called from
      `build_runtime()` on every startup). Correctly distinguishes: an
      attempt that was `INVOKED` but never finalized reconciles to
      **UNKNOWN** (the side effect may have happened) and gets
      `RecoveryStatus.QUARANTINED` — a human has to look at it, the
      system doesn't get to decide on its own that it's fine. An attempt
      that was never even `INVOKED` reconciles to FAILURE (safe — nothing
      happened) and gets `RecoveryStatus.RESOLVED`. No adapter is
      re-invoked during reconciliation — this is "finalize honestly,"
      not "auto-retry."
- [~] **Adapters beyond `process.local`/`stub`**: partially true, but not
      the way the checkbox implied. `FilesystemLocalAdapter` (416 lines)
      and `ApplicationStubAdapter` now exist as code — but **`build_runtime()`
      only registers `ToolExecutorAdapter`**. `ApplicationStubAdapter` is
      honest about this itself (always returns FAILURE with "application
      control not implemented in V1"), which is the right way to build a
      placeholder. `FilesystemLocalAdapter` hasn't been read closely yet
      this pass — it's real code, just not reviewed to the same depth as
      the other fixes below, and not wired into the runtime either way.
- [x] **Still no macOS/Linux/Windows-specific adapters** — `process_local.py`
      remains plain `subprocess`, unchanged.
- [ ] **`URL`/`APPLICATION` identity kinds still have no test coverage**
      exercising a contract that actually requests them — not re-checked
      this pass, left as previously stated.

**Two real bugs found and fixed in this integration:**

- **`ExecutionService.execute()` had a duplicated `ToolResponse`
  construction.** Two near-identical blocks built `response = ToolResponse(...)`
  back to back; the second silently overwrote the first, discarding
  `app_verification_result`/`app_verification_explanation` from the
  persisted metadata and the `raw_evidence.get("data", raw_evidence)`
  fallback (which matters for any adapter that doesn't nest its payload
  under an explicit `"data"` key). Fixed by deleting the second,
  regressed block. `test_execution_record_is_persisted` had been updated
  to assert the *regressed* 3-key metadata shape rather than catching the
  regression — updated it to the correct 5-key shape instead of reverting
  the fix to match the test.
- **`VerificationService.verify()` let a generic app-plane signal
  override an actually-registered domain `Verifier`'s decision.** Added
  logic checked `record.metadata["app_verification_result"]` and, if
  present, discarded the `outcome` already computed from the registered
  `Verifier` (or `VerifierRegistry`'s sensible default), replacing it with
  a verdict based only on whether the underlying execution reported
  SUCCESS. This directly contradicts the class's own docstring
  ("EXECUTION SUCCESS != VERIFIED SUCCESS") and the exact scenario
  `default_verifier`'s docstring already explains is why per-tool
  Verifiers exist. Worse: the persisted `VerificationRecord` (built from
  the *correct* outcome, before the override) said `verified=False` while
  the task transitioned to COMPLETED anyway — the audit record and the
  actual consequence disagreed. Caught because it broke
  `test_verify_failure_advances_task_to_failed` and
  `test_custom_verifier_can_override_execution_report` — both of which
  register a verifier that always fails and assert the task ends up
  FAILED, and both were failing before this fix. Fixed by removing the
  override entirely; `VerificationService` now always defers to the
  single `outcome` computed once from the registered verifier.
- Both confirmed via full suite: 379/379 pytest, mypy --strict clean
  (144 files), ruff clean.

**Recurring cleanup, not yet permanent**: `src/shea/app/ports.py` (the
stale, tab-indented, never-imported duplicate of `ports/__init__.py`
documented in EP Phase 4 above) has now reappeared and been deleted
twice in the same number of sync passes — whatever local branch these
commits are coming from still has the old file. Worth deleting it at the
source rather than relying on this file to keep re-flagging it.

## Verification

- [x] Full suite verified after this round's two fixes (duplicate
      `ToolResponse` block, verification-override bug) and the repeated
      `ports.py` cleanup: 379/379 pytest, mypy --strict clean
      (144 source files), ruff clean.

## Post–Phase 10 / EP depth (repo catch-up)

### Done

- [x] `ExecutionPermit` + sealed tool path (`require_permit` on product bootstrap)
- [x] `build_runtime` flags: `include_ep_process` / `include_ep_application` / `include_ep_network`
- [x] `process.local` isolation depth (no shell, allowlist, session/rlimit best-effort)
- [x] `network.local` + redirects re-checked under policy
- [x] `browser.local` (portable) + `browser.engine` gated by `playwright_available()`
- [x] OS application adapters (macOS / Windows / Linux) + ApplicationScope allowlists
- [x] `evaluate_scope` fail-closed for app/network/process allowlists; cgroup still UNSUPPORTED when required
- [x] Optional `[browser]` extra in `pyproject.toml`
- [x] Optional model factory env (Puter / Ollama / Ghost / OpenAI-compatible)

### Still open (polish)

- [ ] Always register `LocalBrowserAdapter` even when Playwright engine is registered (runtime fallback)
- [ ] Package `__init__` refresh (`shea`, `execution`, `model`, `app/adapters/__init__.py`)
- [ ] Production default real `ExecutionBoundary` (not unsafe-by-default)
- [ ] Narrow CLI-facing runtime surface to interaction + reconcile
- [ ] GUI/API interaction adapters beyond CLI
- [ ] Memory, activation/audio, extensions, richer observability
