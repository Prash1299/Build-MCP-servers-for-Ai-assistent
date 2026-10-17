
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

BASE_URL = "http://localhost:8000"
CLIENT_ID = "ssc_4Hd0xomwEFSEPOoa_tLOmQ"

refresh_path = Path("test_citizen_refresh_token.txt")
refresh_token = refresh_path.read_text(encoding="utf-8").strip()

if not refresh_token:
    raise SystemExit("Refresh-token file is empty.")

payload = urlencode({
    "grant_type": "refresh_token",
    "client_id": CLIENT_ID,
    "refresh_token": refresh_token,
    "resource": "http://localhost:8101",
}).encode("utf-8")

request = Request(
    f"{BASE_URL}/oauth/token",
    data=payload,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    method="POST",
)

try:
    with urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
except HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")
    print(f"Refresh failed: HTTP {exc.code}")
    print(f"Server response: {body[:300]}")
    raise SystemExit(1)
except URLError as exc:
    raise SystemExit(f"Cannot reach the portal: {exc.reason}")

access_token = data.get("access_token")
new_refresh_token = data.get("refresh_token")

if not access_token or not new_refresh_token:
    raise SystemExit("Response did not contain both expected tokens.")

Path("test_citizen_token.txt").write_text(access_token, encoding="utf-8")
refresh_path.write_text(new_refresh_token, encoding="utf-8")

print("Citizen token refresh: PASS")
print("New access and refresh tokens saved locally.")

