from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from shea.contracts.models import Plan


@dataclass(frozen=True)
class OperationNode:
    step_id: str
    tool: str
    action: str
    arguments: dict[str, Any]
    depends_on: tuple[str, ...] = ()
    compensation_tool: str | None = None
    compensation_arguments: dict[str, Any] = field(default_factory=dict[str, Any])
    idempotent: bool = False
    verification: str | None = None  # verifier key
    failure_policy: str = "stop"  # stop | continue | compensate


@dataclass(frozen=True)
class OperationGraph:
    plan_id: str
    task_id: str
    nodes: tuple[OperationNode, ...]

    @classmethod
    def from_plan(cls, plan: Plan) -> OperationGraph:
        nodes: list[OperationNode] = []
        for step in plan.steps:
            raw_args = step.arguments or {}
            meta_raw = raw_args.get("_graph")
            meta: dict[str, Any] = (
                cast(dict[str, Any], meta_raw) if isinstance(meta_raw, dict) else {}
            )
            nodes.append(
                OperationNode(
                    step_id=step.id,
                    tool=step.tool,
                    action=str(step.arguments.get("action") or getattr(step, "action", "run") or "run"),
                    arguments={k: v for k, v in step.arguments.items() if k != "_graph"},
                    depends_on=tuple(step.depends_on or ()),
                    compensation_tool=meta.get("compensation_tool"),
                    compensation_arguments=dict(meta.get("compensation_arguments") or {}),
                    idempotent=bool(meta.get("idempotent", False)),
                    verification=meta.get("verification"),
                    failure_policy=str(meta.get("failure_policy", "stop")),
                )
            )
        graph = cls(plan_id=plan.id, task_id=plan.task_id, nodes=tuple(nodes))
        graph.validate()
        return graph

    def validate(self) -> None:
        ids = {n.step_id for n in self.nodes}
        for n in self.nodes:
            for d in n.depends_on:
                if d not in ids:
                    raise ValueError(f"node {n.step_id} depends on missing {d}")
        # cycle check via topo
        self.topological_order()

    def topological_order(self) -> list[OperationNode]:
        by_id = {n.step_id: n for n in self.nodes}
        deps = {n.step_id: set(n.depends_on) for n in self.nodes}
        ordered: list[OperationNode] = []
        while deps:
            ready = [sid for sid, d in deps.items() if not d]
            if not ready:
                raise ValueError("OperationGraph contains a cycle")
            ready.sort()
            for sid in ready:
                ordered.append(by_id[sid])
                del deps[sid]
                for d in deps.values():
                    d.discard(sid)
        return ordered

    def compensation_chain(self, failed_step_id: str) -> list[OperationNode]:
        """Nodes to compensate in reverse completion order (subset before failure)."""
        order = self.topological_order()
        seen: list[OperationNode] = []
        for n in order:
            if n.step_id == failed_step_id:
                break
            if n.compensation_tool:
                seen.append(n)
        return list(reversed(seen))