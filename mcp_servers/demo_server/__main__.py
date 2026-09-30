"""Small stdio MCP example; it has no filesystem or network tools."""

CONVENTIONS = "Use focused modules, type public interfaces, and add regression tests."


def get_project_conventions() -> str:
    return CONVENTIONS


def lookup_dependency_docs(package: str) -> str:
    return f"No offline documentation bundled for {package}."


def search_internal_docs(query: str) -> str:
    return f"No matching local demo note for: {query[:120]}"


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit("Install the optional MCP extra to run the demo server.") from exc
    server = FastMCP("coding-agent-demo")
    server.tool()(get_project_conventions)
    server.tool()(lookup_dependency_docs)
    server.tool()(search_internal_docs)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
