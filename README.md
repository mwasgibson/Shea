# SHEA — execution pipeline and recovery

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
Phase 7 adds Provider Routing & Failover — a`ProviderRoutingService` that
structurally satisfies the `ModelProvider` port itself, so it's a drop-in
replacement anywhere Phase 5's code expects a single provider, with health-based
failover underneath. Phase 8 (complete) hardens what Phases 1–7 built and closes enforcement
gaps that were only conventions before: mandatory `SecurityService` on
execute, no silent unsafe execution, wired retry/idempotency, shared
`UnitOfWork` for critical write paths, content-bound authorization
(plan/step/argument hashes, expiry, one-shot nonce), a hash-chained
tamper-evident audit trail, tool argument schemas with elevated-capability
register gates, and a multi-step state-machine foundation (`step_verified`
→ READY). Phase 9 (complete) adds the first real tools that touch the
outside world under that hardening: `filesystem.read`/`write` and an
opt-in `http.fetch`, gated by runtime path/DNS re-checks that close what
pure policy string-matching can't. The current pipeline also includes
durable multi-step execution, supervised app receipts, bounded recovery,
and a public `InteractionService` request boundary.

Three of Phase 8/9's features shipped with real bugs that a full
verification pass — not just reading the code — caught and fixed: the
audit hash chain reported every database as tampered from its very first
event, authorization replay protection was pure decoration (the
exception it needed existed but was never raised), and tool schema
`default=` values were validated but silently never delivered to
handlers. Each is called out where it happened below rather than folded
quietly into "done."

## What's here

| Package | Responsibility |
| --- | --- |
| `shea.contracts` | Typed, framework-free data shapes: `Request`, `Intent`, `Task`, `Plan`, `PlanStep`, `Decision`, `RiskAssessment`, `Authorization`, `AuditEvent`, `ToolRequest`/`ToolResponse`, `ModelResponse`, `ToolExecutionRecord`, `VerificationRecord`, `RecoveryAttempt`. |
| `shea.ports` | Abstract interfaces (`TaskRepository`, `PlanRepository`, `IntentRepository`, `DecisionRepository`, `RiskAssessmentRepository`, `AuthorizationRepository`, `ToolExecutionRepository`, `VerificationRepository`, `RecoveryAttemptRepository`, `AuditSink`, `Clock`, `IdGenerator`, `ModelProvider`, `UnitOfWork`) — the hexagonal boundary. Nothing concrete lives here. |
| `shea.state_machine` | Authoritative transition table (Appendix A, plus `execution_unknown` and `step_verified`) and `next_state()` — the only function allowed to change task state. Illegal transitions raise `IllegalTransitionError`. |
| `shea.persistence.sqlite` | Concrete adapters implementing the ports above: connection handling, numbered SQL migrations through `0007`, repositories, and `audit_chain.py` (`verify_audit_chain` — walks `audit_events` and reports `content_altered`/`link_broken`/`sequence_gap` breaks). SQLite is the source of truth for task/plan state — not an in-memory cache with SQLite as backup. |
| `shea.config` | The six-layer configuration resolver (System → Machine → User → Profile → Project → Session), with `security_invariant_keys` that can only ever be set at the System layer regardless of what any other layer says. |
| `shea.core` | The `Orchestrator` — thin coordination of task lifecycle. Creates tasks, advances them via the state machine, attaches plans, persists, and audits every attempt (success *and* rejection). Each state write and its audit event commit or roll back together via a shared `UnitOfWork`, not as two independent commits. |
| `shea.model` | `ModelProvider` port (`generate()`/`health()`/`capabilities()`) and `ScriptedModelProvider` — a deterministic queued-response double. No real LLM API integration ships here; that's the Provider Routing phase's job. |
| `shea.understanding` | `DeterministicIntentMatcher` (pure) and `IntentParser` (pure) — research doc Section 6.2's hybrid: known commands matched deterministically, everything else falls back to the model, with `AmbiguousIntentError` for low-confidence output and `MalformedModelOutputError` for unparseable output. |
| `shea.planning` | `PlanTemplateRegistry` (pure), `validate_plan()` (pure — the "model suggested this" vs "Shea will act on this" boundary), `capabilities_for_plan()` (pure — bridges Planning to Decision), and `PlanningService` — the integration layer, sole caller of `start_planning`/`plan_ready`/`plan_failed`/`block`/`attach_plan`. |
| `shea.decision` | `PolicyEngine`, `RiskEngine`, confirmation-tier rules, and `DecisionService` — sole caller of `authorize_and_run`; issues content-bound `Authorization` records (plan/step/argument hashes, expiry, nonce) when a plan is present. |
| `shea.tools` | `ToolDeclaration` + `ToolRegistry` (capability profiles; optional `argument_schema`; elevated capabilities require a schema at register) and `ToolExecutor` (capability gate *before* handler lookup, schema validation when declared — defaults it computes are actually applied to the request via `dataclasses.replace`, not just checked and discarded — SUCCESS/FAILURE/UNKNOWN outcomes). `schema.py` is the pure validation engine; `provider.py`'s `ToolProvider` protocol + `load_tools()` let a registration bundle (see `shea.tools.builtin`) attach declarations/handlers/verifiers without ever executing or authorizing anything itself. |
| `shea.tools.builtin` | The first tools that touch the outside world: `filesystem.read`/`filesystem.write` and an opt-in `http.fetch`, registered via `register_builtin_tools()`. Not wired into any default fixture — a caller has to ask for these explicitly, and `http.fetch` needs `include_http_fetch=True` on top of that. |
| `shea.execution` | `ExecutionService` — looks up authorized capabilities from the persisted `Decision`, verifies authorization content-binding, requires `SecurityService`, enforces idempotency (SUCCESS/UNKNOWN suppress), runs one tool call through the supervised app boundary, persists `ToolExecutionRecord`, and advances by outcome. `PlanRunner` walks durable multi-step plans with per-step binding and resume-safe completion states. |
| `shea.verification` | `Verifier`/`VerifierRegistry` and `VerificationService` — sole caller of `verified` / `verification_failed` / `step_verified` (intermediate steps return to READY for the next authorization). Execution success does not force verification to agree. |
| `shea.recovery` | `Compensator` abstraction + `RecoveryService` — bounded Saga-style retry (`FAILED -> RECOVERING -> READY \| FAILED`), counted from persisted attempts, and `resolve_blocked()` for tasks Phase 3's `UNKNOWN` execution outcome routes to `BLOCKED`. `RetryController` is the single source of truth for the attempt budget and supplies the backoff delay persisted on each `RecoveryAttempt`. |
| `shea.security` | `NetworkPolicy`/`FilesystemPolicy` (SSRF and path-scope protection, pure) plus `runtime_checks.py`'s `realpath_under_roots`/`resolve_and_check_url` (the filesystem/DNS re-checks a pure policy can't do — symlink resolution, live DNS resolution), `SecretRedactor` (pattern-based, recursive), `PromptInjectionDetector` (heuristic), `SecurityGate` (pure pre-execution request scanner), `binding.py` (pure content-hashing for `Authorization` — plan/step/argument hashes, nonce generation), `SecurityService` — the only caller of `Orchestrator.advance(task_id, "security_halt")`; its violation path (violation audit -> task halt -> transition audit) commits or rolls back as one transaction. Also `SandboxedExecutionBoundary` — the real "Sandbox" pipeline stage (timeout + redaction). |
| `shea.provider` | `ProviderProfile`/`ProviderTrustLevel` (LOCAL/TRUSTED_REMOTE/UNTRUSTED), `HealthTracker` (sliding-window health), `FailureCategory`/`classify_exception()`, `ProviderRouter` (pure eligibility + ranking), `ProviderRoutingService` — structurally satisfies `ModelProvider` itself, so it's a drop-in for `IntentParser`/`PlanningService`. |
| `shea.audit` | `AuditRecorder` — centralizes event ID / timestamp generation so no call site can emit a malformed audit event; optionally redacts metadata via an injected `Redactor`. `chain.py`'s `hash_audit_event` is the pure SHA-256 hashing function backing the tamper-evident chain (see `shea.persistence.sqlite`'s `verify_audit_chain` for the verification side) — storage-neutral on purpose, so any `AuditSink` implementation could use it. |
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

Phase 7 sits underneath Phase 5's model boundary rather than above it —
`ProviderRoutingService` (`shea/provider/service.py`) satisfies the
`ModelProvider` port itself, so `IntentParser` and `PlanningService` can
receive one in place of a single `ScriptedModelProvider` without any
change to their own code; `test_service_is_a_drop_in_model_provider_for_
intent_parser` proves this by actually constructing an `IntentParser`
around one. Eligibility (`ProviderRouter.eligible()`) is a pure hard-filter
chain, not weighted scoring — `ProviderTrustLevel.UNTRUSTED` is excluded
unconditionally, the same non-negotiable shape as Phase 2's
`PolicyVerdict.DENIED` and Phase 6's SSRF blocking, and
`RoutingRequirements.require_local_only` means a local-only request can
never be satisfied by a remote provider, not even as a failover when no
local provider exists at all (research doc Section 8.11's exact scenario,
proven directly in `test_require_local_only_never_fails_over_to_remote`).

Phase 8 hardens what the prior phases built and enforces properties that
were previously only documented.

**Hardening:** `ExecutionService.security_service` is a required constructor
argument — there is no execute path without `SecurityService.enforce()`.
`ToolExecutor` requires a real `ExecutionBoundary` or explicit
`allow_unsafe_execution=True` (`UnsafeExecutionNotAllowedError`).
`RecoveryService` uses `RetryController` for attempt budget and backoff
(delay persisted on `RecoveryAttempt.delay_seconds`). `ExecutionService`
computes an idempotency key from (task, tool, action, arguments) and
suppresses re-invocation after a prior SUCCESS or UNKNOWN
(`DuplicateExecutionSuppressedError`); prior FAILURE is not suppressed.
A shared re-entrant `UnitOfWork` makes task/audit and other paired
repository+audit writes atomic. CI runs pytest, mypy, and ruff on every
push/PR to `main`.

**Enforcement:** Authorizations are content-bound (`plan_hash`, `step_hash`,
`arguments_hash`, `expires_at`, `nonce`, `used_at`). Decision binds when a
plan exists; execution verifies binding before the tool runs and sets
`used_at` only after durable SUCCESS. Tools may declare an
`argument_schema`; elevated capabilities cannot register without one.
The state machine adds `step_verified` (VERIFYING → READY) so intermediate
plan steps must pass `authorize_and_run` again; final steps still use
`verified` → COMPLETED. `PlanRunner` orchestrates the multi-step loop;
durable step status and full multi-step e2e are Phase 10.

**Tamper-evidence:** `audit_events` gets three more columns —
`sequence_number`, `prev_hash`, `event_hash` — forming a SHA-256 hash
chain across the *entire* table, not per task. `shea/audit/chain.py`
(`hash_audit_event`) is the pure hashing function; `shea/persistence/
sqlite/audit_chain.py` (`verify_audit_chain`) walks the table and reports
three kinds of break: `content_altered` (a row's stored content no longer
matches its stored hash), `link_broken` (a row's `prev_hash` doesn't
match its predecessor's actual `event_hash`), and `sequence_gap` (a
missing `sequence_number`). Stated plainly rather than oversold: this
detects alteration or deletion of anything *before* the current chain
tip, because doing so breaks a link something later depends on — it
cannot by itself detect truncating the tail (deleting only the most
recent events), since nothing recorded after the truncation point exists
to notice the gap. Defending against that needs an external anchor
(periodically publishing the tip hash somewhere else), which is out of
scope here.

**What broke on first landing, found by actually exercising the code
rather than reading it:** the audit chain reported every database as
tampered from its first event, always, with zero actual tampering — the
genesis event's hash was computed using a fixed `GENESIS_PREV_HASH`
marker but then stored a plain `None` for `prev_hash` instead, so what
was stored never matched what was hashed. A second bug compounded it:
`SqliteAuditSink.record()` looked up its "previous event" scoped to
`(request_id, task_id)`, while `verify_audit_chain()` checks one global
chain by `sequence_number` — so two tasks' events interleaving (normal
for any system running more than one task) broke it too. The existing
test suite had a test asserting the buggy per-scope behavior as
*correct*, and nothing called `verify_audit_chain()` end-to-end to notice
the two halves disagreed. Both are fixed: `record()` now always chains
against the true global tip and never trusts chain fields a caller might
already have set on the event it was given. Separately, authorization
replay protection turned out to be pure decoration —
`AuthorizationAlreadyUsedError` existed specifically for this but was
never imported or raised anywhere, despite `_verify_authorization_
binding()`'s own docstring listing it as a check it performed. And tool
schema `default=` values were computed by validation but the computed
result was discarded, so declared defaults never actually reached a
handler. All three are fixed and have tests proving the fix, not just
re-testing the pieces in isolation (`tests/unit/test_audit_tamper_
evidence.py` was rewritten entirely around this).

Phase 9 adds the first tools that touch the outside world under all of
that hardening: `filesystem.read`/`filesystem.write`
(`shea/tools/builtin/filesystem.py`) and an opt-in `http.fetch`
(`shea/tools/builtin/http_fetch.py`), registered via a small
`ToolProvider` protocol (`register_builtin_tools`) that only attaches
declarations/handlers/verifiers — `ToolExecutor`/`DecisionService` remain
the only authority paths, matching the same separation Phase 7 kept for
providers. `shea/security/runtime_checks.py` closes gaps pure policy
string-matching can't: `realpath_under_roots` resolves symlinks and
requires the *real* path stay under an allowed root (a symlink inside an
allowed root pointing outside is rejected, and `filesystem.write` also
re-checks the resolved parent directory before `mkdir` so a symlinked
parent can't be used to escape via directory creation), and
`resolve_and_check_url` DNS-resolves the host and re-checks every
returned address against network policy. `filesystem_write_verifier` is
a real verifier — it re-reads the file after a reported SUCCESS and
compares actual on-disk content against what the write claimed, not
default trust-success. Confirmed opt-in only: not wired into `tests/
conftest.py`'s default `tool_registry` fixture, and `include_http_fetch`
defaults to `False`.

`http.fetch` pins the checked address for the actual connection while
preserving the original host for HTTP and TLS identity. Filesystem tools
perform symlink-aware real-path checks and independent post-write
verification; descriptor-level race elimination remains an operating-system
hardening boundary rather than a claim made by the pure policy layer.

## Tool plane vs app plane (execution boundary)

- **Tool plane** (`shea.tools`, builtin `filesystem.*` / `http.fetch`): product
  tools used by plans and `ToolExecutor`. This is the supported agent path today.
- **App plane** (`shea.app`, `ExecutionSupervisor`, receipts/attempts): wraps
  every `ExecutionService.execute` via `ToolExecutorAdapter`, and also hosts
  native adapters (`filesystem.local`, `process.local`) for EP-native contracts.

**Rule:** do not add the same capability in both places. New side-effect work
either extends a tool *or* an EP adapter, not both. Native EP filesystem/process
are not on the default agent adapter list until plans route to them explicitly
(strategy B migration).

## What's deliberately NOT here yet

- Any real model/LLM API integration (`ScriptedModelProvider` is a
  deterministic double, not a production adapter)
- Real OS-level sandboxing: `SandboxedExecutionBoundary` enforces timeout
  and redaction only — a thread timeout does not terminate an underlying
  process, socket, or file handle a tool already opened. Narrower than
  it used to be: Phase 9's `runtime_checks.py` closed the blanket "DNS
  rebinding and symlink escapes aren't checked at all" gap this used to
  describe — `realpath_under_roots` does real symlink resolution against
  the actual filesystem, and `resolve_and_check_url` does real DNS
  resolution and re-checks every returned address. What's left is
  narrower: descriptor-level race elimination remains an operating-system
  hardening boundary beyond the pure policy checks.
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
- Any real model/LLM API adapter — `ScriptedModelProvider` remains the
  only concrete `ModelProvider` implementation; `ProviderRoutingService`
  routes between whatever is registered, but nothing here talks to an
  actual API yet
- Same-provider retry with backoff/jitter, and gradual traffic recovery
  percentages (research doc Sections 8.14/8.17) — every provider failure
  fails over to the next eligible provider immediately; `FailureCategory`/
  `RETRYABLE_CATEGORIES` exist for a future same-provider-retry loop to
  consult, but that loop isn't built
- Context-window reduction/reassembly on failover (Section 8.12) —
  `ProviderRouter` filters out providers whose context limit is too
  small rather than trying to fit the request into a smaller one
- Audio/voice pipeline

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

## Optional model planning

If no deterministic template matches, Planning can call a model provider.

```bash
export SHEA_MODEL_API_KEY=sk-...
# optional:
export SHEA_MODEL_BASE_URL=https://api.openai.com/v1
export SHEA_MODEL_NAME=gpt-4o-mini

python -m shea run "organize my notes somehow"
```

---

### Behavior

| Case | Result |
| ------ | -------- |
| Template match (write a note) | No model call |
| No template + no key | Plan fails (existing) |
| No template + key | `generate` → JSON steps → validate tools → READY |
| Bad JSON / HTTP error | `MalformedModelOutputError` / `ModelUnavailableError` → plan_failed |

Model still **does not** authorize or execute — only proposes steps.

---

### Verify

```bash
pytest tests/unit/test_openai_compatible_provider.py -q
# with key:
export SHEA_MODEL_API_KEY=...
python -m shea run "something with no demo template"
```

## Layout

```text
src/shea/
├── contracts/          # pure data shapes
├── ports/              # hexagonal interfaces (incl. UnitOfWork)
├── state_machine/      # TRANSITIONS + next_state()
├── persistence/sqlite/ # migrations + repositories + audit_chain verification
├── config/             # six-layer resolver
├── core/               # Orchestrator
├── model/              # ModelProvider + ScriptedModelProvider
├── understanding/      # DeterministicIntentMatcher + IntentParser
├── planning/           # templates, validate_plan, PlanningService
├── decision/           # Policy, Risk, DecisionService
├── tools/              # Registry, Executor, schemas, boundary, provider protocol
│   └── builtin/        # filesystem.read/write, http.fetch
├── execution/          # ExecutionService, PlanRunner
├── verification/       # Verifier registry + VerificationService
├── recovery/           # Retry, Idempotency, RecoveryService
├── security/           # Gate, policies, runtime_checks, binding, SecurityService
├── provider/           # Routing + failover
├── audit/              # AuditRecorder + chain hashing
├── app/                # execution plane: supervisor, adapters, evidence, reconcile
├── bootstrap.py        # composition root (wires agent + app plane)
├── __main__.py         # thin CLI
└── adapters/            # concrete Clock / IdGenerator

tests/
├── unit/
└── property/
```

The V1 composition root registers the built-in filesystem tools and wires
`PlanningService` with deterministic intent matching and plan templates.
Model-provider routing remains opt-in: pass a configured `ModelProvider` to
`build_runtime()` when model fallback is available. The default execution
boundary is intentionally unsafe for local development; production callers
must provide a real boundary and configure `SHEA_FILESYSTEM_ROOTS` or pass
`filesystem_roots` explicitly.
