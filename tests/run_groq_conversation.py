
import asyncio
import json
import os

from openai import OpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

CITIZEN_URL = "http://host.docker.internal:8101/mcp"
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

ALLOWED_TOOLS = {
    "get_my_application_status",
}


def result_text(result):
    return "\n".join(
        item.text for item in result.content if hasattr(item, "text")
    )


def groq_client():
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is missing")

    return OpenAI(
        api_key=key,
        base_url=os.getenv(
            "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
        ),
        timeout=45.0,
    )


def log_event(conn, run_id, event_type, content):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO eval_events (run_id, event_type, content)
            VALUES (%s, %s, %s)
            """,
            (run_id, event_type, json.dumps(content, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        cur.close()


async def run_conversation(conn, run_id, token, mobile):
    client = groq_client()
    headers = {"Authorization": f"Bearer {token}"}

    user_message = (
        "Please check the status of my old-age pension application. "
        "Tell me only what the official application record shows."
    )
    log_event(conn, run_id, "USER_MESSAGE", {"content": user_message})

    tool_schemas = [{
        "type": "function",
        "function": {
            "name": "get_my_application_status",
            "description": (
                "Retrieve the authenticated citizen's latest active "
                "pension application status. This tool takes no arguments."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    }]

    messages = [
        {
            "role": "system",
            "content": (
                "You are a Seva Setu citizen assistant. Use the official "
                "MCP status tool to answer application-status questions. "
                "Never invent an application number or status. Do not "
                "request officer actions or call tools outside the citizen "
                "allowlist. Explain only information returned by the tool."
            ),
        },
        {"role": "user", "content": user_message},
    ]

    async with streamablehttp_client(
        CITIZEN_URL, headers=headers
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            available = await session.list_tools()
            available_names = {tool.name for tool in available.tools}

            if "get_my_application_status" not in available_names:
                raise RuntimeError("Citizen status tool is unavailable")

            # At most two model calls: one tool request and one final answer.
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tool_schemas,
                tool_choice="auto",
                max_tokens=300,
            )
            assistant = response.choices[0].message

            log_event(conn, run_id, "ASSISTANT_MESSAGE", {
                "content": assistant.content,
                "finish_reason": response.choices[0].finish_reason,
            })

            if not assistant.tool_calls:
                raise RuntimeError("Model did not request the status tool")

            messages.append({
                "role": "assistant",
                "content": assistant.content,
                "tool_calls": [
                    call.model_dump(exclude_none=True)
                    for call in assistant.tool_calls
                ],
            })

            tool_result = None
            for call in assistant.tool_calls:
                name = call.function.name
                if name not in ALLOWED_TOOLS:
                    raise RuntimeError("Model requested a disallowed tool")

                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    raise RuntimeError("Model produced invalid tool arguments")

                if arguments:
                    raise RuntimeError("Status tool must receive no arguments")

                log_event(conn, run_id, "MCP_TOOL_CALL", {
                    "tool": name,
                    "arguments": arguments,
                })

                result = await session.call_tool(name, arguments)
                if result.isError:
                    raise RuntimeError("Citizen MCP status tool failed")

                raw_result = result_text(result)
                try:
                    tool_result = json.loads(raw_result)
                except json.JSONDecodeError:
                    raise RuntimeError("MCP tool returned invalid JSON")

                log_event(conn, run_id, "MCP_TOOL_RESULT", {
                    "tool": name,
                    "result": tool_result,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

            final_response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=300,
            )
            final_text = final_response.choices[0].message.content or ""

            log_event(conn, run_id, "ASSISTANT_FINAL", {
                "content": final_text,
            })

            # Independent database check against the authenticated mobile.
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT id, application_no, status
                    FROM applications
                    WHERE mobile = %s
                      AND status IN ('PENDING', 'APPROVED')
                    ORDER BY submitted_at DESC, id DESC
                    LIMIT 1
                    """,
                    (mobile,),
                )
                db_row = cur.fetchone()
            finally:
                cur.close()

            found_matches = (
                tool_result.get("found") is True and db_row is not None
                and tool_result.get("application_id") == db_row[0]
                and tool_result.get("application_number") == db_row[1]
                and tool_result.get("status") == db_row[2]
            )
            no_active_matches = (
                tool_result.get("found") is False and db_row is None
            )

            checks = [
                (
                    "Citizen status tool returned a valid response",
                    isinstance(tool_result.get("found"), bool),
                    "found is boolean",
                    repr(tool_result),
                ),
                (
                    "Tool result matches database for authenticated citizen",
                    found_matches or no_active_matches,
                    "tool result agrees with active application query",
                    f"tool={tool_result!r}; db={db_row!r}",
                ),
                (
                    "Groq produced a final answer",
                    bool(final_text.strip()),
                    "non-empty final answer",
                    final_text,
                ),
            ]

            for name, passed, expected, actual in checks:
                cur = conn.cursor()
                try:
                    cur.execute(
                        """
                        INSERT INTO eval_checks
                            (run_id, check_name, expected, actual, passed)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (run_id, name, expected, actual, passed),
                    )
                finally:
                    cur.close()

            passed_count = sum(1 for _, passed, _, _ in checks if passed)
            outcome = "PASS" if passed_count == len(checks) else "FAIL"

            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    UPDATE eval_runs
                    SET finished_at = CURRENT_TIMESTAMP,
                        outcome = %s,
                        summary = %s
                    WHERE id = %s
                    """,
                    (
                        outcome,
                        f"{passed_count}/{len(checks)} checks passed; "
                        "read-only Groq citizen status conversation.",
                        run_id,
                    ),
                )
            finally:
                cur.close()
            conn.commit()

            print("Run ID:", run_id)
            print("Outcome:", outcome)
            print("Tool result:", json.dumps(tool_result, ensure_ascii=False))
            print("Assistant final:", final_text)
            print("Checks:")
            for name, passed, _, _ in checks:
                print(f"  {'PASS' if passed else 'FAIL'} - {name}")


def main():
    token = os.environ.get("CITIZEN_TOKEN")
    mobile = os.environ.get("EXPECTED_CITIZEN_MOBILE", "0000000002")
    if not token:
        raise RuntimeError("CITIZEN_TOKEN is missing")

    import app as portal

    conn = portal.get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO eval_runs (persona_id, scenario, outcome, summary)
            VALUES (2, 'groq_read_only_status_conversation', 'RUNNING',
                    'Groq citizen status conversation; read-only.')
            RETURNING id
            """
        )
        run_id = cur.fetchone()[0]
        conn.commit()
    finally:
        cur.close()

    try:
        asyncio.run(run_conversation(conn, run_id, token, mobile))
    except Exception as exc:
        log_event(conn, run_id, "EVALUATION_ERROR", {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
        })
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE eval_runs
                SET finished_at = CURRENT_TIMESTAMP,
                    outcome = 'ERROR',
                    summary = %s
                WHERE id = %s
                """,
                (f"{type(exc).__name__}: {str(exc)[:900]}", run_id),
            )
            conn.commit()
        finally:
            cur.close()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
