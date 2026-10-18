
import os
from datetime import date, datetime
from mcp.server.transport_security import TransportSecuritySettings

import app as portal
from mcp.server.fastmcp import FastMCP, Context

from mcp_servers.auth import authenticate_token, bearer_token

OFFICER_AUDIENCE = os.getenv(
    "OFFICER_MCP_AUDIENCE",
    "http://localhost:8102",
)

mcp = FastMCP(
    "Seva Setu Officer Server",
    instructions=(
        "Officer-only tools for reviewing pension applications. "
        "Never expose these tools to citizen accounts. "
        "Return only information needed for official case review."
    ),
)



def get_officer_identity(ctx: Context) -> str:
    request = ctx.request_context.request
    claims = request.scope.get("state", {}).get("claims")

    if not claims or claims.get("role") != "officer":
        raise PermissionError("Authenticated officer claims are missing")

    return claims["sub"].removeprefix("officer:")



def serialize_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


@mcp.tool()
def list_pending_applications(ctx: Context, limit: int = 20) -> dict:
    """List basic details of pending applications for an authenticated officer."""
    officer = get_officer_identity(ctx)

    if not 1 <= limit <= 100:
        return {"error": "limit must be between 1 and 100"}

    conn = portal.get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT id, application_no, applicant_name,
                   village, block, status, submitted_at
            FROM applications
            WHERE status = 'PENDING'
            ORDER BY submitted_at ASC
            LIMIT %s
            """,
            (limit,),
        )

        rows = cur.fetchall()

        return {
            "officer": officer,
            "count": len(rows),
            "applications": [
                {
                    "application_id": row[0],
                    "application_number": row[1],
                    "applicant_name": row[2],
                    "village": row[3],
                    "block": row[4],
                    "status": row[5],
                    "submitted_at": serialize_value(row[6]),
                }
                for row in rows
            ],
        }
    finally:
        cur.close()
        conn.close()


@mcp.tool()
def approve_application(
    ctx: Context,
    application_id: int,
    note: str = "",
) -> dict:
    """Approve a pending pension application as the authenticated officer."""
    officer = get_officer_identity(ctx)

    if application_id <= 0:
        return {"success": False, "message": "Invalid application ID."}

    if len(note) > 500:
        return {
            "success": False,
            "message": "Note must be 500 characters or fewer.",
        }

    conn = portal.get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            UPDATE applications
            SET status = 'APPROVED',
                decided_at = %s,
                decided_by = %s
            WHERE id = %s
              AND status = 'PENDING'
            RETURNING id, application_no
            """,
            (portal.now_ist(), officer, application_id),
        )

        row = cur.fetchone()

        if row is None:
            conn.rollback()
            return {
                "success": False,
                "message": (
                    "Application not found or no longer pending. "
                    "Only pending applications can be approved."
                ),
            }

        portal.write_audit(
            cur,
            row[0],
            "APPROVED",
            "officer:" + officer,
            note,
        )

        conn.commit()

        return {
            "success": True,
            "application_id": row[0],
            "application_number": row[1],
            "status": "APPROVED",
            "officer": officer,
            "message": "Application approved successfully.",
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()




@mcp.tool()
def reject_application(
    ctx: Context,
    application_id: int,
    note: str = "",
) -> dict:
    """Reject a pending pension application as the authenticated officer."""
    officer = get_officer_identity(ctx)

    if application_id <= 0:
        return {"success": False, "message": "Invalid application ID."}

    if len(note) > 500:
        return {
            "success": False,
            "message": "Note must be 500 characters or fewer.",
        }

    conn = portal.get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            UPDATE applications
            SET status = 'REJECTED',
                decided_at = %s,
                decided_by = %s
            WHERE id = %s
              AND status = 'PENDING'
            RETURNING id, application_no
            """,
            (portal.now_ist(), officer, application_id),
        )

        row = cur.fetchone()

        if row is None:
            conn.rollback()
            return {
                "success": False,
                "message": (
                    "Application not found or no longer pending. "
                    "Only pending applications can be rejected."
                ),
            }

        portal.write_audit(
            cur,
            row[0],
            "REJECTED",
            "officer:" + officer,
            note,
        )

        conn.commit()

        return {
            "success": True,
            "application_id": row[0],
            "application_number": row[1],
            "status": "REJECTED",
            "officer": officer,
            "message": "Application rejected successfully.",
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()



if __name__ == "__main__":
    import uvicorn
    from mcp_servers.http_auth import MCPAuthMiddleware

    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "localhost:8102",
            "127.0.0.1:8102",
            "officer-mcp:8102",
            "host.docker.internal:8102",
            "gallant-reverence-production-ed24.up.railway.app"
        ],
    )
    
    app = mcp.streamable_http_app()
    protected_app = MCPAuthMiddleware(
        app,
        audience=OFFICER_AUDIENCE,
        role="officer",
    )

    uvicorn.run(protected_app, host="0.0.0.0", port=8102)
