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
