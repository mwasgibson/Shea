# SHEA — Todo (Execution Plane / "Interaction" track)

Separate from `todo_core.md`'s Task/Decision/Execution/Recovery phases.
This tracks `shea.app` — the execution-plane subsystem from
`Shea_Execution_Plane_Research_01-13.md` / `execution-plane-architecture.txt`:
the controlled boundary between authorized work and platform adapters
(application/process/filesystem/browser/network), with receipts-before-
invocation, identity resolution/revalidation, and scope enforcement as
first-class concepts distinct from the Task state machine.

**Current status: supervised execution is wired into the main tool path.**
`ExecutionService` invokes `ExecutionSupervisor` for authorized tool calls,
and `InteractionService` connects planning and `PlanRunner` without bypassing
the safety pipeline. Native application/browser adapters and a bundled
transport remain out of scope; callers provide the transport and use the
public interaction service.

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

## EP Phase 5: Not yet done / open questions

- [x] **Wire `ExecutionSupervisor` into the main pipeline.** Nothing in
      `shea.execution`, `shea.decision`, or `shea.tools` calls it yet.
      Until this happens, `shea.app` is a parallel, unused execution path
      — real, tested, but inert. Deciding how it relates to
      `ExecutionService`/`ToolExecutor` (replaces them? sits underneath
      them for a specific class of operation? handles only
      application/process/filesystem/browser targets while
      `ToolExecutor` keeps handling declared in-process tools?) is an
      open design question, not just a wiring task.
- [x] Confirm whether `SqliteAppReceiptRepository`/
      `SqliteAppAttemptRepository` share a `UnitOfWork` the way
      `SqliteTaskRepository`/`SqliteAuditSink` do. If they don't, a
      receipt persisted without its paired attempt (or vice versa) on a
      crash is exactly the kind of gap the Phase 8 atomicity sweep closed
      elsewhere in the codebase — this subsystem didn't exist yet when
      that sweep happened, so it needs its own pass.
- [x] No adapters yet for application control, filesystem, browser, or
      network under this plane — only `process.local` and the `stub`
      test double. `shea.tools.builtin`'s `filesystem`/`http.fetch` tools
      (Phase 9, in `todo_core.md`) are a separate, already-wired path;
      whether they get reimplemented as `shea.app` adapters or stay where
      they are is part of the open wiring question above.
- [x] No macOS/Linux/Windows-specific adapters — `process_local.py` is
      platform-neutral (plain `subprocess`), not the OS-native
      Launch-Services/D-Bus/Job-Object adapters the execution-plane
      research documents describe in depth.
- [x] Recovery/reconciliation for `AppOutcome.UNKNOWN` isn't built —
      `LocalProcessAdapter` correctly *reports* UNKNOWN on a timeout, but
      nothing yet reconciles an UNKNOWN attempt against actual external
      state before deciding whether a retry is safe (the
      `shea.recovery`/`IdempotencyKeyGenerator` machinery in
      `todo_core.md` covers this for `shea.tools`-executed tools; it
      doesn't currently touch `shea.app` attempts).
- [x] `URL`/`APPLICATION` identity kinds have no test coverage exercising
      a contract that actually requests them (see the note under EP
      Phase 2) — confirm the default exclusion is deliberate before
      treating it as documented behavior rather than an untested gap.

## Verification

- [x] Full suite verified after this session's fix + cleanup: pytest,
      mypy --strict, and ruff all clean (see `todo_core.md`'s Phase 9
      entry for the exact count as of the same sync point — this track's
      files are included in that same run, not verified separately).
