
import asyncio
import base64
import json
import os
import uuid
from datetime import datetime, timezone

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

CITIZEN_URL = "http://host.docker.internal:8101/mcp"


def result_text(result):
    return "\n".join(
        item.text for item in result.content if hasattr(item, "text")
    )


async def submit_application(arguments):
    token = os.environ["CITIZEN_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

    async with streamablehttp_client(
        CITIZEN_URL, headers=headers
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "submit_pension_application", arguments
            )
            if result.isError:
                raise RuntimeError("MCP tool returned a protocol error")
            return json.loads(result_text(result))


def main():
    run_tag = uuid.uuid4().hex[:10]
    run_id = None
    persona_id = 1
    application_id = None
    checks = []

    # Synthetic document only. This is not real age proof.
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"SYNTHETIC TEST DOCUMENT - NOT REAL AGE PROOF\n"
        b"%%EOF\n"
    )
    arguments = {
        "applicant_name": f"EVAL-KAMLA-{run_tag}",
        "dob": "01/01/1950",
        "village": "Synthetic Eval Village",
        "block": "Sonari",
        "bank_account": "123456789",
        "ifsc": "SBIN0003077",
        "document_filename": "synthetic-eval.pdf",
        "document_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "gender": "Other",
        "marital_status": "Unmarried",
    }

    import app as portal

    conn = portal.get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO eval_runs
                (persona_id, scenario, outcome, summary)
            VALUES (%s, %s, 'RUNNING', %s)
            RETURNING id
            """,
            (
                persona_id,
                "eligible_citizen_submission",
                "Synthetic applicant; real citizen MCP tool call.",
            ),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
    finally:
        cur.close()
        conn.close()

    try:
        conn = portal.get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO eval_events (run_id, event_type, content)
                VALUES (%s, %s, %s)
                """,
                (
                    run_id,
                    "USER_REQUEST",
                    json.dumps({
                        "summary": (
                            "A citizen requests an old-age pension "
                            "application."
                        ),
                        "applicant_name": arguments["applicant_name"],
                        "block": arguments["block"],
                        "dob": arguments["dob"],
                    }),
                ),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()

        result = asyncio.run(submit_application(arguments))
        application_id = result.get("application_id")

        conn = portal.get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO eval_events (run_id, event_type, content)
                VALUES (%s, %s, %s)
                """,
                (run_id, "MCP_TOOL_RESULT", json.dumps(result)),
            )

            cur.execute(
                """
                SELECT id, application_no, applicant_name, mobile, status
                FROM applications
                WHERE id = %s
                """,
                (application_id,),
            )
            app_row = cur.fetchone()

            cur.execute(
                """
                SELECT action, actor
                FROM audit_log
                WHERE application_id = %s
                ORDER BY id
                """,
                (application_id,),
            )
            audit_rows = cur.fetchall()

            expected_mobile = os.environ.get("EXPECTED_CITIZEN_MOBILE", "0000000002")
            checks = [
                (
                    "MCP submission succeeded",
                    result.get("success") is True,
                    "success=true",
                    str(result.get("success")),
                ),
                (
                    "Application exists in database",
                    app_row is not None,
                    "one matching application row",
                    repr(app_row),
                ),
                (
                    "Application status is PENDING",
                    bool(app_row and app_row[4] == "PENDING"),
                    "PENDING",
                    str(app_row[4] if app_row else None),
                ),
                (
                    "Application belongs to authenticated citizen",
                    bool(app_row and app_row[3] == expected_mobile),
                    expected_mobile,
                    str(app_row[3] if app_row else None),
                ),
                (
                    "SUBMIT audit entry exists",
                    any(action == "SUBMIT" for action, _ in audit_rows),
                    "SUBMIT",
                    repr(audit_rows),
                ),
                (
                    "Audit actor matches authenticated citizen",
                    any(
                        action == "SUBMIT" and actor == f"applicant:{expected_mobile}"
                        for action, actor in audit_rows
                    ),
                    f"applicant:{expected_mobile}",
                    repr(audit_rows),
                ),
            ]

            for name, passed, expected, actual in checks:
                cur.execute(
                    """
                    INSERT INTO eval_checks
                        (run_id, check_name, expected, actual, passed)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (run_id, name, expected, actual, passed),
                )

            passed_count = sum(1 for _, passed, _, _ in checks if passed)
            outcome = "PASS" if passed_count == len(checks) else "FAIL"

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
                    f"{passed_count}/{len(checks)} database-backed checks passed.",
                    run_id,
                ),
            )
            conn.commit()

            print("Run ID:", run_id)
            print("Application ID:", application_id)
            print("Application number:", result.get("application_number"))
            print("Outcome:", outcome)
            print("Checks:")
            for name, passed, expected, actual in checks:
                print(f"  {'PASS' if passed else 'FAIL'} - {name}")
                if not passed:
                    print("    Expected:", expected)
                    print("    Actual:", actual)
        finally:
            cur.close()
            conn.close()

    except Exception as exc:
        conn = portal.get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO eval_events (run_id, event_type, content) VALUES (%s, %s, %s)",
                (run_id, "EVALUATION_ERROR", str(exc)),
            )
            cur.execute(
                """
                UPDATE eval_runs
                SET finished_at = CURRENT_TIMESTAMP,
                    outcome = 'ERROR',
                    summary = %s
                WHERE id = %s
                """,
                (str(exc)[:1000], run_id),
            )
            conn.commit()
        finally:
            cur.close()
            conn.close()
        raise


if __name__ == "__main__":
    main()
