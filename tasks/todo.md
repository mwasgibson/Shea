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

## Phase 5: Intent Understanding & Planning

- [x] Contracts: `ModelResponse`; `Intent.task_id` field
- [x] `shea.model` — `ModelProvider` port (`generate`/`health`/`capabilities`,
      `stream()` deliberately deferred), `ScriptedModelProvider` (deterministic
      queued-response double, not a production adapter)
- [x] `shea.understanding` — `DeterministicIntentMatcher` (pure, ordered substring
      triggers) + `IntentParser` (pure) implementing the doc's hybrid: deterministic
      first, model fallback second; `AmbiguousIntentError` below confidence
      threshold, `MalformedModelOutputError` for unusable model output
- [x] `shea.planning` — `PlanTemplateRegistry` (pure), `validate_plan()` (pure —
      the "model suggested this" vs "Shea will act on this" boundary),
      `capabilities_for_plan()` (pure — bridges Planning to Decision), and
      `PlanningService` (integration layer, sole caller of `start_planning`/
      `plan_ready`/`plan_failed`/`block`/`attach_plan`)
- [x] `Orchestrator.attach_plan()` — keeps Task mutation centralized
- [x] SQLite migration 0005 (`intents`) + `SqliteIntentRepository`
- [x] Unit tests: scripted provider (5), intent parser (12), plan templates/
      validator/capabilities (9), planning service integration (8)
- [x] Property tests: ambiguous-iff-below-threshold across randomized
      confidence/threshold pairs; missing-required-field always raises
- [x] Capstone: `test_end_to_end_pipeline.py` — raw text through Planning,
      Decision, Execution, Verification to `COMPLETED`, nothing hand-driving
      the state machine
- [x] Verified directly by the user after a mid-phase sandbox filesystem
      reset required rebuilding from the last checkpointed zip — I don't
      have an exact pytest/mypy/ruff count logged for this phase in
      isolation; the next fully-logged run (217/217, Phase 6 complete)
      includes all of Phase 5 passing within it.

## Phase 6: Security & Trust

- [x] `shea.security` — `NetworkPolicy`/`is_url_allowed` (SSRF: blocks
      loopback/private/link-local/reserved IP literals + known dangerous
      hostnames), `FilesystemPolicy`/`is_path_allowed` (pure logical path-scope
      checking), `SecretRedactor` (pattern-based, recursive over nested
      dicts/lists), `PromptInjectionDetector` (heuristic phrase matching),
      `SecurityGate` (pure pre-execution request scanner), `SecurityService`
      (integration layer — sole caller of `Orchestrator.advance(task_id,
      "security_halt")`)
- [x] `shea.ports.redactor.Redactor` — lets `AuditRecorder` optionally redact
      metadata without `shea.audit` importing `shea.security` (avoids a
      circular dependency, since `security` already depends on `audit`)
- [x] `shea.ports.execution_boundary.ExecutionBoundary`/`ExecutionScope` —
      the real "Sandbox" pipeline stage (timeout + redaction), receiving an
      already-resolved handler rather than a registry, so exactly one code
      path can ever invoke a handler
- [x] `shea.tools.boundary.UnsafeExecutionBoundary` — `ToolExecutor`'s default
      when no real sandbox is configured (lives in `tools/`, not `security/`,
      so `shea.tools` never depends on `shea.security`)
- [x] `shea.security.sandbox.SandboxedExecutionBoundary` — timeout mapped to
      `UnknownOutcomeError` (not `FAILURE` — Section 12.13), response/error
      redaction via injected `SecretRedactor`
- [x] `ExecutionService` gained optional `security_service` param — when
      supplied, `execute()` calls `SecurityService.enforce()` structurally
      before anything else, so security enforcement can't be forgotten by a
      caller (see review below for the bug this replaced)
- [x] Unit tests: network policy (7), filesystem policy (7), secrets (7),
      audit redaction (2), injection detector (4), security gate (8),
      execution boundaries (7), security service (9), plus the
      double-execution regression test in `test_tool_executor.py`
- [x] Property tests: every generated loopback/private/link-local IPv4
      literal always blocked; public-looking IPs outside reserved ranges
      always allowed; paths under/outside an allowed root always
      allowed/blocked
- [x] Capstone updated: `test_end_to_end_pipeline.py` now wires
      `SecurityService` into `ExecutionService` and calls `scan_output()`
      after execution, before verification
- [x] Full suite verified: 253/253 pytest, mypy --strict clean, ruff clean

## Phase 7: Provider Routing & Failover

- [x] `shea.provider` — `ProviderTrustLevel` (LOCAL/TRUSTED_REMOTE/UNTRUSTED,
      the last non-negotiable per Section 8.6), `ProviderProfile`,
      `HealthTracker` (sliding-window HEALTHY/DEGRADED/UNAVAILABLE),
      `FailureCategory` (doc's exact taxonomy) + `RETRYABLE_CATEGORIES` +
      `classify_exception()`, `RoutingRequirements`, `ProviderRouter` (pure
      eligibility filtering + ranking), `ProviderRoutingService`
      (integration layer)
- [x] `ProviderRoutingService` structurally satisfies the `ModelProvider`
      port itself (`generate`/`health`/`capabilities`) — a drop-in
      replacement anywhere a single `ModelProvider` was expected, so
      `IntentParser`/`PlanningService` don't need to know routing exists
- [x] Failover always considers a different eligible provider regardless of
      failure category (a different provider may not share the same cause);
      same-provider retry/backoff is a documented, not-yet-built extension
- [x] `require_local_only` requirement — Section 8.11's exact scenario: a
      local-only requirement can never be satisfied by a remote provider,
      not even as a failover when no local provider exists at all
- [x] Every attempt, failover, exhaustion, and no-eligible-provider case is
      audited via the existing `AuditRecorder`
- [x] Unit tests: health tracker (6), failure classification (7), router
      eligibility (8), routing service integration (12)
- [x] Property tests: UNTRUSTED never eligible regardless of health/
      capabilities (mirrors Phase 2's PolicyVerdict.DENIED property and
      Phase 6's SSRF property); UNAVAILABLE health always excludes;
      eligibility iff required capabilities are a subset of available ones
- [x] Full suite verified: 253/253 pytest, mypy --strict clean, ruff clean

## Not yet built — explicitly flagged, not silently missing

- [ ] Memory & Context management
- [ ] Activation & Audio pipeline
- [ ] Interaction layer (CLI/GUI/API adapters producing a uniform `Request`
      — `PlanningService.create_and_plan()` currently builds `Request`
      itself with `source="text"` hardcoded)
- [ ] Extensions & Updates (plugin manifest, signing, sandboxed activation)
- [ ] Observability beyond the audit trail (structured logs, metrics,
      tracing, correlation IDs across a request)
- [ ] Multi-step plan execution — `ExecutionService` runs one tool call
      per invocation; a real `Plan` with multiple `PlanStep`s is never
      looped over, checkpointed, or resumed
- [ ] Real OS-level sandboxing (namespaces/seccomp/cgroups or platform
      equivalent) — `SandboxedExecutionBoundary` enforces timeout and
      redaction only; a thread timeout does not terminate an underlying
      process, socket, or file handle a tool already opened
- [ ] Tool schemas (input/output JSON schema, per-action argument
      validation) — `ToolDeclaration` has capabilities but no argument
      contract; a malformed argument is only caught by the tool itself
- [ ] Authorization binding to plan/step/argument hash + expiry + replay
      protection — an `Authorization` currently belongs to a task, not to
      a specific plan version; nothing prevents reusing one after the
      plan it was granted for has changed
- [ ] Dedicated secret store (OS keychain/Secret Service/Credential
      Manager) — `SecretRedactor` prevents secrets leaking into audit
      metadata, but there is no `SecretStore.get/set/delete/rotate`
      abstraction; secrets aren't actually managed, just redacted after
      the fact
- [ ] Audit tamper-evidence (hash-chained events) — `audit_events` is
      insert-only by API (`AuditSink` exposes no update/delete), but
      nothing detects direct database tampering
- [ ] Cross-repository transactional atomicity — state, authorization,
      and audit writes each commit independently; a crash between two
      commits can leave contradictory persisted facts. Phase 8 makes
      state+audit atomic for the highest-stakes transitions
      (`Orchestrator.advance`, `SecurityService.enforce`'s halt path);
      a full sweep across every repository is still open
- [ ] Concurrency model (task scheduler, per-tool concurrency limits,
      cancellation as a real execution mechanism, backpressure)
- [ ] Resource governance (CPU/RAM/disk/output-size/call-rate limits)
- [ ] CI/CD (no `.github/workflows` yet — every commit should run pytest
      + mypy --strict + ruff automatically, not on trust)
- [ ] Full testing pyramid — unit + property exist; no integration/E2E/
      adversarial security suite yet (SSRF via IPv6, Unicode path tricks,
      sandbox escape, replay attacks, etc.)

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

---

### Phase 5 Review

**What the capstone test actually proves:** a task can go from a raw text
string to `COMPLETED` calling only public service methods, in the order a
real caller would use them — no test anywhere reaches into the state
machine directly for this path. That's the concrete payoff of every prior
phase's "sole caller of X transition" discipline: the pieces actually
compose.

**Known simplifications, intentional for Phase 5:**

- `DeterministicIntentMatcher` is ordered case-insensitive substring
  matching, not real NLU — documented as a starting point, not a claim of
  sophistication.
- No real model/LLM API integration ships — `ScriptedModelProvider` is a
  deterministic double. Wiring an actual provider is Provider Routing's job.
- `IntentParser`/`PlanningService`'s model-fallback prompts
  (`_build_intent_prompt`, `_build_plan_prompt`) are simple f-strings, not
  tuned prompts — they exist to give the fallback path something concrete
  to validate against, not as production prompt engineering.

**Next natural step (identified at the time):** Security & Trust — noted
as deliberately deferred until there was an actual model boundary to
constrain, which Phase 5 just built.

---

### Phase 6 Review

**A user-caught bug, not a self-caught one — worth recording accurately.**
While reviewing this phase's code, the user found that Security had been
built but never wired into anything (correct — `SecurityGate`/
`SecurityService` existed but nothing called them), and supplied a first
attempt at fixing it via a `ToolExecutor` boundary. That attempt had a real
bug: after computing a response through the configured boundary, the code
fell through to an unconditional second, raw `handler(request)` call —
discarding the boundary's result entirely and, when a boundary was
configured, invoking the handler twice. A non-idempotent tool would have
run its side effect twice. The fix: `ToolExecutor` now has exactly one call
site that can invoke a handler (`self._boundary.run(...)`), with
`UnsafeExecutionBoundary` as the structural default rather than a
special-cased branch — "no boundary configured" and "explicitly configured
for no isolation" are now the same code path, not two.

**A second issue caught during that same review:** the original boundary
attempt reimplemented URL/path scanning inline, checking only arguments
literally named `"path"` or `"url"` — narrower than, and inconsistent
with, `SecurityGate.check_request()`'s general shape-based scan across
every string argument. Consolidated: `SandboxedExecutionBoundary` now
contains zero policy-checking logic of its own — that lives only in
`SecurityGate`, called once, upstream, by `SecurityService.enforce()` —
and does only the mechanical sandboxing (timeout, redaction) a "Sandbox"
pipeline stage is actually responsible for.

**What the tests actually prove:**

- `test_injected_boundary_is_used_and_handler_is_called_exactly_once` —
  a spy boundary and a spy handler both assert call count `== 1`,
  directly disproving the double-invocation bug rather than just testing
  around it.
- `test_argument_key_name_does_not_matter_for_url_detection` — an SSRF
  attempt in an argument named `target` (not `url`) is still caught,
  proving the shape-based scan actually replaced the narrower key-based one.
- `test_enforce_halts_task_on_ssrf_attempt` +
  `test_security_halt_is_terminal_even_after_this_service` — a violation
  drives the task to `SECURITY_HALT`, and that state is then proven
  terminal (any further `advance()` call raises `IllegalTransitionError`),
  not just documented as terminal.
- `test_sandboxed_boundary_raises_unknown_outcome_on_timeout` — a real
  0.3s-sleeping handler against a 0.05s timeout produces `UnknownOutcomeError`,
  not a `FAILURE` outcome — Section 12.13's "connection dies, might have
  succeeded" principle applied to the timeout case specifically, with an
  actual slow handler, not a mocked timer.
- The property tests generate loopback/private/link-local addresses across
  every octet Hypothesis tries and confirm none of them slip through.

**Known simplifications, intentional for Phase 6:**

- `NetworkPolicy`/`FilesystemPolicy` check literal request content, not
  runtime behavior — DNS rebinding (a hostname resolving to a private IP
  at request time) and symlink-based path escapes are both documented,
  explicit gaps that require real network resolution / OS-level realpath
  checks at actual access time, which belongs in a future real sandbox
  runtime, not these pure policy functions.
- `PromptInjectionDetector` is a heuristic phrase list, not a classifier —
  a determined attacker can phrase around it. Documented the same way
  `default_verifier` documents its own honesty about being a fallback,
  not a complete solution.
- `SecurityService.scan_output()` records a security event but does not
  itself halt the task on a detected injection attempt — per research doc
  Section 11.6, untrusted content is data, not authority; a future policy
  phase may want to make repeated or high-confidence detections
  consequential, but that's a policy decision this phase deliberately
  left unmade.
- `SecretRedactor`'s patterns cover common shapes (AWS-style keys, bearer
  tokens, `sk-` prefixes, key=value pairs) but cannot cover every possible
  secret format — defense in depth, not the primary control (secrets
  belong in a dedicated store per Section 11.7, not general context).

**Next natural step:** Provider Routing — the last piece before a real
model can actually be swapped in behind the `ModelProvider` port Phase 5
defined, now that Security constrains what that model is allowed to do.

---

### Phase 7 Review

**What the tests actually prove:**

- `test_no_eligible_provider_raises_without_attempting_any` and
  `test_missing_capability_provider_never_attempted` — both use a
  call-recording provider subclass and assert zero calls, the same
  "prove the handler was never reached" pattern used for Phase 3's
  capability gate and Phase 6's security gate, applied here to provider
  selection.
- `test_require_local_only_never_fails_over_to_remote` — the literal
  scenario research doc Section 8.11 describes, with only a remote
  provider registered: routing must raise rather than quietly using it.
- `test_service_is_a_drop_in_model_provider_for_intent_parser` — actually
  constructs a real `IntentParser` with a `ProviderRoutingService` in the
  `model_provider` slot and parses an intent through it, proving the
  structural-typing claim behaviorally rather than just by inspection.
- The property tests directly mirror the "non-negotiable tier" shape
  established in Phase 2 (`PolicyVerdict.DENIED`) and Phase 6 (SSRF
  blocking): `UNTRUSTED` is swept across every trust level, health state,
  and capability combination Hypothesis generates, and never once
  produces a non-empty eligible list.

**Known simplifications, intentional for Phase 7:**

- No same-provider retry with backoff/jitter (research doc Section
  8.14) — every failure fails over to the next eligible provider
  immediately. `FailureCategory`/`RETRYABLE_CATEGORIES` are captured now
  so that mechanism has correct data to consult when built, but the
  mechanism itself isn't built yet.
- No gradual traffic recovery percentages (Section 8.17's "5% -> 25% ->
  50% -> 100%") — `HealthTracker` recovers to HEALTHY as soon as the
  sliding window's error rate drops, which the doc itself calls an
  acceptable V1 fallback ("a simpler cooldown plus health-check
  mechanism is enough").
- `classify_exception()` only recognizes this codebase's own exception
  types (`ModelUnavailableError`, `MalformedModelOutputError`). A real
  provider adapter integrating an actual API needs to translate its own
  errors (HTTP 429, connection resets, etc.) into the existing taxonomy
  as it's built — documented as an extension point, not a gap discovered
  later.
- No context-window reduction/reassembly on failover (Section 8.12) —
  `ProviderRouter` filters out providers whose `context_limit` is too
  small rather than trying to fit the request into a smaller one.

**Next natural step:** the Activation & Audio pipeline is the last major
research-doc subsystem with no code behind it at all — voice ingress
(mic capture, VAD, wake-word, streaming STT). Alternatively, since a
`ModelProvider` can now be routed but still isn't backed by any real
LLM API, wiring an actual provider adapter (even a single one, e.g. via
an HTTP client behind the `ModelProvider` port) would be the thing that
makes every LLM-shaped piece of this system stop being scripted/simulated.
