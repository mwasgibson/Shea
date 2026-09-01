# SHEA — Phase 1–6: Foundation through Security & Trust

Phase 1 is the foundation layer (state machine, persistence, contracts,
config). Phase 2 adds the Decision/Policy/Risk engine — the only
subsystem allowed to move a task into `RUNNING`. Phase 3 adds the Tool
Registry and Executor — the first subsystem that does something once a
task is `RUNNING`. Phase 4 closes the verification/recovery loop the
state machine always had a shape for. Phase 5 adds Intent Understanding
& Planning — the first place a model enters the system. Phase 6 adds
Security & Trust: SSRF/path-scope protection, secret redaction, prompt
injection detection, and a real sandboxing boundary around tool
execution — the constraint layer around the model boundary Phase 5 built.

## What's here

| Package | Responsibility |
| --- | --- |
| `shea.contracts` | Typed, framework-free data shapes: `Request`, `Intent`, `Task`, `Plan`, `PlanStep`, `Decision`, `RiskAssessment`, `Authorization`, `AuditEvent`, `ToolRequest`/`ToolResponse`, `ModelResponse`, `ToolExecutionRecord`, `VerificationRecord`, `RecoveryAttempt`. |
| `shea.ports` | Abstract interfaces (`TaskRepository`, `PlanRepository`, `IntentRepository`, `DecisionRepository`, `RiskAssessmentRepository`, `AuthorizationRepository`, `ToolExecutionRepository`, `VerificationRepository`, `RecoveryAttemptRepository`, `AuditSink`, `Clock`, `IdGenerator`, `ModelProvider`) — the hexagonal boundary. Nothing concrete lives here. |
| `shea.state_machine` | The authoritative task transition table (Appendix A, extended with `execution_unknown`) and `next_state()`, the only function allowed to change a task's state. Illegal transitions raise `IllegalTransitionError` rather than silently succeeding. |
| `shea.persistence.sqlite` | Concrete adapters implementing the ports above: connection handling, numbered SQL migrations (0001–0005), repositories. SQLite is the source of truth for task/plan state — not an in-memory cache with SQLite as backup. |
| `shea.config` | The six-layer configuration resolver (System → Machine → User → Profile → Project → Session), with `security_invariant_keys` that can only ever be set at the System layer regardless of what any other layer says. |
| `shea.core` | The `Orchestrator` — thin coordination of task lifecycle. Creates tasks, advances them via the state machine, attaches plans, persists, and audits every attempt (success *and* rejection). |
| `shea.model` | `ModelProvider` port (`generate()`/`health()`/`capabilities()`) and `ScriptedModelProvider` — a deterministic queued-response double. No real LLM API integration ships here; that's the Provider Routing phase's job. |
| `shea.understanding` | `DeterministicIntentMatcher` (pure) and `IntentParser` (pure) — research doc Section 6.2's hybrid: known commands matched deterministically, everything else falls back to the model, with `AmbiguousIntentError` for low-confidence output and `MalformedModelOutputError` for unparseable output. |
| `shea.planning` | `PlanTemplateRegistry` (pure), `validate_plan()` (pure — the "model suggested this" vs "Shea will act on this" boundary), `capabilities_for_plan()` (pure — bridges Planning to Decision), and `PlanningService` — the integration layer, sole caller of `start_planning`/`plan_ready`/`plan_failed`/`block`/`attach_plan`. |
| `shea.decision` | `PolicyEngine` (deterministic capability rules), `RiskEngine` (factor-based classification + explanation), confirmation-tier rules, and `DecisionService` — the only subsystem allowed to call `Orchestrator.advance(task_id, "authorize_and_run")`. |
| `shea.tools` | `ToolDeclaration` + `ToolRegistry` (capability profiles, no authorization logic) and `ToolExecutor` (the capability gate — checks required vs. authorized capabilities *before* the handler is ever looked up, and distinguishes SUCCESS/FAILURE/UNKNOWN outcomes). |
| `shea.execution` | `ExecutionService` — looks up a task's authorized capabilities from the persisted `Decision` (never from a caller-supplied value), runs one tool call through `ToolExecutor`, persists a `ToolExecutionRecord`, and advances the orchestrator based on the outcome. |
| `shea.verification` | `Verifier`/`VerifierRegistry` (per-tool, mirrors `ToolRegistry`) and `VerificationService` — the only caller of `Orchestrator.advance(task_id, "verified" \| "verification_failed")`. Independently decides whether a tool's claimed success actually happened; a tool reporting success does not force verification to agree. |
| `shea.recovery` | `Compensator` abstraction + `RecoveryService` — bounded Saga-style retry (`FAILED -> RECOVERING -> READY \| FAILED`), counted from persisted attempts, and `resolve_blocked()` for tasks Phase 3's `UNKNOWN` execution outcome routes to `BLOCKED`. |
| `shea.security` | `NetworkPolicy`/`FilesystemPolicy` (SSRF and path-scope protection, pure), `SecretRedactor` (pattern-based, recursive), `PromptInjectionDetector` (heuristic), `SecurityGate` (pure pre-execution request scanner), `SecurityService` — the only caller of `Orchestrator.advance(task_id, "security_halt")`. Also `SandboxedExecutionBoundary` — the real "Sandbox" pipeline stage (timeout + redaction). |
| `shea.audit` | `AuditRecorder` — centralizes event ID / timestamp generation so no call site can emit a malformed audit event; optionally redacts metadata via an injected `Redactor`. |
| `shea.adapters` | Production implementations of `Clock` and `IdGenerator` (real time, real UUIDs). Tests use fakes instead — see `tests/conftest.py`. |

## Why this order

The state machine (`shea/state_machine/transitions.py`) is the most
important file in Phase 1. It makes `IDLE → EXECUTING` without an
authorization step *structurally* impossible — there's no event in the
transition table that does it — rather than merely a rule enforced
elsewhere.

Phase 2's `DecisionService` (`shea/decision/service.py`) is what actually
exercises that boundary: it's the only code that calls
`Orchestrator.advance(task_id, "authorize_and_run")`, and it enforces two
distinct tiers on the way there —

- **`PolicyVerdict.DENIED`** — non-negotiable. No `explicit_user_ack`
  argument or override flag changes the outcome. Raises `PolicyDeniedError`.
- **Risk-based authorization requirement** — overridable. `WARNING != DENIAL`
  (Appendix B): a HIGH/CRITICAL/UNKNOWN-risk action blocks with
  `AuthorizationRequiredError` until an explicit, audited acknowledgement
  is supplied, at which point it proceeds.

Both paths, and every risk assessment, are persisted and audited before
the orchestrator is ever touched.

Phase 3's `ExecutionService` (`shea/execution/service.py`) is the next
link: it looks up a task's authorized capabilities from the persisted
`Decision` — not from whatever an execution caller happens to claim — and
`ToolExecutor` (`shea/tools/executor.py`) checks a tool's declared
capabilities against that set *before* even looking up the handler
function. There is no code path in `ToolExecutor.execute()` that reaches
a handler once the capability check fails. Execution outcomes are kept
to exactly three, never conflated: `SUCCESS`, `FAILURE`, and `UNKNOWN`
(the last for cases like a dropped connection after a side effect may
have occurred — routed to `BLOCKED`, not `FAILED`, since it isn't safe to
assume either way).

Phase 4 closes the loop the state machine always had a shape for but no
subsystem behind: `VerificationService` (`shea/verification/service.py`)
reads the `ToolExecutionRecord` `ExecutionService` persisted and runs a
per-tool `Verifier` against it — deliberately NOT trusting the tool's own
`success` flag by default reasoning alone, so a registered Verifier can
disagree and fail verification even when the tool claimed success
(`EXECUTION SUCCESS != VERIFIED SUCCESS`, Appendix B). `RecoveryService`
(`shea/recovery/service.py`) implements the bounded Saga-style retry loop:
`default_compensator` always reports `restored=False` — there is no
optimistic default — so Constraint 5 ("Rollback must never be claimed
successful without verification") holds even when nobody has configured
a real compensating action yet. Retry attempts are counted from
persisted `RecoveryAttempt` rows, not an in-memory counter, so the limit
survives a process restart.

Phase 5 is the first place a model enters the system, and it enters
exactly the way research doc Section 2's Core Architectural Principle 1
describes: "LLMs interpret, they do not receive unrestricted authority."
`IntentParser` (`shea/understanding/parser.py`) tries a deterministic
match first; the model is only ever asked to produce *structured* output,
which is validated exactly as strictly as any other untrusted input
before it becomes an `IntentDraft` — a missing field, a confidence value
outside `[0, 1]`, or non-JSON `structured_data` all raise
`MalformedModelOutputError` rather than being coerced into something
usable. `validate_plan()` (`shea/planning/validator.py`) is the concrete
form of Section 6.5's "A plan should not execute simply because an LLM
produced it": every step's tool must actually be registered before the
plan is accepted, and this check is structural only — it says nothing
about whether the plan is *authorized*, which remains `DecisionService`'s
job downstream. `capabilities_for_plan()` is what finally closes the loop
opened all the way back in Phase 2: a raw text request can now flow
through Planning → Decision → Execution → Verification and reach
`COMPLETED` without anything hand-driving the state machine — see
`tests/unit/test_end_to_end_pipeline.py`.

Phase 6 constrains what Phase 5's model can actually make happen.
`SecurityGate` (`shea/security/gate.py`) scans every string-valued tool
argument for URL/path shape and checks it against `NetworkPolicy`/
`FilesystemPolicy` — SSRF targets (loopback, private networks, the cloud
metadata endpoint) and out-of-scope filesystem paths are blocked before a
handler is ever reached. `SecurityService.enforce()` is called
structurally from inside `ExecutionService.execute()` (not left as a
separate step a caller might forget), and a violation drives the task to
`SECURITY_HALT` — the terminal state Phase 3's transition table always
had but nothing used until now. Sandboxing itself is a real
`ExecutionBoundary`: `ToolExecutor` has exactly one call site that can
ever invoke a handler, so a configured boundary (or the default
`UnsafeExecutionBoundary`) can't be silently bypassed by a leftover code
path — see the Phase 6 review in `tasks/todo.md` for the concrete bug
this design replaced. `SandboxedExecutionBoundary` maps a timeout to
`UnknownOutcomeError`, not `FAILURE` — Section 12.13's "the connection
died, the side effect might have happened" principle applied to the
timeout case specifically — and redacts secrets from tool responses via
an injected `SecretRedactor`, the same redactor `AuditRecorder` can
optionally use for its own metadata.

## What's deliberately NOT here yet

- Any real model/LLM API integration (`ScriptedModelProvider` is a
  deterministic double, not a production adapter)
- Real OS-level sandboxing: `SandboxedExecutionBoundary` enforces timeout
  and redaction; `NetworkPolicy`/`FilesystemPolicy` check literal request
  content, not runtime behavior — DNS rebinding and symlink-based path
  escapes are documented, explicit gaps requiring real network
  resolution / OS-level realpath checks at actual access time
- Multi-step plan execution (`ExecutionService` runs one tool call per
  invocation; looping over a `Plan`'s steps is Orchestration's job)
- Real per-tool Verifiers and Compensators — Phase 4 provides the
  abstractions and honest fallbacks; registering an actual independent
  check for a given tool is that tool's job when it's built
- Real NLU — `DeterministicIntentMatcher` is ordered substring matching,
  not slot-filling or entity extraction
- A real prompt-injection classifier — `PromptInjectionDetector` is a
  heuristic phrase list; a determined attacker can phrase around it
- Consequential action on a detected injection — `SecurityService.
  scan_output()` audits, it doesn't halt; untrusted content is data, not
  authority (Section 11.6), and making detections consequential is a
  policy decision this phase deliberately left unmade
- Audio/voice pipeline
- Provider routing / failover

These are later phases per the technical doc's Development Plan (Section 20).

## Running it

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest                  # unit + property tests
mypy                    # strict type checking
ruff check .            # lint
```

## Layout

```text
src/shea/
├── contracts/          # pure data: enums.py, models.py
├── ports/               # abstract interfaces (hexagonal boundary)
│   ├── clock.py
│   ├── execution_boundary.py
│   ├── id_generator.py
│   ├── model_provider.py
│   ├── redactor.py
│   └── repositories.py
├── state_machine/       # transition table + validator
├── persistence/sqlite/
│   ├── migrations/      # 0001_initial ... 0005_intents
│   └── *.py             # one repository adapter per entity
├── config/               # layered resolver + security invariants
├── core/                 # Orchestrator
├── model/                 # ModelProvider port + ScriptedModelProvider
├── understanding/          # DeterministicIntentMatcher, IntentParser
├── planning/               # PlanTemplateRegistry, validator, capabilities, PlanningService
├── decision/               # PolicyEngine, RiskEngine, confirmation rules, DecisionService
├── tools/                   # ToolRegistry, ToolExecutor, UnsafeExecutionBoundary
├── execution/                # ExecutionService
├── verification/              # Verifier, VerifierRegistry, VerificationService
├── recovery/                   # Checkpoint, Classifier, Compensator, Idempotency, Planner, Retry, RecoveryService, Startup
├── security/                    # NetworkPolicy, FilesystemPolicy, SecretRedactor,
│                                 # PromptInjectionDetector, SecurityGate,
│                                 # SandboxedExecutionBoundary, SecurityService
├── audit/                        # AuditRecorder
└── adapters/                      # concrete Clock / IdGenerator

tests/
├── unit/                 # one file per subsystem + capstone end-to-end test
└── property/              # Hypothesis-based invariant tests
```
