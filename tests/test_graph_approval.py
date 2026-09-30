from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command

from coding_agent.graph.workflow import build_graph


class FakeModel:
    def __init__(self, responses: list[AIMessage]):
        self.responses = iter(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return next(self.responses)


def model_for_patch(diff: str) -> FakeModel:
    return FakeModel(
        [
            AIMessage(
                content="1. Inspect target\n2. Apply a focused patch\n3. Report verification status"
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "apply_patch_tool",
                        "args": {"diff": diff, "rationale": "Fix the observed defect."},
                        "id": "patch-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Patch applied; no tests were run."),
        ]
    )


@pytest.mark.asyncio
async def test_patch_requires_approval_then_resumes(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n")
    diff = "--- a/sample.py\n+++ b/sample.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    graph = build_graph(model=model_for_patch(diff))
    config = {"configurable": {"thread_id": "approval-run"}}
    interrupted = await graph.ainvoke(
        {
            "run_id": "approval-run",
            "thread_id": "approval-run",
            "workspace_path": str(tmp_path),
            "user_request": "Change the value.",
        },
        config,
    )
    assert interrupted["__interrupt__"][0].value["arguments"]["diff"] == diff
    assert source.read_text() == "value = 1\n"
    result = await graph.ainvoke(Command(resume={"approved": True}), config)
    assert source.read_text() == "value = 2\n"
    assert "sample.py" in result["final_answer"]


@pytest.mark.asyncio
async def test_rejection_does_not_apply_patch(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n")
    diff = "--- a/sample.py\n+++ b/sample.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    graph = build_graph(model=model_for_patch(diff))
    config = {"configurable": {"thread_id": "reject-run"}}
    await graph.ainvoke(
        {
            "run_id": "reject-run",
            "thread_id": "reject-run",
            "workspace_path": str(tmp_path),
            "user_request": "Change the value.",
        },
        config,
    )
    result = await graph.ainvoke(Command(resume={"approved": False}), config)
    assert source.read_text() == "value = 1\n"
    assert result["status"] == "rejected"
