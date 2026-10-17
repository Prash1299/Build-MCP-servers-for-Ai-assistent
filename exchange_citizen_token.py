
import json
import os
import urllib.parse
import urllib.request
import urllib.error

with open("citizen_pkce.txt", "r") as f:
    verifier = f.read().strip()

data = urllib.parse.urlencode({
    "grant_type": "authorization_code",
    "client_id": "ssc_4Hd0xomwEFSEPOoa_tLOmQ",
    "redirect_uri": "http://localhost:8765/callback",
    "code": os.environ["AUTH_CODE"],
    "code_verifier": verifier,
}).encode()

request = urllib.request.Request(
    "http://localhost:8000/oauth/token",
    data=data,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

try:
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read())
        print("HTTP status:", response.status)
        print("Access token received:", bool(result.get("access_token")))
        print("Refresh token received:", bool(result.get("refresh_token")))

        if result.get("access_token"):
            with open("citizen_token.txt", "w") as f:
                f.write(result["access_token"])

        if result.get("refresh_token"):
            with open("citizen_refresh_token.txt", "w") as f:
                f.write(result["refresh_token"])

        if not result.get("access_token"):
            print("Error:", result.get("error", "unknown"))
            print("Description:", result.get("error_description", ""))

except urllib.error.HTTPError as error:
    print("HTTP status:", error.code)
    print("Response:", error.read().decode()[:500])
