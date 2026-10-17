
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def read_result(result):
    """Extract a dictionary from an MCP tool result."""
    data = getattr(result, "structuredContent", None)

    if isinstance(data, dict):
        return data

    for item in result.content:
        if hasattr(item, "text"):
            try:
                parsed = json.loads(item.text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    return {}


async def main():
    token = os.environ.get("CITIZEN_TOKEN")
    if not token:
        raise RuntimeError("CITIZEN_TOKEN environment variable is missing")

    url = "http://host.docker.internal:8101/mcp"
    headers = {"Authorization": f"Bearer {token}"}

    async with streamablehttp_client(url, headers=headers) as (
        read_stream, write_stream, _
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("MCP initialization: PASS")

            result = await session.list_tools()
            tool_names = [tool.name for tool in result.tools]
            print("Available citizen tools:", tool_names)

            required = {
                "get_my_application_status",
                "withdraw_my_pending_application",
            }
            if not required.issubset(set(tool_names)):
                raise AssertionError("A required citizen tool is missing")

            print("Citizen tool discovery: PASS")

            # Check status, but do not assume it is the application
            # that the withdrawal tool will select.
            status_result = await session.call_tool(
                "get_my_application_status", arguments={}
            )
            if status_result.isError:
                raise RuntimeError("Status tool returned an MCP error")

            status_data = read_result(status_result)
            print("Status tool call: PASS")
            print("Application found:", status_data.get("found"))
            print("Reported status:", status_data.get("status"))

            # Withdraw a pending application belonging to this token.
            withdrawal = await session.call_tool(
                "withdraw_my_pending_application", arguments={}
            )
            if withdrawal.isError:
                raise RuntimeError("Withdrawal tool returned an MCP error")

            withdrawal_data = read_result(withdrawal)
            print("Withdrawal tool call: PASS")
            print("Withdrawal successful:", withdrawal_data.get("success"))

            if not withdrawal_data.get("success"):
                print("No pending application was available to withdraw.")
                print("Withdrawal test: NOT COMPLETED")
                return

            application_id = withdrawal_data.get("application_id")
            if not isinstance(application_id, int):
                raise AssertionError("Withdrawal returned no valid application ID")

            print("Returned status:", withdrawal_data.get("status"))

            # Verify the exact application ID directly in the database.
            # This test runs inside the portal's app container.
            import app as portal

            conn = portal.get_db()
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT status, decided_by FROM applications WHERE id = %s",
                    (application_id,),
                )
                row = cur.fetchone()

                if not row:
                    raise AssertionError(
                        "Withdrawn application was not found in the database"
                    )

                db_status, decided_by = row

                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM audit_log
                    WHERE application_id = %s
                      AND action = 'WITHDRAW'
                      AND actor LIKE 'applicant:%'
                    """,
                    (application_id,),
                )
                audit_count = cur.fetchone()[0]
            finally:
                cur.close()
                conn.close()

            print("Database status:", db_status)
            print("Applicant audit entries:", audit_count)

            if db_status != "WITHDRAWN":
                raise AssertionError("Database status is not WITHDRAWN")

            if decided_by != "APPLICANT":
                raise AssertionError("Unexpected decision identity")

            if audit_count < 1:
                raise AssertionError("Withdrawal audit entry is missing")

            print("Exact application database verification: PASS")
            print("END-TO-END WITHDRAWAL TEST: PASS")


if __name__ == "__main__":
    asyncio.run(main())
