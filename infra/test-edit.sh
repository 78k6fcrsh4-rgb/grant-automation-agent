#!/usr/bin/env bash
# End-to-end exercise of the review-and-correct path with no browser:
# log in, upload, read back, PATCH a field, read back again.
#
#   ./infra/test-edit.sh
#
# If this passes, the backend is fine and the problem is in the frontend.
# If it fails, the response body says why.

set -uo pipefail
API="${API:-http://localhost:8000}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV="$REPO/backend/.env"
PDF="${1:-$REPO/sample-award-letter.pdf}"

EMAIL="$(grep '^SEED_ADMIN_EMAIL=' "$ENV" | cut -d= -f2-)"
PASS="$(grep '^SEED_ADMIN_PASSWORD=' "$ENV" | cut -d= -f2-)"
PY="$REPO/backend/.venv/bin/python3"; [ -x "$PY" ] || PY=python3

say()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }

say "1. Log in as $EMAIL"
LOGIN="$(curl -s -m 15 -X POST "$API/api/auth/login" \
   -H 'Content-Type: application/json' \
   -d "$("$PY" -c '
import json,sys; print(json.dumps({"email":sys.argv[1],"password":sys.argv[2]}))' "$EMAIL" "$PASS")")"
TOKEN="$("$PY" -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' <<<"$LOGIN")"
if [ -z "$TOKEN" ]; then fail "no token. Response:"; echo "    $LOGIN"; exit 1; fi
ok "token received"

say "2. Upload $(basename "$PDF")"
[ -f "$PDF" ] || { fail "no such file: $PDF"; exit 1; }
UP="$(curl -s -m 120 -X POST "$API/api/grants/upload-package" \
   -H "Authorization: Bearer $TOKEN" -F "award_letter=@$PDF")"
FID="$("$PY" -c 'import json,sys; print(json.load(sys.stdin).get("package_id",""))' <<<"$UP" 2>/dev/null)"
if [ -z "$FID" ]; then fail "no package_id. Response:"; echo "    ${UP:0:400}"; exit 1; fi
ok "package_id $FID"

say "3. Read the extracted record"
BEFORE="$(curl -s -m 15 "$API/api/grants/data/$FID" -H "Authorization: Bearer $TOKEN")"
"$PY" - <<'PY' <<<"$BEFORE"
import json,sys
d = json.load(sys.stdin)
print("     grant_amount     :", d.get("grant_amount"))
print("     grant_title      :", d.get("grant_title"))
print("     confidence       :", d.get("extraction_confidence"))
PY

say "4. PATCH grant_amount to 133600"
CODE="$(curl -s -o /tmp/patch_body.json -w '%{http_code}' -m 15 -X PATCH \
   "$API/api/grants/data/$FID" -H "Authorization: Bearer $TOKEN" \
   -H 'Content-Type: application/json' -d '{"grant_amount": 133600}')"
echo "     HTTP $CODE"
if [ "$CODE" != "200" ]; then
    fail "the edit was rejected. Response body:"
    sed 's/^/     /' /tmp/patch_body.json; echo
    exit 1
fi
ok "accepted"

say "5. Read it back — did the edit stick?"
AFTER="$(curl -s -m 15 "$API/api/grants/data/$FID" -H "Authorization: Bearer $TOKEN")"
"$PY" - <<'PY' <<<"$AFTER"
import json,sys
d = json.load(sys.stdin)
amt = d.get("grant_amount")
conf = (d.get("extraction_confidence") or {}).get("grant_amount")
print("     grant_amount     :", amt)
print("     confidence       :", conf)
print()
if amt == 133600:
    print("  \033[32mBACKEND IS FINE\033[0m — the edit persisted. The problem is in the frontend.")
else:
    print("  \033[31mBACKEND PROBLEM\033[0m — PATCH returned 200 but the value did not change.")
PY
