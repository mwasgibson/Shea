# SHEA — Todo

## Phase 1: Core Foundation

- [x] Directory scaffold (`src/shea/...`, `tests/...`)
- [x] Contracts: enums (`TaskState`, `RiskLevel`, `ExecutionOutcome`) + dataclasses
      (`Request`, `Intent`, `Task`, `Plan`, `PlanStep`, `Decision`, `RiskAssessment`,
      `Authorization`, `AuditEvent`)
- [x] Ports: `TaskRepository`, `PlanRepository`, `AuditSink`, `Clock`, `IdGenerator`
- [x] State machine: transition table (Appendix A) + `next_state()` / `IllegalTransitionError`
- [x] SQLite persistence: connection helper, migrator, repositories for Task/Plan/Audit
- [x] Config: six-layer resolver with security-invariant key enforcement
- [x] Core: `Orchestrator` (create_task / advance / get_task), audits every attempt
- [x] `AuditRecorder`
- [x] Unit tests: state machine, task repository, config resolver, orchestrator
- [x] Property tests (Hypothesis): illegal transitions always rejected
- [x] Run full test suite + mypy --strict + ruff, fix anything red
- [x] Review section below, once verified

## Phase 2: Decision, Policy & Risk Engine

- [x] Contracts: `PolicyVerdict` enum; `Decision.requires_explicit_acknowledgement` field
- [x] Ports: `RiskAssessmentRepository`, `DecisionRepository`, `AuthorizationRepository`
- [x] `PolicyEngine` — deterministic capability-based deny / requires-authorization / allowed
- [x] `RiskEngine` — factor-based classification + explanation (Section 12), never a bare score
- [x] Confirmation-tier rules (research doc Section 4.2): SAFE/LOW auto, MEDIUM implicit-ok,
      HIGH/CRITICAL/UNKNOWN require explicit acknowledgement
- [x] `DecisionService` — the only caller of `Orchestrator.advance(task_id, "authorize_and_run")`;
      raises `PolicyDeniedError` (never overridable) or `AuthorizationRequiredError`
      (overridable via explicit_user_ack) instead of silently proceeding
- [x] SQLite migration 0002 + repositories for risk_assessments / decisions / authorizations
- [x] Unit tests: PolicyEngine, RiskEngine, DecisionService (14 scenarios incl. audit trail)
- [x] Property tests: policy denial never downgraded by capability overlap; verdict always
      one of exactly three values; disjoint capabilities always allowed
- [x] Full suite verified: 68/68 pytest, mypy --strict clean, ruff clean (fresh extraction)

## Phase 3: Tool Registry + Executor

- [x] Contracts: `ToolRequest`/`ToolResponse` (Section 8.4); `Decision.capabilities`
      field so authorized capabilities are persisted, not just passed around at
      runtime
- [x] State machine: added `execution_unknown` event (`RUNNING` -> `BLOCKED`) so
      UNKNOWN outcomes never collapse into `FAILED`
- [x] `ToolDeclaration` + `ToolRegistry` — capability profile + lookup, no
      authorization logic of its own
- [x] `ToolExecutor` — capability gate BEFORE handler lookup; distinguishes
      SUCCESS / FAILURE / UNKNOWN (`UnknownOutcomeError` for the latter)
- [x] `ExecutionService` — looks up authorized capabilities from the persisted
      Decision (not a caller-supplied value); advances the orchestrator based on
      outcome; audits every attempt including capability denials
- [x] SQLite migration 0003 (decisions.capabilities column) + repository update
- [x] Unit tests: registry (6), executor (6), execution service (8)
- [x] Property test: handler fires iff required capabilities ⊆ authorized
      capabilities, across randomized capability set combinations
- [x] Full suite verified: 89/89 pytest, mypy --strict clean, ruff clean

## Phase 4: Verification & Recovery

- [x] Contracts: `ToolExecutionRecord`, `VerificationRecord`, `RecoveryAttempt`
- [x] Ports: `ToolExecutionRepository`, `VerificationRepository`, `RecoveryAttemptRepository`
- [x] `ExecutionService` updated to persist a `ToolExecutionRecord` for every
      attempt (including capability denials), giving Verification something
      structured to read
- [x] `Verifier` abstraction + `VerifierRegistry` (per-tool, mirrors `ToolRegistry`'s
      shape) + documented `default_verifier` fallback
- [x] `VerificationService` — the only caller of `Orchestrator.advance(task_id,
      "verified" | "verification_failed")`
- [x] `Compensator` abstraction + honest `default_compensator` (always reports
      `restored=False` — never optimistic)
- [x] `RecoveryService` — bounded Saga-style retry loop (`FAILED -> RECOVERING ->
      READY | FAILED`) counted from persisted attempts, not an in-memory counter;
      plus `resolve_blocked()` for the `BLOCKED` state Phase 3 introduced but never
      resolved
- [x] SQLite migration 0004 (tool_executions / verifications / recovery_attempts)
      + three new repositories
- [x] Unit tests: verifier (4), verification service (6), recovery service (11)
- [x] Property tests: default verifier only ever verifies genuine SUCCESS+success
      across randomized inputs; default compensator never reports restored
- [x] Full suite verified: 112/112 pytest, mypy --strict clean, ruff clean

## Explicitly deferred to later phases (not started)

- [ ] Intent Understanding & Planning (LLM-in-the-loop, constrained output)
- [ ] Tool Registry + Executor + capability declarations
- [ ] Security & Trust boundary (sandboxing, threat detection, secrets)
- [ ] Provider Routing & failover
- [ ] Memory & Context management
- [ ] Activation & Audio pipeline
- [ ] Extensions & Updates
- [ ] Observability (metrics/tracing) beyond the audit trail
- [ ] Full testing pyramid (integration, E2E, security, chaos) — only unit +
      property exist so far

## Phase 1 Review

**Verified 2026-08-16:**

- `pytest`: 43/43 passed (21 state-machine unit, 4 task-repository, 7
  config-resolver, 8 orchestrator, 3 Hypothesis property tests)
- `mypy --strict`: clean across all 26 source files
- `ruff check .`: clean

**What the property tests actually prove:**

- `next_state()` and `validate_transition()` can never disagree, across
  every `TaskState` × a mix of real event names and random strings.
- Every terminal state (`COMPLETED`, `CANCELLED`, `SECURITY_HALT`) rejects
  every possible event — nothing can move a "done" task anywhere.
- No event other than `authorize_and_run` can ever produce a transition
  into `RUNNING`, from any state — this is the concrete, testable form of
  `PLAN != AUTHORIZATION` (Appendix B).

**Known simplifications, intentional for Phase 1, to revisit later:**

- `PlanRepository.save()` does delete-then-reinsert of steps rather than
  diffing. Fine at current scale; revisit if step counts grow.
- No connection pooling — one `sqlite3.Connection` per test/process. Fine
  until concurrent access is a real requirement (Section 16, "driven by
  measurable requirements," not preemptively).
- `AuditSink` has no query/read API yet, only `record()`. Reads will be
  added when the first consumer (e.g. a CLI or the Decision engine) needs
  them — no speculative API surface.

**Next steps (not started, see "Explicitly deferred" above):** Decision/
Policy/Risk engine is the natural next phase — it's the first subsystem
that actually populates the `Decision`/`RiskAssessment`/`Authorization`
contracts and calls `Orchestrator.advance()` with `authorize_and_run`.

---

## Phase 2 Review

**Verified 2026-08-17 (fresh extraction, not the in-place dev venv):**

- `pytest`: 68/68 passed (43 from Phase 1 + 25 new: 6 policy, 7 risk,
  9 decision-service integration, 3 policy property tests)
- `mypy --strict`: clean across all 35 source files
- `ruff check .`: clean

**What the new property tests prove:**

- Whenever a random capability set intersects a random deny list, the
  verdict is always `DENIED` — never downgraded to `REQUIRES_AUTHORIZATION`
  or `ALLOWED` by anything else about the request. `evaluate()` takes no
  argument that changes this, by construction.
- `evaluate()` is total: for any capability set, the result is always
  exactly one of the three `PolicyVerdict` members.

**What the integration tests prove (the actual point of Phase 2):**

- A `PolicyDeniedError` cannot be bypassed by `explicit_user_ack=True` —
  proven directly, not just documented (`test_policy_denied_capability_
  blocks_even_with_explicit_ack`).
- A HIGH-risk action IS unblockable by an explicit acknowledgement —
  `WARNING != DENIAL` (Appendix B), proven as the mirror image of the
  above rather than asserted in a comment.
- When authorization is required and not given, the task's state is
  provably unchanged (`READY`, not `RUNNING`) — no partial advancement.
- Every denial and every "awaiting authorization" block is audited, with
  the audit row asserted directly against the `audit_events` table, not
  just "a method was called."

**Known simplifications, intentional for Phase 2:**

- `PolicyEngine`/`RiskEngine` ship with sensible default capability sets
  from the technical doc's own vocabulary (Section 10.4), but contain no
  actual security policy of their own — a real deployment must supply its
  own `deny_capabilities` (currently empty by default). This is
  deliberate: baking in "real" deny rules without the Security phase's
  threat model behind them would be guessing.
- `DecisionService` assumes the task is already in `READY` state (i.e.
  Planning has already happened). Since Planning doesn't exist yet, tests
  drive the state machine directly via the `ready_task` fixture.
- Risk scoring is a simple factor-count → level mapping (0→SAFE ...
  4→CRITICAL). It matches the doc's Section 12 worked example exactly but
  is intentionally the simplest total function that does — a real risk
  engine will likely need weighted factors, not just counts.
- One risk assessment / one decision per task in Phase 2 (upsert, not
  history). Re-assessment (e.g. after RECOVERING) isn't modeled yet.

**Next natural step:** Tool Registry + Executor. It's the first subsystem
that gives `capabilities` (currently just opaque strings passed into
`DecisionService`) a real backing — actual tools that declare their
required capabilities per technical doc Section 10.4's `Tool` contract —
and the first subsystem that does something once `RUNNING` is reached.

---

### Phase 3 Review

**Verified 2026-08-17 (fresh venv + fresh extraction):**

- `pytest`: 89/89 passed (68 from Phase 1+2, 21 new)
- `mypy --strict`: clean across all 40 source files
- `ruff check .`: clean

**What the tests actually prove:**

- `test_unauthorized_capability_never_reaches_handler` — the handler
  function itself is never called when required capabilities aren't a
  subset of authorized ones, verified with a call-recording spy, not just
  an exception assertion.
- The property test sweeps every combination of `required` vs.
  `authorized` capability sets (both randomized) and confirms the handler
  fires exactly when `required <= authorized` — never partially.
- `test_unknown_outcome_error_is_unknown_not_failure` and
  `test_unknown_outcome_advances_task_to_blocked_not_failed` — UNKNOWN
  stays distinct from FAILURE end-to-end, from the executor through to
  the task's actual persisted state.
- `test_execution_without_decision_raises` — even though only
  `DecisionService` can currently move a task to `RUNNING`, `ExecutionService`
  doesn't trust that invariant blindly; it checks for a persisted
  `Decision` and fails loudly if one is missing.

**Known simplifications, intentional for Phase 3:**

- No sandboxing, resource limits, or filesystem/network scoping — those
  are the Security & Trust phase's job (research doc Section 10/11).
  `ExecutionService` is the orchestration layer around that boundary, not
  the boundary itself.
- No `tool_executions` persistence table yet — execution attempts are
  traceable via `audit_events`, which was judged sufficient for Phase 3's
  scope. A dedicated table becomes worth adding once Verification &
  Recovery needs richer per-attempt state than the audit log carries.
- One tool call per `ExecutionService.execute()` — multi-step plan
  execution (looping over `PlanStep`s) is Planning/Orchestration's job
  once that subsystem exists.

**Next natural step:** Intent Understanding & Planning is the last major
piece before there's a real LLM in the loop — or, if you'd rather harden
what exists first, Verification & Recovery (the `VERIFYING -> COMPLETED`
half of the state machine, currently unimplemented) is a smaller, more
self-contained slice.

---

### Phase 4 Review

**Verified 2026-08-17 (fresh venv + fresh extraction):**

- `pytest`: 112/112 passed (89 from Phase 1-3, 23 new)
- `mypy --strict`: clean across all 49 source files
- `ruff check .`: clean

**What the tests actually prove:**

- `test_custom_verifier_can_override_execution_report` — a tool reporting
  `success=True` does NOT force the task to `COMPLETED`. A registered
  Verifier can independently disagree, and the task ends up `FAILED`.
  This is `EXECUTION SUCCESS != VERIFIED SUCCESS` (Appendix B) proven as
  behavior, not asserted in a docstring.
- `test_resolve_recovery_with_default_compensator_never_claims_success` —
  with no real compensating action configured, recovery resolves to
  `FAILED`, not `READY`. The property test
  `test_default_compensator_never_reports_restored` extends this across
  arbitrary task IDs: the default never once returns `restored=True`.
- `test_recovery_attempts_are_bounded` — drives three full recovery
  cycles and confirms a fourth `begin_recovery()` call raises
  `RecoveryExhaustedError`, with the task provably still `FAILED`
  afterward (exhaustion doesn't silently move it anywhere).
- The `UNKNOWN`-outcome property test from Phase 3
  (`test_unknown_outcome_advances_task_to_blocked_not_failed`) now has a
  real way out: `resolve_blocked()`, tested both for resuming
  (`-> READY`) and cancelling (`-> CANCELLED`).

**Known simplifications, intentional for Phase 4:**

- `default_verifier` trusts a tool's own success report when no
  tool-specific `Verifier` is registered — documented as a known
  limitation in its own docstring, not a silent gap. Real verification
  (e.g. re-reading a file a tool claims to have written) requires
  tool-specific knowledge that belongs with each tool's own registration,
  not a generic engine.
- `RecoveryService.begin_recovery()` does not itself decide *why* a task
  failed or whether retrying is sensible — that judgment belongs to
  whatever calls it (eventually the Orchestrator/Planning layer). Phase 4
  provides the bounded mechanism, not the retry policy.
- One verification record and unlimited tool-execution records per task
  (both listed, not upserted) — matches the append-only pattern used for
  `Authorization` since Phase 2.

**Next natural step:** Intent Understanding & Planning — the last major
piece before a real LLM enters the loop, and the first subsystem that
actually produces a `Plan` (currently just typed shape) for `DecisionService`
to evaluate, rather than tests driving the state machine by hand.
