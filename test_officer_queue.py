
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    token = os.environ["OFFICER_TOKEN"]

    async with streamablehttp_client(
        "http://host.docker.internal:8102/mcp",
        headers={"Authorization": f"Bearer {token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Officer tools:", [tool.name for tool in tools.tools])

            result = await session.call_tool(
                "list_pending_applications",
                arguments={"limit": 20},
            )

            for item in result.content:
                if hasattr(item, "text"):
                    print("Queue response:")
                    print(item.text)

            print("MCP protocol error:", result.isError)


if __name__ == "__main__":
    asyncio.run(main())
