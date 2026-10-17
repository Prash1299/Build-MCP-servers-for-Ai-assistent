
import os
import jwt
from datetime import datetime, timezone

for name in ("CITIZEN_TOKEN", "OFFICER_TOKEN"):
    token = os.environ.get(name, "")
    print(f"\n{name}:")

    if not token:
        print("MISSING")
        continue

    try:
        claims = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
        print("Role:", claims.get("role"))
        print("Scope:", claims.get("scope"))
        exp = claims.get("exp")
        if exp:
            expiry = datetime.fromtimestamp(exp, timezone.utc)
            print("Expired:", expiry <= datetime.now(timezone.utc))
        else:
            print("Expiry: missing")
    except Exception as exc:
        print("Could not decode token:", type(exc).__name__)
