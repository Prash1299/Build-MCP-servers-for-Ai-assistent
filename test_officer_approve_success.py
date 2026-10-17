import asyncio
import os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    token = os.environ["OFFICER_TOKEN"]

    async with streamablehttp_client(
        "http://host.docker.internal:8102/mcp",
        headers={"Authorization": f"Bearer {token}"}
    ) as (read_stream, write_stream, _):

        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "approve_application",
                arguments={
                    "application_id": 100019,
                    "note": "Synthetic end-to-end officer approval test"
                }
            )

            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text)

            print("MCP protocol error:", result.isError)


if __name__ == "__main__":
    asyncio.run(main())