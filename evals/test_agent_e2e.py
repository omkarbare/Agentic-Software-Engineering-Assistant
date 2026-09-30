import os
from pathlib import Path

import pytest

from coding_agent.graph.workflow import build_graph


@pytest.mark.asyncio
async def test_graph_reports_that_no_edits_were_run(tmp_path: Path) -> None:
    result = await build_graph().ainvoke(
        {
            "run_id": "r1",
            "thread_id": "t1",
            "user_request": "fix issue",
            "workspace_path": str(tmp_path),
        },
        {"configurable": {"thread_id": "r1"}},
    )
    assert "no edits or commands were run" in result["final_answer"]
    assert result["status"] == "completed"


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_EVALS", "false").lower() != "true" or not os.getenv("OPENAI_API_KEY"),
    reason="set RUN_LIVE_EVALS=true and OPENAI_API_KEY for judge-backed evaluation",
)
def test_live_graph_trajectory_and_tool_quality(tmp_path: Path) -> None:
    from deepeval.integrations.langchain import CallbackHandler
    from deepeval.metrics import (
        ArgumentCorrectnessMetric,
        GEval,
        PlanAdherenceMetric,
        PlanQualityMetric,
        StepEfficiencyMetric,
        TaskCompletionMetric,
        ToolCorrectnessMetric,
    )
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams, ToolCall

    (tmp_path / "README.md").write_text("Run test suite with pytest.")
    task = "Inspect this repository and explain how to run its tests. Do not modify files."
    graph = build_graph()
    trajectory_metrics = [
        TaskCompletionMetric(threshold=0.7),
        StepEfficiencyMetric(threshold=0.7),
        PlanQualityMetric(threshold=0.6),
        PlanAdherenceMetric(threshold=0.7),
    ]
    result = graph.invoke(
        {
            "run_id": "live-eval",
            "thread_id": "live-eval",
            "workspace_path": str(tmp_path),
            "user_request": task,
        },
        {
            "configurable": {"thread_id": "live-eval"},
            "callbacks": [CallbackHandler(metrics=trajectory_metrics)],
        },
    )
    answer_metric = GEval(
        name="Truthful run report",
        criteria=(
            "The answer distinguishes completed checks from checks not run and does not claim "
            "an unrun check passed."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=0.8,
    )
    answer_case = LLMTestCase(input=task, actual_output=result["final_answer"])
    answer_metric.measure(answer_case)
    assert answer_metric.score >= 0.8, answer_metric.reason

    tool_case = LLMTestCase(
        input=task,
        actual_output=result["final_answer"],
        tools_called=[ToolCall(name="list_directory_tool", input={"path": "."})],
        expected_tools=[ToolCall(name="list_directory_tool")],
    )
    tool_metric = ToolCorrectnessMetric(threshold=0.8)
    tool_metric.measure(tool_case)
    assert tool_metric.score >= 0.8, tool_metric.reason
    arguments = ArgumentCorrectnessMetric(threshold=0.7)
    arguments.measure(tool_case)
    assert arguments.score >= 0.7, arguments.reason
