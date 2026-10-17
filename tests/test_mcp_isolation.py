
import asyncio
import os
import unittest

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


CITIZEN_URL = "http://host.docker.internal:8101/mcp"
OFFICER_URL = "http://host.docker.internal:8102/mcp"


async def get_tools(url, token):
    """Connect to an MCP endpoint and return its tool names."""
    headers = {"Authorization": f"Bearer {token}"}

    async with streamablehttp_client(url, headers=headers) as (
        read_stream, write_stream, _
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return {tool.name for tool in result.tools}


class TestMCPRoleIsolation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.citizen_token = os.environ.get("CITIZEN_TOKEN")
        cls.officer_token = os.environ.get("OFFICER_TOKEN")

        if not cls.citizen_token or not cls.officer_token:
            raise RuntimeError(
                "Load CITIZEN_TOKEN and OFFICER_TOKEN before running tests."
            )

    def test_citizen_can_access_citizen_tools(self):
        tools = asyncio.run(get_tools(CITIZEN_URL, self.citizen_token))
        self.assertIn("get_my_application_status", tools)
        self.assertIn("withdraw_my_pending_application", tools)

    
    def test_officer_can_access_officer_tools(self):
        tools = asyncio.run(get_tools(OFFICER_URL, self.officer_token))
        self.assertIn("list_pending_applications", tools)
        self.assertIn("approve_application", tools)
        self.assertIn("reject_application", tools)

    def test_citizen_token_cannot_access_officer_server(self):
        with self.assertRaises(Exception):
            asyncio.run(get_tools(OFFICER_URL, self.citizen_token))

    def test_officer_token_cannot_access_citizen_server(self):
        with self.assertRaises(Exception):
            asyncio.run(get_tools(CITIZEN_URL, self.officer_token))


if __name__ == "__main__":
    unittest.main(verbosity=2)
