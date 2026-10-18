import os
import base64
import binascii
import secrets
from datetime import date, datetime
from mcp.server.transport_security import TransportSecuritySettings

import app as portal
from mcp.server.fastmcp import FastMCP, Context

from mcp_servers.auth import (
    authenticate_token,
    bearer_token,
    CITIZEN_AUDIENCE,
)

mcp = FastMCP(
    "Seva Setu Citizen Server",
    instructions=(
        "Citizen-facing tools. Only return information belonging to "
        "the authenticated citizen. Never expose bank details or document paths."
    ),
)


def get_citizen_mobile(ctx: Context) -> str:
    request = ctx.request_context.request
    claims = request.scope.get("state", {}).get("claims")

    if not claims or claims.get("role") != "citizen":
        raise PermissionError("Authenticated citizen claims are missing")

    return claims["sub"].removeprefix("citizen:")


def serialize_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


@mcp.tool()
def get_my_application_status(ctx: Context) -> dict:
    """Get the authenticated citizen's latest active application status."""
    mobile = get_citizen_mobile(ctx)

    conn = portal.get_db()
    cur = conn.cursor()

    try:
        application = portal.active_application(cur, mobile)

        if not application:
            return {
                "found": False,
                "message": "No active application was found for your account.",
            }

        app_id, application_no, status = application

        cur.execute(
            """
            SELECT applicant_name, village, block, submitted_at, decided_at
            FROM applications
            WHERE id = %s AND mobile = %s
            """,
            (app_id, mobile),
        )
        row = cur.fetchone()

        if not row:
            return {
                "found": False,
                "message": "Application details could not be retrieved.",
            }

        applicant_name, village, block, submitted_at, decided_at = row

        return {
            "found": True,
            "application_id": app_id,
            "application_number": application_no,
            "applicant_name": applicant_name,
            "village": village,
            "block": block,
            "status": status,
            "submitted_at": serialize_value(submitted_at),
            "decided_at": serialize_value(decided_at),
        }
    finally:
        cur.close()
        conn.close()


@mcp.tool()
def withdraw_my_pending_application(ctx: Context) -> dict:
    """Withdraw the authenticated citizen's own pending application."""
    mobile = get_citizen_mobile(ctx)

    conn = portal.get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            WITH target AS (
        SELECT id
        FROM applications
        WHERE mobile = %s
          AND status = 'PENDING'
        ORDER BY submitted_at DESC, id DESC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE applications AS a
    SET status = 'WITHDRAWN',
        decided_at = %s,
        decided_by = 'APPLICANT'
    FROM target
    WHERE a.id = target.id
      AND a.mobile = %s
      AND a.status = 'PENDING'
    RETURNING a.id, a.application_no
            """,
            (mobile, portal.now_ist(), mobile),
        )

        row = cur.fetchone()

        if not row:
            conn.rollback()
            return {
                "success": False,
                "message": (
                    "No pending application was found to withdraw. "
                    "Only your own pending application can be withdrawn."
                ),
            }

        application_id, application_number = row

        portal.write_audit(
            cur,
            application_id,
            "WITHDRAW",
            "applicant:%s" % mobile,
        )

        conn.commit()

        return {
            "success": True,
            "application_id": application_id,
            "application_number": application_number,
            "status": "WITHDRAWN",
            "message": "Your pending application has been withdrawn.",
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

@mcp.tool()
def submit_pension_application(
    ctx: Context,
    applicant_name: str,
    dob: str,
    village: str,
    block: str,
    bank_account: str,
    ifsc: str,
    document_filename: str,
    document_base64: str,
    gender: str = "",
    marital_status: str = "",
    husband_name: str = "",
) -> dict:
    """Submit a pension application for the authenticated citizen with age proof.

    The age-proof document must be a base64-encoded PDF, JPG, JPEG, or PNG
    no larger than 5 MB. Never submit a filesystem path as a document.
    """
    mobile = get_citizen_mobile(ctx)

    allowed_extensions = {"pdf", "jpg", "jpeg", "png"}
    extension = (document_filename or "").rsplit(".", 1)[-1].lower()

    if extension not in allowed_extensions:
        return {
            "success": False,
            "message": "Age proof must be a PDF, JPG, JPEG, or PNG file.",
        }

    if not document_base64:
        return {"success": False, "message": "Age-proof document is required."}

    # Bound encoded input before decoding to limit memory usage.
    max_bytes = 5 * 1024 * 1024
    if len(document_base64) > ((max_bytes + 2) // 3) * 4 + 16:
        return {"success": False, "message": "Document exceeds the 5 MB limit."}

    try:
        document_bytes = base64.b64decode(document_base64, validate=True)
    except (binascii.Error, ValueError):
        return {
            "success": False,
            "message": "Document content must be valid base64.",
        }

    if not document_bytes or len(document_bytes) > max_bytes:
        return {"success": False, "message": "Document must be between 1 byte and 5 MB."}

    # Verify basic file signatures; do not trust the filename alone.
    signatures = {
        "pdf": lambda b: b.startswith(b"%PDF-"),
        "jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
        "jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
        "png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    }
    if not signatures[extension](document_bytes):
        return {
            "success": False,
            "message": "The document content does not match its file type.",
        }

    data = {
        "applicant_name": applicant_name,
        "dob": dob,
        "village": village,
        "block": block,
        "bank_account": bank_account,
        "ifsc": ifsc,
        "gender": gender,
        "marital_status": marital_status,
        "husband_name": husband_name,
    }

    upload_dir = portal.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)

    # Generated name prevents path traversal and collisions. The original
    # filename is not used as a filesystem path.
    safe_name = "%s_mcp_%s.%s" % (
        mobile,
        secrets.token_hex(12),
        extension,
    )
    document_path = os.path.join(upload_dir, safe_name)

    conn = portal.get_db()
    cur = conn.cursor()
    file_created = False

    try:
        errors, cleaned = portal.validate_application(data, document_path)
        if errors:
            return {
                "success": False,
                "message": "Application validation failed.",
                "errors": errors,
            }

        # Serialize submissions for the same mobile to reduce duplicate races.
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (mobile,),
        )

        existing = portal.active_application(cur, mobile)
        if existing:
            return {
                "success": False,
                "message": "An active application already exists for your account.",
                "existing_application_number": existing[1],
                "existing_status": existing[2],
            }

        with open(document_path, "xb") as out:
            out.write(document_bytes)
        file_created = True

        application_id, application_number = portal.create_application(
            cur, mobile, cleaned
        )
        conn.commit()

        return {
            "success": True,
            "application_id": application_id,
            "application_number": application_number,
            "status": "PENDING",
            "message": "Your pension application was submitted successfully.",
        }

    except Exception:
        conn.rollback()
        if file_created:
            try:
                os.remove(document_path)
            except OSError:
                pass
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
            "localhost:8101",
            "127.0.0.1:8101",
            "citizen-mcp:8101",
            "host.docker.internal:8101",
            "perpetual-liberation-production-16d0.up.railway.app",
        ],
    )
    
    app = mcp.streamable_http_app()
    protected_app = MCPAuthMiddleware(
        app,
        audience=os.getenv(
            "CITIZEN_MCP_AUDIENCE",
            "http://localhost:8101",
        ),
        role="citizen",
    )

    uvicorn.run(
        protected_app,
        host="0.0.0.0",
        port=8101,
    )

