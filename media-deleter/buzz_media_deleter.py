#!/usr/bin/env python3
"""buzz-media-deleter — minimal sidecar that deletes a buzz-media object by sha256.

Why this exists: the nostr.py bridge (AB-2) needs to delete an uploaded voice
note, but it runs inside a hardened tenant container that has no docker socket,
no `ssh`, and no MinIO credentials. This sidecar is the single narrow door:
one HTTP call on the tenant's own docker network, one sha256, one delete.

It talks S3 directly with stdlib SigV4 (hmac/hashlib) rather than shelling out
to `mc`. That avoids the two traps the AB-4 key-layout discovery found in the
shipped MinIO image: its baked `local` alias has empty credentials, and the
image is distroless (no grep/sed/awk to post-process `mc` output with).

Contract (the one line the bridge uses):

    POST http://buzz-media-deleter-<tenant>:8099/delete
         {"sha256": "<64-hex>", "ext": "<ext>"}
      -> 200 {"deleted": [...], "count": N, "verified": true}
      -> 404 {"missed": true}   when no key for that sha exists
      -> 400 malformed sha/ext, 401 missing/bad token, 500 storage error

The key set is derived by listing the bucket and matching the sha, not by
hard-coding `_meta/{community}/` — so it stays correct for a multi-community
future and for a new audio extension the sweep's regex would not know.
"""

import hashlib
import hmac
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXT_RE = re.compile(r"^[a-z0-9]{1,8}$")
S3_XMLNS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def _xml_tag(element):
    """Local name of an ElementTree tag, namespace or not.

    Real S3 responses carry the 2006-03-01 namespace; test doubles and some
    S3-compatible servers omit it. Strip whichever is present so one parser
    handles both.
    """
    return element.tag.rsplit("}", 1)[-1]


def _find_text(parent, name):
    for child in parent:
        if _xml_tag(child) == name:
            return child.text
    return None

DEFAULT_ENDPOINT = "http://minio:9000"
DEFAULT_BUCKET = "buzz-media"
DEFAULT_REGION = "us-east-1"
DEFAULT_PORT = 8099


class MediaError(Exception):
    """Base class for deleter failures."""


class MediaMissing(MediaError):
    """No object in the bucket carries the requested sha256."""


class StorageError(MediaError):
    """The object store rejected a call (creds, 5xx, transport)."""


class Config:
    def __init__(self, endpoint, access_key, secret_key, bucket, region, port, auth_token=""):
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self.port = port
        self.auth_token = auth_token

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        try:
            port = int(env.get("MD_LISTEN_PORT", DEFAULT_PORT))
        except (TypeError, ValueError):
            port = DEFAULT_PORT
        return cls(
            endpoint=env.get("MD_MINIO_ENDPOINT", DEFAULT_ENDPOINT),
            access_key=env.get("MD_MINIO_ACCESS_KEY", ""),
            secret_key=env.get("MD_MINIO_SECRET_KEY", ""),
            bucket=env.get("MD_MINIO_BUCKET", DEFAULT_BUCKET),
            region=env.get("MD_MINIO_REGION", DEFAULT_REGION),
            port=port,
            auth_token=env.get("MD_AUTH_TOKEN", ""),
        )


def _rfc3986(value):
    return urllib.parse.quote(str(value), safe="-_.~")


def encode_key(key):
    """Percent-encode a key's segments while keeping the '/' separators."""
    return "/".join(_rfc3986(segment) for segment in key.split("/"))


def _signing_key(secret_key, date, region, service):
    key = ("AWS4" + secret_key).encode()
    for message in (date, region, service, "aws4_request"):
        key = hmac.new(key, message.encode(), hashlib.sha256).digest()
    return key


def sign_request(
    method,
    host,
    path,
    query,
    headers,
    payload,
    access_key,
    secret_key,
    region,
    service,
    amz_date,
    sign_content_sha256=False,
):
    """Return headers with a SigV4 Authorization for the given request.

    ``sign_content_sha256`` adds ``x-amz-content-sha256`` to the signed header
    set. S3 wants it; the AWS-published iam vector (used to test this math) does
    not have it, so it is opt-in rather than unconditional.
    """
    payload_hash = hashlib.sha256(payload).hexdigest()
    signed = {k.lower(): v for k, v in headers.items()}
    signed["host"] = host
    signed["x-amz-date"] = amz_date
    if sign_content_sha256:
        signed["x-amz-content-sha256"] = payload_hash

    items = sorted((k, " ".join(str(v).split())) for k, v in signed.items())
    canonical_headers = "".join(f"{k}:{v}\n" for k, v in items)
    signed_headers = ";".join(k for k, _ in items)

    canonical_query = "&".join(
        f"{_rfc3986(k)}={_rfc3986(query[k])}" for k in sorted(query)
    )
    canonical_request = "\n".join(
        [method, path, canonical_query, canonical_headers, signed_headers, payload_hash]
    )

    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(secret_key, amz_date[:8], region, service),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    out = dict(signed)
    out["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return out


def matching_keys(keys, sha256):
    """Return the keys belonging to ``sha256`` from a bucket listing.

    Matches, at any depth:
      - the flat content-addressed blob ``{sha}.{ext}`` (and a bare ``{sha}``)
      - the tenant read-gate sidecar ``_meta/{community}/{sha}.json``
      - the image thumbnail ``{sha}.thumb.jpg`` (never exists for audio)
      - the per-upload records ``_uploads/{community}/{sha}/{ulid}.json``

    A key whose basename merely *starts with* the sha (e.g. ``{sha}deadbeef.mp3``)
    is deliberately not matched, so one delete cannot take a neighbour with it.
    """
    matched = []
    for key in keys:
        if key == sha256:
            matched.append(key)
            continue
        if key.startswith(f"_uploads/"):
            segments = key.split("/")
            if len(segments) >= 4 and segments[2] == sha256:
                matched.append(key)
            continue
        basename = key.rsplit("/", 1)[-1]
        if basename == sha256 or basename.startswith(f"{sha256}."):
            matched.append(key)
    return matched


class S3Client:
    def __init__(self, cfg):
        self.cfg = cfg
        parsed = urllib.parse.urlparse(cfg.endpoint)
        self.host = parsed.netloc
        self.scheme = parsed.scheme or "http"

    def _request(self, method, path, query, payload=b"", extra_headers=None):
        headers = sign_request(
            method=method,
            host=self.host,
            path=path,
            query=query,
            headers=extra_headers or {},
            payload=payload,
            access_key=self.cfg.access_key,
            secret_key=self.cfg.secret_key,
            region=self.cfg.region,
            service="s3",
            amz_date=_amz_date(),
            sign_content_sha256=True,
        )
        url = f"{self.scheme}://{self.host}{path}"
        if query:
            url += "?" + "&".join(
                f"{_rfc3986(k)}={_rfc3986(query[k])}" for k in sorted(query)
            )
        request = urllib.request.Request(url, data=payload or None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise StorageError(f"{method} {path} -> HTTP {exc.code}: {body[:200]!r}") from exc
        except urllib.error.URLError as exc:
            raise StorageError(f"{method} {path} -> transport error: {exc.reason}") from exc

    def list_keys(self):
        """Every key in the bucket, following ListObjectsV2 continuation tokens."""
        keys = []
        token = None
        while True:
            query = {"list-type": "2"}
            if token:
                query["continuation-token"] = token
            status, body = self._request("GET", f"/{self.cfg.bucket}", query)
            if status != 200:
                raise StorageError(f"list -> HTTP {status}")
            root = ET.fromstring(body)
            for contents in root.iter():
                if _xml_tag(contents) != "Contents":
                    continue
                key = _find_text(contents, "Key")
                if key:
                    keys.append(key)
            if _find_text(root, "IsTruncated") != "true":
                return keys
            token = _find_text(root, "NextContinuationToken")
            if not token:
                return keys

    def delete_key(self, key):
        status, _ = self._request("DELETE", f"/{self.cfg.bucket}/{encode_key(key)}", {})
        if status not in (200, 202, 204):
            raise StorageError(f"delete {key} -> HTTP {status}")


def _amz_date():
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def delete_media(cfg, sha256, ext):
    """Delete every key for ``sha256`` and confirm the bucket is clean.

    Returns {"deleted": [...], "count": N, "verified": bool}.
    Raises MediaMissing when nothing matched, StorageError on a store failure.
    """
    if not SHA256_RE.match(sha256 or ""):
        raise MediaError("sha256 must be 64 lowercase hex characters")
    if not EXT_RE.match(ext or ""):
        raise MediaError("ext must be 1-8 lowercase alphanumeric characters")

    client = S3Client(cfg)
    targets = matching_keys(client.list_keys(), sha256)
    if not targets:
        raise MediaMissing(f"no keys for {sha256}")

    for key in targets:
        client.delete_key(key)

    remaining = matching_keys(client.list_keys(), sha256)
    return {
        "deleted": targets,
        "count": len(targets),
        "verified": not remaining,
        "remaining": remaining,
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "buzz-media-deleter/1"

    def log_message(self, format, *args):
        sys.stderr.write("buzz-media-deleter: " + format % args + "\n")

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        token = self.server.cfg.auth_token
        if not token:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {token}"

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/healthz":
            return self._send(200, {"status": "ok"})
        if path == "/delete":
            return self._send(405, {"error": "method not allowed"})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/delete":
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return self._send(401, {"error": "unauthorized"})

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad content-length"})
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "invalid json"})
        if not isinstance(payload, dict):
            return self._send(400, {"error": "body must be a json object"})

        sha256 = payload.get("sha256")
        ext = payload.get("ext")
        if not isinstance(sha256, str) or not SHA256_RE.match(sha256):
            return self._send(400, {"error": "sha256 must be 64 lowercase hex characters"})
        if not isinstance(ext, str) or not EXT_RE.match(ext):
            return self._send(400, {"error": "ext must be 1-8 lowercase alphanumeric characters"})

        try:
            result = delete_media(self.server.cfg, sha256, ext)
        except MediaMissing as exc:
            return self._send(404, {"missed": True, "sha256": sha256, "error": str(exc)})
        except StorageError as exc:
            return self._send(500, {"error": str(exc)})
        except MediaError as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, result)


class DeleterServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the resolved config for its handler."""

    daemon_threads = True

    def __init__(self, address, handler, cfg):
        super().__init__(address, handler)
        self.cfg = cfg


def build_server(cfg, host="0.0.0.0", port=None):
    return DeleterServer((host, cfg.port if port is None else port), _Handler, cfg)


def main():
    cfg = Config.from_env()
    if not cfg.access_key or not cfg.secret_key:
        sys.stderr.write("buzz-media-deleter: MD_MINIO_ACCESS_KEY / MD_MINIO_SECRET_KEY are required\n")
        return 2
    httpd = build_server(cfg)
    sys.stderr.write(
        f"buzz-media-deleter: listening on 0.0.0.0:{cfg.port} "
        f"bucket={cfg.bucket} endpoint={cfg.endpoint} auth={'on' if cfg.auth_token else 'off'}\n"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
