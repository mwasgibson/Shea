# SHEA — Lessons

## Process

- Verification that only reads code misses bugs that show up when exercising
  audit chain, auth replay, and schema defaults end-to-end.
- Optional dependencies (Playwright) must be gated by **package + OS**, not
  assumed installable on every developer machine.
- Shared runtime objects (`ToolExecutor`, `ExecutionSupervisor`) are not a
  security boundary unless permits / entrypoints seal them.

## Product

- Deterministic templates give a working CLI without paid APIs.
- Strategy C (tools vs EP adapters) must stay explicit in docs or callers
  double-implement the same capability.

## EP

- Receipt-before-invoke and adapter try/except finalize prevent stuck
  ATTEMPTING/INVOKED rows.
- Empty process/application allowlists must fail closed at scope and adapter.
