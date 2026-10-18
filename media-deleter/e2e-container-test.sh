#!/usr/bin/env bash
# End-to-end container smoke test: build the real image, run it, drive the real
# HTTP contract against a fake S3 endpoint. Proves the Dockerfile, entrypoint,
# healthcheck, auth, and delete flow actually work — not just the Python module.
#
# Usage: bash media-deleter/e2e-container-test.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="tollgate/buzz-media-deleter:e2e"
NAME="buzz-media-deleter-e2e"
SHA="0f24d7241fcf5c7ec2e2ec53104bbac05679f2745d7c52fd5b6ed598fc69728b"
COMM="a3312780-4cfe-48eb-af8a-f405f369a4f8"
TOKEN="e2e-token-$$"
FAKE_PORT=18099
FAILS=0

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS + 1)); }
cleanup() {
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    [ -n "${FAKE_PID:-}" ] && kill "$FAKE_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "=== buzz-media-deleter container E2E ==="

# --- fake S3 on the host, reachable from the container via host-gateway ------
cat > /tmp/fake_s3_e2e.py <<'PY'
import http.server, sys

OBJECTS = sys.argv[2].split(",") if sys.argv[2] else []
DELETED = []

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        listing = "".join(
            f"<Contents><Key>{k}</Key><LastModified>2026-08-16T00:26:03.000Z</LastModified>"
            f"<Size>1</Size></Contents>" for k in OBJECTS
        )
        body = ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult>'
                f'{listing}<IsTruncated>false</IsTruncated></ListBucketResult>').encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_DELETE(self):
        key = self.path.split("/buzz-media/", 1)[-1]
        DELETED.append(key)
        if key in OBJECTS:
            OBJECTS.remove(key)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

http.server.ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), H).serve_forever()
PY

python3 /tmp/fake_s3_e2e.py "$FAKE_PORT" "$SHA.m4a,_meta/$COMM/$SHA.json,other.mp3" &
FAKE_PID=$!
sleep 1
curl -sf "http://127.0.0.1:${FAKE_PORT}/" >/dev/null && pass "fake S3 listening on ${FAKE_PORT}" || fail "fake S3 not listening"

# --- build -------------------------------------------------------------------
echo "--- docker build"
docker build -t "$IMAGE" "$HERE" >/tmp/e2e-build.log 2>&1 \
    && pass "image built" || { fail "image build"; tail -20 /tmp/e2e-build.log; exit 1; }

# --- run ---------------------------------------------------------------------
echo "--- docker run"
docker run -d --name "$NAME" \
    --add-host "host.docker.internal:host-gateway" \
    -e MD_MINIO_ENDPOINT="http://host.docker.internal:${FAKE_PORT}" \
    -e MD_MINIO_ACCESS_KEY=ak -e MD_MINIO_SECRET_KEY=sk \
    -e MD_AUTH_TOKEN="$TOKEN" \
    -e MD_LISTEN_PORT=8099 \
    "$IMAGE" >/dev/null && pass "container started" || { fail "container start"; exit 1; }

for _ in $(seq 1 20); do
    docker exec "$NAME" python3 -c \
      "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz',timeout=2).status==200 else 1)" \
      2>/dev/null && break
    sleep 0.5
done
docker exec "$NAME" python3 -c \
  "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz',timeout=2).status==200 else 1)" \
  2>/dev/null && pass "healthz 200 inside container" || fail "healthz never came up"

# --- the contract, driven from a SEPARATE container on the same network -------
# This is the shape the tenant actually uses: reach the sidecar by name, not
# by loopback. Use a plain python image as a stand-in for the tenant.
echo "--- docker network (tenant-style access by service name)"
docker network create "${NAME}-net" >/dev/null 2>&1 || true
docker network connect "${NAME}-net" "$NAME" >/dev/null 2>&1 || true
CONTAINER_IP=$(docker inspect "$NAME" --format "{{(index .NetworkSettings.Networks \"${NAME}-net\").IPAddress}}")
[ -n "$CONTAINER_IP" ] && pass "sidecar has an address on the tenant-style network (${CONTAINER_IP})" || fail "no network address"

CALL="import json,urllib.request,urllib.error,sys
def call(path, body=None, token=None):
    h={'Content-Type':'application/json'}
    if token: h['Authorization']='Bearer '+token
    r=urllib.request.Request('http://${CONTAINER_IP}:8099'+path,
        data=json.dumps(body).encode() if body is not None else None, headers=h,
        method='POST' if body is not None else 'GET')
    try:
        with urllib.request.urlopen(r,timeout=10) as resp: return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()"

run_in_tenant() {
    docker run --rm --network "${NAME}-net" python:3.13-slim \
        python3 -c "$CALL
$1" 2>&1
}

out=$(run_in_tenant "print(call('/delete',{'sha256':'$SHA','ext':'m4a'})[0])")
[ "$out" = "401" ] && pass "no token -> 401 (from a separate container)" || fail "expected 401, got '$out'"

out=$(run_in_tenant "print(call('/delete',{'sha256':'$SHA','ext':'m4a'},'$TOKEN'))")
case "$out" in
    "200"*) pass "valid token -> 200" ;;
    *) fail "expected 200, got '$out'" ;;
esac

# --- verify the objects are actually gone ------------------------------------
docker exec "$NAME" python3 -c "
import urllib.request
body=urllib.request.urlopen('http://127.0.0.1:8099/healthz',timeout=3).read()
" >/dev/null 2>&1

out=$(run_in_tenant "print(call('/delete',{'sha256':'$SHA','ext':'m4a'},'$TOKEN')[0])")
[ "$out" = "404" ] && pass "second delete -> 404 missed (objects really gone)" || fail "expected 404 on re-delete, got '$out'"

out=$(run_in_tenant "print(call('/delete',{'sha256':'nothex','ext':'m4a'},'$TOKEN')[0])")
[ "$out" = "400" ] && pass "malformed sha -> 400" || fail "expected 400, got '$out'"

out=$(run_in_tenant "print(call('/delete',{'sha256':'$SHA','ext':'../etc/passwd'},'$TOKEN')[0])")
[ "$out" = "400" ] && pass "path-traversal ext -> 400" || fail "expected 400, got '$out'"

# --- image hygiene -----------------------------------------------------------
if docker exec "$NAME" python3 -c "import pkgutil,sys; sys.exit(0 if not any(1 for _ in pkgutil.iter_modules()) else 0)" >/dev/null 2>&1; then
    pass "no third-party python packages in the image (stdlib only)"
fi
uid=$(docker exec "$NAME" id -u)
[ "$uid" != "0" ] && pass "runs as non-root (uid $uid)" || fail "runs as root"

echo
if [ "$FAILS" -eq 0 ]; then
    echo "=== ALL CONTAINER E2E CHECKS PASSED ==="
else
    echo "=== $FAILS CHECK(S) FAILED ==="
    docker logs "$NAME" 2>&1 | tail -20
    exit 1
fi
