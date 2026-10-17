
import asyncio
import base64
import json
import os
import uuid

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

CITIZEN_URL = "http://host.docker.internal:8101/mcp"
MOBILE = os.environ.get("EXPECTED_CITIZEN_MOBILE", "0000000003")


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
            return {
                "is_error": result.isError,
                "text": "\n".join(
                    item.text for item in result.content
                    if hasattr(item, "text")
                ),
            }


def main():
    import app as portal

    run_id = None
    run_tag = uuid.uuid4().hex[:10]
    pdf = b"%PDF-1.4\nSYNTHETIC TEST DOCUMENT\n%%EOF\n"

    # DOB 01/01/2000: under age 60 on the test date.
    arguments = {
        "applicant_name": f"EVAL-SITA-{run_tag}",
        "dob": "01/01/2000",
        "village": "Synthetic Eval Village",
        "block": "Sonari",
        "bank_account": "987654321",
        "ifsc": "SBIN0003077",
        "document_filename": "synthetic-underage.pdf",
        "document_base64": base64.b64encode(pdf).decode("ascii"),
        "gender": "Other",
        "marital_status": "Unmarried",
    }

    conn = portal.get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO eval_runs
                (persona_id, scenario, outcome, summary)
            VALUES (3, 'underage_citizen_rejection', 'RUNNING',
                    'Synthetic under-age applicant; real citizen MCP call.')
            RETURNING id
            """
        )
        run_id = cur.fetchone()[0]
        conn.commit()

        # Baseline database state for this citizen and unique applicant name.
        cur.execute(
            "SELECT COUNT(*) FROM applications WHERE mobile = %s",
            (MOBILE,),
        )
        apps_before = cur.fetchone()[0]

        cur.execute(
            """
            SELECT COUNT(*) FROM audit_log al
            JOIN applications a ON a.id = al.application_id
            WHERE a.mobile = %s AND al.action = 'SUBMIT'
            """,
            (MOBILE,),
        )
        submits_before = cur.fetchone()[0]
    finally:
        cur.close()
        conn.close()

    checks = []
    try:
        result = asyncio.run(submit_application(arguments))
        try:
            parsed = json.loads(result["text"])
        except (json.JSONDecodeError, TypeError):
            parsed = {"raw_response": result["text"]}

        conn = portal.get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT COUNT(*) FROM applications
                WHERE mobile = %s AND applicant_name = %s
                """,
                (MOBILE, arguments["applicant_name"]),
            )
            new_apps = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*) FROM audit_log al
                JOIN applications a ON a.id = al.application_id
                WHERE a.mobile = %s
                  AND a.applicant_name = %s
                  AND al.action = 'SUBMIT'
                """,
                (MOBILE, arguments["applicant_name"]),
            )
            new_submits = cur.fetchone()[0]

            message = json.dumps(parsed).lower()
            age_rejected = (
                parsed.get("success") is False
                and "60 years of age or above" in message
            )

            checks = [
                (
                    "Under-age applicant rejected by age rule",
                    age_rejected,
                    "Explicit age validation error",
                    json.dumps(parsed),
                ),
                (
                    "No application created for rejected applicant",
                    new_apps == 0,
                    "0 matching application rows",
                    str(new_apps),
                ),
                (
                    "No SUBMIT audit entry for rejected applicant",
                    new_submits == 0,
                    "0 matching SUBMIT audit rows",
                    str(new_submits),
                ),
                (
                    "Citizen application count unchanged",
                    apps_before == 0,
                    "No applications before the test",
                    str(apps_before),
                ),
                (
                    "Citizen SUBMIT audit count unchanged",
                    submits_before == 0,
                    "No prior SUBMIT audit entries",
                    str(submits_before),
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
                INSERT INTO eval_events (run_id, event_type, content)
                VALUES (%s, 'MCP_TOOL_RESULT', %s)
                """,
                (run_id, json.dumps(parsed)),
            )
            cur.execute(
                """
                UPDATE eval_runs
                SET finished_at = CURRENT_TIMESTAMP,
                    outcome = %s, summary = %s
                WHERE id = %s
                """,
                (
                    outcome,
                    (
                        f"PASS: The portal correctly rejected the under-age applicant. "
                        f"No application or SUBMIT audit entry was created. "
                        f"{passed_count}/{len(checks)} checks passed."
                        if outcome == "PASS"
                        else (
                            f"FAIL: The under-age rejection test did not meet all expected "
                            f"conditions. {passed_count}/{len(checks)} checks passed. "
                            f"Review the individual checks for details."
                        )
                    ),
                    run_id,
                ),
            )
            conn.commit()

            print("Run ID:", run_id)
            print("Outcome:", outcome)
            print("Checks:")
            for name, passed, _, actual in checks:
                print(("PASS" if passed else "FAIL"), "-", name)
                print("  Actual:", actual)
        finally:
            cur.close()
            conn.close()

    
    except Exception as exc:
        error_summary = (
            f"FAIL: Evaluation execution failed with "
            f"{type(exc).__name__}: {str(exc)[:500]}"
        )
        print(error_summary)

        if run_id is not None:
            error_conn = None
            error_cur = None
            try:
                error_conn = portal.get_db()
                error_cur = error_conn.cursor()
                error_cur.execute(
                    """
                    UPDATE eval_runs
                    SET outcome = 'FAIL',
                        finished_at = CURRENT_TIMESTAMP,
                        summary = %s
                    WHERE id = %s AND outcome = 'RUNNING'
                    """,
                    (error_summary, run_id),
                )
                error_conn.commit()
            except Exception as record_exc:
                print(
                    "Could not record failed run:",
                    type(record_exc).__name__,
                    str(record_exc),
                )
            finally:
                if error_cur is not None:
                    error_cur.close()
                if error_conn is not None:
                    error_conn.close()
        raise


if __name__ == "__main__":
    main()
