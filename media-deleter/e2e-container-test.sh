#!/usr/bin/env bash
# End-to-end container smoke test: build the real image, run it, drive the real
# HTTP contract from a SEPARATE container on the same docker network.
#
# Proves the Dockerfile, entrypoint, healthcheck, bearer auth, and the
# delete/verify/miss flow actually work as a deployed artifact — not just the
# Python module (that is tests/test_buzz_media_deleter.py).
#
# Everything runs inside docker networks: no host ports, no host backgrounding,
# no reliance on the host's ability to reach container IPs. The fake S3 runs as
# a container too, so the whole topology mirrors production.
#
# Usage: bash media-deleter/e2e-container-test.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="tollgate/buzz-media-deleter:e2e"
NAME="buzz-media-deleter-e2e"
FAKE="buzz-media-deleter-e2e-fakes3"
NET="${NAME}-net"
SHA="0f24d7241fcf5c7ec2e2ec53104bbac05679f2745d7c52fd5b6ed598fc69728b"
COMM="a3312780-4cfe-48eb-af8a-f405f369a4f8"
TOKEN="e2e-token-$$"
FAILS=0

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS + 1)); }

cleanup() {
    docker rm -f "$NAME" "$FAKE" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Clear anything an interrupted previous run left behind.
docker rm -f "$NAME" "$FAKE" >/dev/null 2>&1 || true
docker network rm "$NET" >/dev/null 2>&1 || true

echo "=== buzz-media-deleter container E2E ==="

docker network create "$NET" >/dev/null
pass "created isolated network ${NET}"

# --- build -------------------------------------------------------------------
echo "--- docker build"
if docker build -t "$IMAGE" "$HERE" >/tmp/e2e-build.log 2>&1; then
    pass "image built"
else
    fail "image build"
    tail -20 /tmp/e2e-build.log
    exit 1
fi

# --- fake S3, also a container on the same network ---------------------------
echo "--- fake S3"
docker run -d --name "$FAKE" --network "$NET" --network-alias fakes3 \
    -v "${HERE}/tests/fake_s3.py:/fake_s3.py:ro" \
    --entrypoint python3 "$IMAGE" \
    /fake_s3.py 9000 "${SHA}.m4a,_meta/${COMM}/${SHA}.json,untouched.mp3" >/dev/null
pass "fake S3 container started (alias fakes3)"

# --- sidecar under test ------------------------------------------------------
echo "--- sidecar"
docker run -d --name "$NAME" --network "$NET" \
    -e MD_MINIO_ENDPOINT=http://fakes3:9000 \
    -e MD_MINIO_ACCESS_KEY=ak -e MD_MINIO_SECRET_KEY=sk \
    -e MD_AUTH_TOKEN="$TOKEN" \
    -e MD_LISTEN_PORT=8099 \
    "$IMAGE" >/dev/null
pass "sidecar container started"

for _ in $(seq 1 30); do
    docker exec "$NAME" python3 -c \
      "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz',timeout=2).status==200 else 1)" \
      2>/dev/null && break
    sleep 0.5
done
if docker exec "$NAME" python3 -c \
    "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8099/healthz',timeout=2).status==200 else 1)" 2>/dev/null; then
    pass "healthz 200 inside the sidecar"
else
    fail "healthz never came up"
    docker logs "$NAME" 2>&1 | tail -20
fi

# --- the contract, driven from a SEPARATE container by service name ----------
# This is the tenant's view: reach the sidecar by name over the docker network,
# exactly as the nostr.py bridge will.
echo "--- contract (from a separate container, by service name)"
CALL='import json,urllib.request,urllib.error
def call(path, body=None, token=None):
    h={"Content-Type":"application/json"}
    if token: h["Authorization"]="Bearer "+token
    r=urllib.request.Request("http://buzz-media-deleter-e2e:8099"+path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(r,timeout=10) as resp: return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()'

client() {
    # Detached run + `docker wait`, NOT attached `docker run`: on this host an
    # attached run whose stdout is redirected prints its output and then hangs
    # for ~2 minutes before returning (reproduced with plain python:3.13-slim, so
    # it is a host/docker quirk, not this image). Detached + wait is reliable.
    local cname="${NAME}-client-$$-$RANDOM"
    docker run -d --name "$cname" --pull=never --network "$NET" \
        --entrypoint python3 "$IMAGE" -c "$CALL
$1" >/dev/null 2>&1
    local rc
    rc=$(timeout 60 docker wait "$cname" 2>/dev/null || echo "timeout")
    local out
    out=$(docker logs "$cname" 2>&1 || true)
    docker rm -f "$cname" >/dev/null 2>&1 || true
    if [ "$rc" = "timeout" ]; then
        echo "CLIENT-TIMEOUT"
    else
        echo "$out"
    fi
}

out=$(client "print(call('/healthz')[0])")
[ "$out" = "200" ] && pass "healthz 200 from a separate container (by service name)" \
                   || fail "healthz from separate container: '$out'"

out=$(client "print(call('/delete',{'sha256':'$SHA','ext':'m4a'})[0])")
[ "$out" = "401" ] && pass "no token -> 401" || fail "expected 401, got '$out'"

out=$(client "print(call('/delete',{'sha256':'$SHA','ext':'m4a'},'wrong-token')[0])")
[ "$out" = "401" ] && pass "wrong token -> 401" || fail "expected 401, got '$out'"

out=$(client "print(call('/delete',{'sha256':'$SHA','ext':'m4a'},'$TOKEN'))")
case "$out" in
    "(200,"*) pass "valid token -> 200 $out" ;;
    *) fail "expected 200, got '$out'" ;;
esac

out=$(client "print(call('/delete',{'sha256':'$SHA','ext':'m4a'},'$TOKEN')[0])")
[ "$out" = "404" ] && pass "re-delete -> 404 (objects really gone, not just acked)" \
                   || fail "expected 404 on re-delete, got '$out'"

out=$(client "print(call('/delete',{'sha256':'nothex','ext':'m4a'},'$TOKEN')[0])")
[ "$out" = "400" ] && pass "malformed sha -> 400" || fail "expected 400, got '$out'"

out=$(client "print(call('/delete',{'sha256':'$SHA','ext':'../etc/passwd'},'$TOKEN')[0])")
[ "$out" = "400" ] && pass "path-traversal ext -> 400" || fail "expected 400, got '$out'"

out=$(client "print(call('/nope')[0])")
[ "$out" = "404" ] && pass "unknown path -> 404" || fail "expected 404, got '$out'"

# --- assert exactly which keys the store was asked to remove ------------------
# The fake S3 logs every DELETE it receives, so this is a real assertion about
# the wire traffic rather than a restatement of the response body.
echo "--- wire-level delete assertions"
deleted_keys=$(docker logs "$FAKE" 2>&1 | grep '^DELETED ' | sed 's/^DELETED //' | sort)
expected=$(printf '%s\n%s\n' "${SHA}.m4a" "_meta/${COMM}/${SHA}.json" | sort)
if [ "$deleted_keys" = "$expected" ]; then
    pass "exactly the blob + sidecar were deleted (no neighbour touched)"
else
    fail "unexpected delete set"
    echo "     got:      $(echo "$deleted_keys" | tr '\n' ' ')"
    echo "     expected: $(echo "$expected" | tr '\n' ' ')"
fi
if echo "$deleted_keys" | grep -q 'untouched.mp3'; then
    fail "a neighbour object was deleted"
else
    pass "neighbour object untouched.mp3 was never deleted"
fi

# --- image hygiene -----------------------------------------------------------
echo "--- image hygiene"
uid=$(docker exec "$NAME" id -u)
[ "$uid" != "0" ] && pass "runs as non-root (uid $uid)" || fail "runs as root"

if docker exec "$NAME" sh -c 'ls /app' >/dev/null 2>&1; then
    pass "image has an expected /app layout"
fi

echo
if [ "$FAILS" -eq 0 ]; then
    echo "=== ALL CONTAINER E2E CHECKS PASSED ==="
else
    echo "=== $FAILS CHECK(S) FAILED ==="
    docker logs "$NAME" 2>&1 | tail -20
    exit 1
fi
