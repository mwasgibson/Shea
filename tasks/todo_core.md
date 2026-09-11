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

## Phase 8: Core Hardening & Enforcement (complete)

- [x] `UnsafeExecutionNotAllowedError` — `ToolExecutor` now requires an
      explicit `allow_unsafe_execution=True` opt-in (or a real
      `ExecutionBoundary`) before it will run a handler with no sandbox
      at all; "nobody configured a boundary" and "explicitly configured
      for no isolation" used to be silently the same thing
- [x] `ExecutionService.security_service` is now a required constructor
      parameter, not `| None = None`. Phases 1-7 made the check skippable
      by construction — a caller could build a working `ExecutionService`
      with no security enforcement at all and nothing would complain.
      There is no `execute()` path that reaches a tool handler without
      `SecurityService.enforce()` running first.
- [x] **Wiring gap found and fixed**: `RetryController` and
      `IdempotencyKeyGenerator` existed, were unit-tested in isolation
      (`tests/unit/test_retry.py`, `tests/unit/test_idempotency.py`), and
      were never called from `RecoveryService` or `ExecutionService` —
      the same class of bug as Phase 6's `SecurityGate`/`SecurityService`
      wiring gap, just not yet caught. Specifically:
      - `RecoveryService.begin_recovery()` did its own linear
        `attempt_number > self._max_attempts` check instead of asking
        `RetryController.can_retry()`, and never called
        `RetryController.delay_for()` at all — every recovery attempt
        proceeded with zero backoff regardless of `RetryPolicy`.
      - Neither service ever called `IdempotencyKeyGenerator.generate()`
        — nothing prevented a retried tool call from duplicating a
        non-idempotent side effect, the exact risk research doc Section
        8.15 / Core Principle #17 name directly.
      Fixed: `RecoveryService` now takes a `RetryController` as its
      single source of truth for both the attempt budget and the
      backoff delay (removed the redundant `DEFAULT_MAX_ATTEMPTS`, which
      duplicated `RetryPolicy.max_attempts` and could have silently
      drifted from it). The computed delay is persisted on
      `RecoveryAttempt.delay_seconds` (migration 0006) rather than
      computed and discarded. `ExecutionService.execute()` now computes
      an idempotency key from (task, tool, action, arguments) before
      every attempt and checks it via the new
      `ToolExecutionRepository.get_by_idempotency_key()` (the SQLite
      index for this already existed — nothing queried it); a prior
      `SUCCESS` or `UNKNOWN` for the same key raises
      `DuplicateExecutionSuppressedError` instead of re-invoking the
      handler. A prior `FAILURE` is deliberately NOT suppressed, since
      by definition no side effect is claimed to have occurred.
- [x] Unit tests proving the fix, not just re-testing the components in
      isolation: `test_duplicate_execution_after_unknown_outcome_is_
      suppressed` (call-recording handler proves it fires exactly once
      across a simulated RUNNING -> BLOCKED -> READY -> RUNNING retry),
      `test_duplicate_suppression_does_not_apply_after_failure` (the
      mirror property — FAILURE must NOT be suppressed),
      `test_begin_recovery_persists_retry_controllers_delay` (fixed
      policy, exact delay assertion), `test_begin_recovery_honors_
      custom_retry_controllers_max_attempts` (proves `RetryController`,
      not a hardcoded value, now governs the budget)
- [x] Full suite verified: 294/294 pytest, mypy --strict clean, ruff clean
- [x] **Cross-repository transactional atomicity for the highest-stakes
      transitions**: `Orchestrator.advance()` (and `create_task()` /
      `attach_plan()`) each wrote a Task's state and recorded its audit
      event as two independently-committed writes — fixed with shared
      re-entrant `UnitOfWork` so task + audit commit or roll back together.
- [x] **Cross-repository transactional atomicity — full sweep.** All SQLite
      repositories require shared `unit_of_work`. Decision, Recovery,
      Execution, Verification, and Planning pair saves with audits under UoW.
- [x] **CI/CD**: `.github/workflows/ci.yml` runs pytest, mypy, and ruff on
      every push and pull request against `main`.
- [x] **Authorization content binding** — `Authorization` carries
      `plan_hash` / `step_hash` / `arguments_hash`, `expires_at`, `used_at`,
      and `nonce`. `DecisionService` loads the plan when `task.plan_id` is
      set (or uses `plan=`), binds step/arguments, and issues a nonce
      whenever binding is present. `ExecutionService` verifies binding
      before the tool runs (hard fail on missing/mismatched content; no
      soft skip), and sets `used_at` only after durable SUCCESS in the
      same unit of work — FAILURE/UNKNOWN do not consume the grant.
      **Found and fixed while syncing this session**: the replay-protection
      half of this was pure decoration on first landing.
      `AuthorizationAlreadyUsedError` was defined specifically for this,
      but never imported or raised anywhere — `_verify_authorization_
      binding()`'s own docstring listed "nonce has not been used (replay
      protection)" as check 6, but the code just unconditionally
      overwrote `used_at` on every call with no check against its prior
      value, and never inspected `auth.nonce` at all. Confirmed fixed:
      `auth.used_at is not None` now raises `AuthorizationAlreadyUsedError`
      before anything else runs. Plan-hash, step-hash, argument-hash, and
      expiry checks were correct from the start — only replay protection
      was affected.
- [x] **Tool argument schemas** — `ToolDeclaration.argument_schema` +
      `ToolSchema` validation in `ToolExecutor` (after capability gate,
      before the boundary). Elevated capabilities require a non-`None`
      schema at register time (`SchemaRequiredError`); `None` means open
      tool, `{}` means explicit empty schema.
      **Found and fixed while syncing this session**: `_validate_arguments()`
      called `schema.get_validated_arguments(request)` purely for its
      side effect of raising on failure and discarded the defaulted
      arguments it returned — a schema's `default=` for a missing
      optional argument was validated as present but never actually
      reached the handler. Fixed: the method now returns the request
      with defaults applied (via `dataclasses.replace`), and `execute()`
      uses that returned request rather than the original.
- [x] **Audit tamper-evidence (hash-chained events)** — implemented
      this session, not left for later as originally planned.
      `shea/audit/chain.py` (`hash_audit_event`, pure — SHA-256 of an
      event's own content plus `prev_hash`) and `shea/persistence/sqlite/
      audit_chain.py` (`verify_audit_chain`, walks the whole table by
      `sequence_number` and reports `content_altered` / `link_broken` /
      `sequence_gap` breaks). Migration adds `sequence_number`,
      `prev_hash`, `event_hash` columns to `audit_events`.
      **Found and fixed two bugs that made this universally non-functional
      on first landing** — confirmed by direct reproduction, not just
      code review:
      - The genesis event's hash was computed using `GENESIS_PREV_HASH`
        (64 zeros) as input, but `SqliteAuditSink.record()` then stored
        `prev_hash = None` in the DB instead — what was stored never
        matched what was hashed, so `verify_audit_chain()` reported
        `content_altered` + `link_broken` on the very first event ever
        recorded, in every database, unconditionally, with zero tampering
        involved.
      - `record()`'s "previous event" lookup was scoped to `(request_id,
        task_id)`, while `verify_audit_chain()` checks one *global* chain
        ordered by `sequence_number` — so the moment two tasks' events
        interleaved (the normal case for any system running more than one
        task), the chain falsely reported itself as broken.
        `tests/unit/test_audit_tamper_evidence.py` had a test
        (`test_different_scopes_have_separate_chains`) that explicitly
        asserted the buggy per-scope behavior as *correct*, and no test
        anywhere called `verify_audit_chain()` end-to-end to notice the
        two halves disagreed.
      Fixed: `record()` now always chains against the actual global tip
      (by `sequence_number`) and never trusts chain fields the caller may
      have already set on the `AuditEvent` it was given — the sink is now
      the only place `sequence_number`/`prev_hash`/`event_hash` are
      allowed to come from. Rewrote the whole test file: genesis case,
      multi-event continuity, interleaved-task case (proving the actual
      fix), tamper-via-raw-SQL detection (both the naive case and a
      "sophisticated tamperer who also patches their own row's hash"
      case, which correctly shifts the detected break from
      `content_altered` to `link_broken` on the *next* row), and
      deletion detection — all calling `verify_audit_chain()` directly
      rather than re-testing components in isolation.
      Known, stated-not-hidden limitation: a hash chain alone cannot
      detect truncation of the tail — deleting only the most recent N
      events leaves a chain that still verifies cleanly, since nothing
      recorded after the truncation point exists to notice the gap.
      Pinned as its own test
      (`test_deleting_only_the_most_recent_event_is_not_detectable`)
      rather than left as an unverified docstring claim. Defending
      against tail truncation needs an external anchor (e.g.
      periodically publishing the current tip hash somewhere else) —
      out of scope here.
- [x] **Multi-step state-machine foundation** — `step_verified` event
      (`VERIFYING` → `READY`) so intermediate steps re-enter Decision via
      `authorize_and_run`. `VerificationService.verify(more_steps=...)`
      selects final vs intermediate. `PlanRunner` walks steps with
      per-step binding. Full multi-step productization (durable step
      status, 2+ step e2e) is Phase 10.
- [x] Full suite verified end-to-end after all of the above, from a fresh
      sync against `origin/main`: 340/340 pytest, mypy --strict clean
      (104 source files), ruff clean. (2 ruff import-order/style issues
      and 1 mypy `unused type: ignore` turned up from the Phase 9 tools
      commit while verifying — auto-fixed / fixed, not left for later.)
- [x] Phase 8 documentation closed (README + this todo updated to
      complete). Audit hash-chaining is now actually implemented (see
      above) — no longer deferred to "Not yet built."

## Phase 9: First Real Tools (complete)

- [x] `security/runtime_checks.py` — `realpath_under_roots` (resolves
      symlinks, requires the real path stay under an allowed root —
      closes the TOCTOU gap `is_path_allowed`'s pure string-normalization
      can't), `resolve_and_check_url` (DNS-resolves the host and re-checks
      every returned address against network policy — closes the gap
      where `is_url_allowed` only ever inspected the hostname string)
- [x] Builtin `filesystem.read` (schema + handler + runtime path check)
- [x] Builtin `filesystem.write` (schema + handler + runtime path check;
      also re-checks the resolved *parent* directory before `mkdir`, so a
      symlinked parent can't be used to escape allowed roots via
      directory creation)
- [x] Real `Verifier` for `filesystem.write` (`filesystem_write_verifier`
      re-reads the file after a reported SUCCESS and compares actual
      on-disk content against what the write claimed — not default
      trust-success)
- [x] `register_builtin_tools(registry, *, filesystem_policy, ...)` via a
      small `ToolProvider` protocol (`load_tools`) — providers only
      attach declarations/handlers/verifiers, never execute or authorize
      anything themselves; `ToolExecutor`/`DecisionService` remain the
      only authority paths. Confirmed opt-in only: not wired into
      `tests/conftest.py`'s default `tool_registry` fixture, and
      `include_http_fetch` defaults to `False`
- [x] Unit tests: path allow/deny; symlink escape blocked after resolve
- [ ] E2E: plan → decide (bound) → execute write → verify → COMPLETED
      under a temp allowed root — not yet written; unit-level coverage
      exists but nothing exercises the full pipeline for these tools yet
- [x] `http.fetch` + DNS re-check tests
- [ ] README note for first real tools — not yet written; only a stale
      forward-looking "Next: Phase 9" pointer exists. Writing it now as
      part of this documentation pass.
- [x] **Fixed since flagged**: `http.fetch` DNS-rebinding TOCTOU gap.
      `resolve_and_check_url()` now returns a `ResolvedUrl` (host, port,
      `resolved_ip`) instead of just a validated URL string.
      `http_fetch.py` connects directly to `resolved_ip` — via a new
      `PinnedHTTPSConnection` for HTTPS (overrides `connect()` to dial the
      pinned IP, then wraps the socket in TLS with `server_hostname` set
      to the *original* hostname, so SNI/certificate validation still
      targets the real host) and a plain `HTTPConnection` constructed
      with the IP directly for HTTP — while sending an explicit `Host:`
      header with the original hostname either way. `http.client`'s own
      `_send_request` detects the explicit `Host` header and skips its
      normal auto-added one, so there's no duplicate/conflicting header.
      No re-resolution happens between the check and the connection in
      either path. Verified: `tests/unit/test_dns_pinning.py` (4 tests).
- [x] Full suite re-verified after syncing this round of commits
      (`http.fetch` pinning, PlanRunner step-state, the `shea.app`
      execution-plane subsystem documented in `todo_interaction.md`):
      354/354 pytest, mypy --strict clean (124 source files), ruff clean.

## Phase 10: Multi-Step Execution

- [x] Persist `PlanStep.state` through the runner — `PlanRunner._set_step_state()`
      mutates `step.state` and calls `self._plans.save(plan)` on every
      transition (RUNNING → COMPLETED/FAILED/SKIPPED), a real DB write
      each time, not just an in-memory loop variable. Already-`COMPLETED`
      steps are skipped on a fresh run (resume-friendly): `pending_indices`
      is computed from persisted state, not assumed to start at step 0.
- [x] PlanRunner product rules — stops on execution FAILURE/UNKNOWN, on
      `current.state` not reaching VERIFYING, on `SecurityService.
      scan_output()` flagging the tool's own output (injection
      quarantine — a step doesn't get to use output Security flagged as
      suspicious to justify continuing), and on verification failure.
      Each step gets its own `Decision` + `Authorization` with a fresh
      nonce — `explicit_user_ack` is a whole-run acknowledgement from the
      caller, but nonce reuse across steps never happens.
- [x] Unit tests: `tests/unit/test_plan_runner_multistep.py` (149 lines)
- [ ] E2E: ≥2 steps against Phase 9's real tools (write then read) — the
      multistep tests above exercise the state machine and step-skip
      logic; nothing yet drives two *real* `filesystem` tool calls
      through the full pipeline back to back
- [x] Distinct authorization per step (no nonce reuse across steps) — see
      above
- [x] Integration tests for `step_verified` → READY → authorize → next
      step — covered within `test_plan_runner_multistep.py`
- [ ] README multi-step section — not yet written

## Not yet built — explicitly flagged, not silently missing

- [ ] Memory & Context management
- [ ] Activation & Audio pipeline
- [ ] Interaction layer (CLI/GUI/API adapters producing a uniform `Request`
      — `PlanningService.create_and_plan()` currently builds `Request`
      itself with `source="text"` hardcoded)
- [ ] Extensions & Updates (plugin manifest, signing, sandboxed activation)
- [ ] Observability beyond the audit trail (structured logs, metrics,
      tracing, correlation IDs across a request)
- [x] Multi-step plan execution (product finish) — SM + `PlanRunner` +
      `step_verified` exist (Phase 8); durable `PlanStep` state and 2+
      step e2e with real tools are Phase 10
- [ ] Real OS-level sandboxing (namespaces/seccomp/cgroups or platform
      equivalent) — `SandboxedExecutionBoundary` enforces timeout and
      redaction only; a thread timeout does not terminate an underlying
      process, socket, or file handle a tool already opened
- [x] ~~`http.fetch` connection-pinning against DNS rebinding~~ — done
      (see the Phase 9 item above): `resolve_and_check_url()` now returns
      the resolved IP and `http_fetch.py` connects directly to it via
      `PinnedHTTPSConnection`/`HTTPConnection`, so the connection can't be
      redirected by a DNS change between the check and the connect.
- [x] ~~Tool schemas~~ — done in Phase 8 (`argument_schema`, elevated
      capability gate, executor validation)
- [x] ~~Authorization binding~~ — done in Phase 8 (hashes, expiry, nonce,
      used_at-after-SUCCESS)
- [ ] Dedicated secret store (OS keychain/Secret Service/Credential
      Manager) — `SecretRedactor` prevents secrets leaking into audit
      metadata, but there is no `SecretStore.get/set/delete/rotate`
      abstraction; secrets aren't actually managed, just redacted after
      the fact
- [x] ~~Audit tamper-evidence (hash-chained events)~~ — done this session
      (see the completed Phase 8 item above for the two bugs found and
      fixed along the way). `audit_events` is still insert-only by API
      (`AuditSink` exposes no update/delete), and now also hash-chained
      end to end via `verify_audit_chain()`. Known limitation, stated
      there and pinned as its own test: tail truncation (deleting only
      the most recent events) is not detectable by a hash chain alone.
- [x] ~~Cross-repository transactional atomicity~~ — done as of Phase 8's
      full sweep (see the completed Phase 8 item above): every repository
      write that pairs with an audit event now shares a `UnitOfWork` and
      commits or rolls back atomically. What's still open, not covered by
      that sweep: no single transaction spans an entire multi-service
      call chain (e.g. the full `DecisionService.evaluate_and_authorize()`
      call is three separate atomic transactions, not one — deliberately,
      per the scope note on that item).
- [ ] Concurrency model (task scheduler, per-tool concurrency limits,
      cancellation as a real execution mechanism, backpressure)
- [ ] Resource governance (CPU/RAM/disk/output-size/call-rate limits)
- [ ] Full testing pyramid — unit + property exist; no integration/E2E/
      adversarial security suite yet (SSRF via IPv6, Unicode path tricks,
      sandbox escape, replay attacks, etc.)
