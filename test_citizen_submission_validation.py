
import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    token = os.environ["CITIZEN_TOKEN"]

    async with streamablehttp_client(
        "http://host.docker.internal:8101/mcp",
        headers={"Authorization": f"Bearer {token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "submit_pension_application",
                arguments={
                    "applicant_name": "Synthetic Validation Test",
                    "dob": "01/01/1950",
                    "village": "Test Village",
                    "block": "Sonari",
                    "bank_account": "123456789",
                    "ifsc": "SBIN0003077",
                    "document_filename": "proof.txt",
                    "document_base64": "invalid",
                },
            )

            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text)

            print("MCP tool error flag:", result.isError)


if __name__ == "__main__":
    asyncio.run(main())
