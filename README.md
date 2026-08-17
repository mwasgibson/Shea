# SHEA — Phase 1–3: Core Foundation, Decision/Policy/Risk, Tool Execution

Phase 1 is the foundation layer (state machine, persistence, contracts,
config). Phase 2 adds the Decision/Policy/Risk engine — the only
subsystem allowed to move a task into `RUNNING`. Phase 3 adds the Tool
Registry and Executor — the first subsystem that does something once a
task is `RUNNING`, and the first to give `capabilities` a real backing
instead of being opaque strings passed around by hand.

Still no model/LLM integration and no Intent/Planning subsystem — those
plug into the ports and the `DecisionService`/`ExecutionService` call
sites in later phases without requiring changes to this layer.

## What's here

| Package                   | Responsibility                                                                                                                                                                                                                                                                  |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `shea.contracts`          | Typed, framework-free data shapes: `Request`, `Intent`, `Task`, `Plan`, `PlanStep`, `Decision`, `RiskAssessment`, `Authorization`, `AuditEvent`. Only `Task` has real behavior in Phase 1 (via the state machine); the rest are agreed-upon shape for later phases to populate. |
| `shea.ports`              | Abstract interfaces (`TaskRepository`, `PlanRepository`, `AuditSink`, `Clock`, `IdGenerator`) — the hexagonal boundary. Nothing concrete lives here.                                                                                                                            |
| `shea.state_machine`      | The authoritative task transition table (Appendix A) and `next_state()`, the only function allowed to change a task's state. Illegal transitions raise `IllegalTransitionError` rather than silently succeeding.                                                                |
| `shea.persistence.sqlite` | Concrete adapters implementing the ports above: connection handling, numbered SQL migrations, repositories. SQLite is the source of truth for task/plan state — not an in-memory cache with SQLite as backup.                                                                   |
| `shea.config`             | The six-layer configuration resolver (System → Machine → User → Profile → Project → Session), with `security_invariant_keys` that can only ever be set at the System layer regardless of what any other layer says.                                                             |
| `shea.core`               | The `Orchestrator` — thin coordination of task lifecycle. Creates tasks, advances them via the state machine, persists, and audits every attempt (success _and_ rejection).                                                                                                     |
| `shea.decision`           | `PolicyEngine` (deterministic capability rules), `RiskEngine` (factor-based classification + explanation), confirmation-tier rules, and `DecisionService` — the only subsystem allowed to call `Orchestrator.advance(task_id, "authorize_and_run")`.                            |
| `shea.tools`              | `ToolDeclaration` + `ToolRegistry` (capability profiles, no authorization logic) and `ToolExecutor` (the capability gate — checks required vs. authorized capabilities _before_ the handler is ever looked up, and distinguishes SUCCESS/FAILURE/UNKNOWN outcomes).             |
| `shea.execution`          | `ExecutionService` — looks up a task's authorized capabilities from the persisted `Decision` (never from a caller-supplied value), runs one tool call through `ToolExecutor`, and advances the orchestrator based on the outcome.                                               |
| `shea.audit`              | `AuditRecorder` — centralizes event ID / timestamp generation so no call site can emit a malformed audit event.                                                                                                                                                                 |
| `shea.adapters`           | Production implementations of `Clock` and `IdGenerator` (real time, real UUIDs). Tests use fakes instead — see `tests/conftest.py`.                                                                                                                                             |

## Why this order

The state machine (`shea/state_machine/transitions.py`) is the most
important file in Phase 1. It makes `IDLE → EXECUTING` without an
authorization step _structurally_ impossible — there's no event in the
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
capabilities against that set _before_ even looking up the handler
function. There is no code path in `ToolExecutor.execute()` that reaches
a handler once the capability check fails. Execution outcomes are kept
to exactly three, never conflated: `SUCCESS`, `FAILURE`, and `UNKNOWN`
(the last for cases like a dropped connection after a side effect may
have occurred — routed to `BLOCKED`, not `FAILED`, since it isn't safe to
assume either way).

## What's deliberately NOT here yet

- Any model/LLM integration
- Intent Understanding & Planning (the Decision engine assumes a task is
  already `READY`, i.e. planning already happened)
- Sandboxing, resource limits, filesystem/network scoping (Security &
  Trust phase — `ExecutionService` is the orchestration layer around that
  boundary, not the boundary itself)
- Multi-step plan execution (`ExecutionService` runs one tool call per
  invocation; looping over `PlanStep`s is Planning/Orchestration's job)
- Audio/voice pipeline
- Provider routing

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

```bash
src/shea/
├── contracts/       # pure data
├── ports/            # abstract interfaces (hexagonal boundary)
├── state_machine/    # transition table + validator
├── persistence/sqlite/
│   ├── migrations/   # numbered .sql files
│   └── *.py          # repository adapters
├── config/           # layered resolver + security invariants
├── core/             # Orchestrator
├── audit/            # AuditRecorder
└── adapters/          # concrete Clock / IdGenerator

tests/
├── unit/
└── property/          # Hypothesis-based invariant tests
```
