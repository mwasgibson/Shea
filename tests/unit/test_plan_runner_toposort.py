import pytest

from shea.contracts.models import Plan, PlanStep
from shea.execution.operation_graph import OperationGraph


def test_topological_sort_linear():
    steps = [
        PlanStep(id="s1", plan_id="p1", order=1, description="1", tool="t", depends_on=[]),
        PlanStep(id="s2", plan_id="p1", order=2, description="2", tool="t", depends_on=["s1"]),
        PlanStep(id="s3", plan_id="p1", order=3, description="3", tool="t", depends_on=["s2"]),
    ]
    plan = Plan(id="p1", task_id="t1", objective="o", steps=steps)
    graph = OperationGraph.from_plan(plan)
    sorted_steps = graph.topological_order()
    assert [s.step_id for s in sorted_steps] == ["s1", "s2", "s3"]

def test_topological_sort_diamond():
    # s1 -> s2 -> s4
    #    -> s3 ->
    steps = [
        PlanStep(id="s4", plan_id="p1", order=4, description="", tool="t", depends_on=["s2", "s3"]),
        PlanStep(id="s2", plan_id="p1", order=2, description="", tool="t", depends_on=["s1"]),
        PlanStep(id="s3", plan_id="p1", order=3, description="", tool="t", depends_on=["s1"]),
        PlanStep(id="s1", plan_id="p1", order=1, description="", tool="t", depends_on=[]),
    ]
    plan = Plan(id="p1", task_id="t1", objective="o", steps=steps)
    graph = OperationGraph.from_plan(plan)
    sorted_steps = graph.topological_order()
    order_ids = [s.step_id for s in sorted_steps]
    assert order_ids[0] == "s1"
    assert set(order_ids[1:3]) == {"s2", "s3"}
    assert order_ids[3] == "s4"
    # Due to string sort tie-breaker on ids, s2 comes before s3
    assert order_ids[1] == "s2"
    assert order_ids[2] == "s3"

def test_topological_sort_cycle():
    steps = [
        PlanStep(id="s1", plan_id="p1", order=1, description="", tool="t", depends_on=["s2"]),
        PlanStep(id="s2", plan_id="p1", order=2, description="", tool="t", depends_on=["s1"]),
    ]
    plan = Plan(id="p1", task_id="t1", objective="o", steps=steps)
    with pytest.raises(ValueError, match="cycle"):
        OperationGraph.from_plan(plan)
