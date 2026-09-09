# SHEA — Todo

## Phase 1: Core Foundation

- [x] Directory scaffold (`src/shea/...`, `tests/...`)
- [x] Contracts: enums + dataclasses (Request, Intent, Task, Plan, Decision, Authorization, AuditEvent, …)
- [x] Ports: TaskRepository, PlanRepository, AuditSink, Clock, IdGenerator
- [x] State machine: transition table + next_state() / IllegalTransitionError
- [x] SQLite persistence: migrations + repositories
- [x] Config: six-layer resolver with security-invariant keys
- [x] Core: Orchestrator (create_task / advance / get_task), audits every attempt
- [x] AuditRecorder
- [x] Unit + property tests; mypy --strict; ruff clean

## Phase 2: Decision, Policy & Risk Engine

- [x] PolicyEngine, RiskEngine, confirmation tiers
- [x] DecisionService — sole caller of authorize_and_run
- [x] PolicyDeniedError (non-overridable) / AuthorizationRequiredError
- [x] Migration 0002 + repositories
- [x] Tests + property tests

## Phase 3: Tool Registry + Executor

- [x] ToolRequest/ToolResponse; Decision.capabilities
- [x] execution_unknown → BLOCKED
- [x] ToolRegistry + ToolExecutor (capability gate before handler)
- [x] ExecutionService (capabilities from persisted Decision)
- [x] Migration 0003; tests + property tests

## Phase 4: Verification & Recovery

- [x] ToolExecutionRecord, VerificationRecord, RecoveryAttempt
- [x] VerificationService (verified / verification_failed)
- [x] RecoveryService (bounded retry; resolve_blocked)
- [x] Honest default_verifier / default_compensator
- [x] Migration 0004; tests + property tests

## Phase 5: Intent Understanding & Planning

- [x] ModelProvider + ScriptedModelProvider
- [x] DeterministicIntentMatcher + IntentParser
- [x] PlanTemplateRegistry, validate_plan, capabilities_for_plan, PlanningService
- [x] Migration 0005 (intents)
- [x] Capstone e2e pipeline test

## Phase 6: Security & Trust

- [x] NetworkPolicy, FilesystemPolicy, SecretRedactor, PromptInjectionDetector
- [x] SecurityGate + SecurityService (security_halt)
- [x] ExecutionBoundary + SandboxedExecutionBoundary / UnsafeExecutionBoundary
- [x] Tests + property tests (SSRF / path scope)

## Phase 7: Provider Routing & Failover

- [x] ProviderTrustLevel, HealthTracker, FailureCategory, ProviderRouter
- [x] ProviderRoutingService as ModelProvider drop-in
- [x] require_local_only; UNTRUSTED never eligible
- [x] Tests + property tests

## Phase 8: Core Hardening & Enforcement (complete)

### Hardening

- [x] UnsafeExecutionNotAllowedError — no silent unsafe ToolExecutor default
- [x] ExecutionService.security_service required
- [x] RetryController wired into RecoveryService (budget + delay_seconds)
- [x] IdempotencyKeyGenerator wired into ExecutionService (SUCCESS/UNKNOWN suppress)
- [x] UnitOfWork — Orchestrator / SecurityService atomic paths
- [x] Full repository UoW sweep + service save/audit pairing
- [x] CI: pytest + mypy + ruff on push/PR

### Enforcement

- [x] Authorization content binding (plan_hash, step_hash, arguments_hash, expires_at, nonce, used_at)
- [x] DecisionService loads plan when task.plan_id set; binds step/args; nonce when bound
- [x] ExecutionService hard binding failures; used_at only after durable SUCCESS
- [x] Tool argument schemas; elevated capabilities require schema at register (SchemaRequiredError)
- [x] step_verified (VERIFYING → READY); VerificationService.verify(more_steps=…)
- [x] PlanRunner skeleton (product multi-step = Phase 10)
- [x] README + todo closed as Phase 8 complete

## Phase 9: First Real Tools

- [ ] security/runtime_checks.py — realpath_under_roots, resolve_and_check_url
- [ ] Builtin filesystem.read (schema + handler + runtime path check)
- [ ] Builtin filesystem.write (schema + handler + runtime path check)
- [ ] Real Verifier for filesystem.write (not default trust-success)
- [ ] register_builtin_tools(registry, *, filesystem_policy, …)
- [ ] Unit tests: path allow/deny; symlink escape blocked after resolve
- [ ] E2E: plan → decide (bound) → execute write → verify → COMPLETED under temp allowed root
- [ ] Optional: http.fetch + DNS re-check tests
- [ ] README note; pytest / mypy / ruff green

## Phase 10: Multi-Step Execution

- [ ] Persist PlanStep.state through the runner
- [ ] PlanRunner product rules (stop on failure/injection; ack policy after first step)
- [ ] E2E: ≥2 steps (prefer write then read from Phase 9 tools)
- [ ] Distinct authorization per step (no nonce reuse across steps)
- [ ] Integration tests for step_verified → READY → authorize → next step
- [ ] README multi-step section; pytest / mypy / ruff green

## Not yet built — explicitly flagged, not silently missing

- [ ] Memory & Context management
- [ ] Activation & Audio pipeline
- [ ] Interaction layer (CLI/GUI/API adapters producing a uniform Request)
- [ ] Extensions & Updates (plugin manifest, signing, sandboxed activation)
- [ ] Observability beyond the audit trail (structured logs, metrics, tracing)
- [ ] Multi-step plan execution (product finish) — SM + PlanRunner + step_verified exist (Phase 8); durable PlanStep state and 2+ step e2e are Phase 10
- [ ] Real OS-level sandboxing (namespaces/seccomp/cgroups)
- [x] ~~Tool schemas~~ — done in Phase 8
- [x] ~~Authorization binding~~ — done in Phase 8
- [ ] Dedicated secret store (OS keychain / Secret Service)
- [ ] Audit tamper-evidence (hash-chained events)
- [x] ~~Cross-repository transactional atomicity~~ — done in Phase 8 UoW sweep (multi-service single transaction still out of scope)
- [ ] Concurrency model (scheduler, per-tool limits, cancellation, backpressure)
- [ ] Resource governance (CPU/RAM/disk/output-size/call-rate limits)
- [ ] Full testing pyramid — adversarial security suite (IPv6 SSRF, Unicode paths, sandbox escape, replay, …)
