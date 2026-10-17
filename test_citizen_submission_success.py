
import asyncio
import base64
import json
import os
import sys
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


MOBILE = "0000000001"
TEST_NAME = "MCP-SUCCESS-TEST-20261016-001"


def make_test_pdf():
    """Create a minimal valid PDF clearly marked as synthetic test data."""
    content = (
        b"BT /F1 12 Tf 72 720 Td "
        b"(SYNTHETIC TEST DOCUMENT - NOT REAL AGE PROOF) Tj ET"
    )

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode()
        + b" >>\nstream\n" + content + b"\nendstream",
    ]

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]

    for number, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{number} 0 obj\n".encode())
        pdf.extend(obj + b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")

    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())

    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(pdf)


async def main():
    token = os.environ.get("CITIZEN_TOKEN")
    if not token:
        raise RuntimeError("CITIZEN_TOKEN is missing.")

    # Check token claims locally before making any application changes.
    claims = json.loads(
        base64.urlsafe_b64decode(
            token.split(".")[1] + "=" * (-len(token.split(".")[1]) % 4)
        )
    )

    if (
        claims.get("sub") != f"citizen:{MOBILE}"
        or claims.get("aud") != "http://localhost:8101"
        or claims.get("role") != "citizen"
        or claims.get("scope") != "citizen"
        or claims.get("exp", 0) <= time.time()
    ):
        raise RuntimeError(
            "Token identity, audience, role, scope, or expiry is incorrect. "
            "No submission attempted."
        )

    pdf_bytes = make_test_pdf()
    print("Synthetic PDF generated:", len(pdf_bytes), "bytes")
    print("PDF signature valid:", pdf_bytes.startswith(b"%PDF-"))

    async with streamablehttp_client(
        "http://host.docker.internal:8101/mcp",
        headers={"Authorization": f"Bearer {token}"},
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "submit_pension_application",
                arguments={
                    "applicant_name": TEST_NAME,
                    "dob": "01/01/1950",
                    "village": "Synthetic Test Village",
                    "block": "Sonari",
                    "bank_account": "123456789",
                    "ifsc": "SBIN0003077",
                    "document_filename": "synthetic_test.pdf",
                    "document_base64": base64.b64encode(
                        pdf_bytes
                    ).decode("ascii"),
                    "gender": "Other",
                    "marital_status": "Unmarried",
                },
            )

            response_text = "\n".join(
                item.text
                for item in result.content
                if hasattr(item, "text")
            )
            print("MCP response:")
            print(response_text)
            print("MCP protocol error:", result.isError)

            try:
                response = json.loads(response_text)
            except json.JSONDecodeError:
                raise RuntimeError("Could not parse the MCP response.")

            if result.isError or not response.get("success"):
                raise RuntimeError(
                    "Submission did not succeed. Do not rerun yet; "
                    "inspect the response first."
                )

            print("SUBMISSION RESULT: PASS")


if __name__ == "__main__":
    asyncio.run(main())
