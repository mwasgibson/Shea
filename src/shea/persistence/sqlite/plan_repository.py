from __future__ import annotations

import json
import sqlite3

from shea.contracts.enums import RiskLevel
from shea.contracts.models import Plan, PlanStep


class SqlitePlanRepository:
    """Concrete adapter for the PlanRepository port.

    `save` replaces the full set of steps for a plan (delete-then-insert)
    rather than diffing — Phase 1 plans are small and this keeps the
    adapter simple; revisit if step counts grow large enough for it to
    matter.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, plan: Plan) -> None:
        self._conn.execute(
            """
            INSERT INTO plans (id, task_id, objective, assumptions, risk, result)
            VALUES (:id, :task_id, :objective, :assumptions, :risk, :result)
            ON CONFLICT(id) DO UPDATE SET
                objective = excluded.objective,
                assumptions = excluded.assumptions,
                risk = excluded.risk,
                result = excluded.result
            """,
            {
                "id": plan.id,
                "task_id": plan.task_id,
                "objective": plan.objective,
                "assumptions": json.dumps(plan.assumptions),
                "risk": plan.risk.value if plan.risk else None,
                "result": plan.result,
            },
        )
        self._conn.execute("DELETE FROM plan_steps WHERE plan_id = ?", (plan.id,))
        for step in plan.steps:
            self._conn.execute(
                """
                INSERT INTO plan_steps
                    (id, plan_id, step_order, description, tool, arguments, state)
                VALUES
                    (:id, :plan_id, :step_order, :description, :tool, :arguments, :state)
                """,
                {
                    "id": step.id,
                    "plan_id": plan.id,
                    "step_order": step.order,
                    "description": step.description,
                    "tool": step.tool,
                    "arguments": json.dumps(step.arguments),
                    "state": step.state,
                },
            )
        self._conn.commit()

    def get_by_task(self, task_id: str) -> Plan | None:
        plan_row = self._conn.execute(
            "SELECT * FROM plans WHERE task_id = ?", (task_id,)
        ).fetchone()
        if plan_row is None:
            return None

        step_rows = self._conn.execute(
            "SELECT * FROM plan_steps WHERE plan_id = ? ORDER BY step_order",
            (plan_row["id"],),
        ).fetchall()

        steps = [
            PlanStep(
                id=row["id"],
                plan_id=row["plan_id"],
                order=row["step_order"],
                description=row["description"],
                tool=row["tool"],
                arguments=json.loads(row["arguments"]),
                state=row["state"],
            )
            for row in step_rows
        ]

        return Plan(
            id=plan_row["id"],
            task_id=plan_row["task_id"],
            objective=plan_row["objective"],
            assumptions=json.loads(plan_row["assumptions"]),
            steps=steps,
            risk=RiskLevel(plan_row["risk"]) if plan_row["risk"] else None,
            result=plan_row["result"],
        )