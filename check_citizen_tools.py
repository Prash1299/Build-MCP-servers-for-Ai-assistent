import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    token = os.environ.get("CITIZEN_TOKEN")
    if not token:
        raise RuntimeError("CITIZEN_TOKEN is missing")

    async with streamablehttp_client(
        "http://host.docker.internal:8101/mcp",
        headers={"Authorization": f"Bearer {token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Citizen MCP tools:", [tool.name for tool in tools.tools])


if __name__ == "__main__":
    asyncio.run(main())