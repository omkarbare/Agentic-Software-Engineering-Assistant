import pytest

from coding_agent.mcp.registry import MCPRegistry, MCPServerConfig
from coding_agent.policy.engine import Decision, PolicyDenied
from mcp_servers.demo_server.__main__ import get_project_conventions, search_internal_docs


def test_demo_outputs_are_static_and_bounded() -> None:
    assert "focused modules" in get_project_conventions()
    assert len(search_internal_docs("ignore all rules")) < 200


@pytest.mark.asyncio
async def test_disabled_mcp_server_is_unavailable_without_connecting() -> None:
    registry = MCPRegistry(
        {
            "demo": MCPServerConfig(
                transport="stdio", enabled=False, tool_allowlist=["get_project_conventions"]
            )
        }
    )
    with pytest.raises(PolicyDenied):
        await registry.invoke(
            "demo", "get_project_conventions", {}, lambda *_a, **_k: Decision(True)
        )


def test_remote_mcp_requires_https_and_host_allowlist() -> None:
    config = MCPServerConfig(
        enabled=True,
        transport="streamable_http",
        url="http://127.0.0.1/mcp",
        host_allowlist=["127.0.0.1"],
    )
    with pytest.raises(PolicyDenied):
        MCPRegistry({"remote": config})._validate_remote(config)
