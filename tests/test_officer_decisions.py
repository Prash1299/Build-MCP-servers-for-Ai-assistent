
import asyncio
import os
import unittest

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

OFFICER_URL = "http://host.docker.internal:8102/mcp"


async def call_tool(name, arguments):
    token = os.environ["OFFICER_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    async with streamablehttp_client(
        OFFICER_URL, headers=headers
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            if result.isError:
                raise AssertionError(f"{name} returned an MCP error")
            return result


def result_text(result):
    return "\n".join(
        item.text for item in result.content if hasattr(item, "text")
    )


class TestOfficerDecisions(unittest.TestCase):
    def test_approve_synthetic_application(self):
        result = asyncio.run(call_tool(
            "approve_application",
            {
                "application_id": 100015,
                "note": "Synthetic end-to-end approval test",
            },
        ))
        text = result_text(result)
        print("Approval result:", text)
        self.assertIn("APPROVED", text)
        self.assertIn("true", text.lower())

    def test_reject_synthetic_application(self):
        result = asyncio.run(call_tool(
            "reject_application",
            {
                "application_id": 100016,
                "note": "Synthetic end-to-end rejection test",
            },
        ))
        text = result_text(result)
        print("Rejection result:", text)
        self.assertIn("REJECTED", text)
        self.assertIn("true", text.lower())

    def test_repeat_approval_is_refused(self):
        result = asyncio.run(call_tool(
            "approve_application",
            {
                "application_id": 100015,
                "note": "Repeat decision should fail",
            },
        ))
        text = result_text(result)
        print("Repeat approval result:", text)
        self.assertIn("false", text.lower())
        self.assertIn("no longer pending", text.lower())

    def test_invalid_id_is_refused(self):
        result = asyncio.run(call_tool(
            "reject_application",
            {
                "application_id": -1,
                "note": "Invalid ID test",
            },
        ))
        text = result_text(result)
        print("Invalid ID result:", text)
        self.assertIn("false", text.lower())
        self.assertIn("Invalid application ID", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
