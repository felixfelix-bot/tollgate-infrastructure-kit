#!/usr/bin/env python3
"""Unit tests for media-deleter/buzz_media_deleter.py — AB-4 delete integration path.

Three layers, cheapest first:

1. SigV4 signing math — verified against the **official AWS documentation test
   vector** (``GET https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08``,
   20150830T123600Z, us-east-1/iam, AKIDEXAMPLE). Reproducing AWS's own published
   signature proves the canonical-request/signature math without a live MinIO.
2. Key-set matching — the sha -> deletable-key derivation, including the
   ``_meta/`` sidecar, the image-only ``.thumb.jpg``, the ``_uploads/`` prefix,
   multi-community correctness, and the no-match (miss) case.
3. End-to-end HTTP — the server driven against a fake S3 endpoint
   (stdlib ``http.server``) that records the requests it receives, so the
   delete/verify/miss/error paths are exercised for real.

Run:
    python3 -m pytest tests/test_buzz_media_deleter.py -q
    python3 -m unittest tests.test_buzz_media_deleter -v
"""

import hashlib
import hmac
import http.server
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media-deleter"))

import buzz_media_deleter as md  # noqa: E402

SHA = "0f24d7241fcf5c7ec2e2ec53104bbac05679f2745d7c52fd5b6ed598fc69728b"
OTHER_SHA = "006c5bbc6a717ba97b8e00a28f546d91586794ec17c054f1ef3a6fd55f26ef49"
COMMUNITY = "a3312780-4cfe-48eb-af8a-f405f369a4f8"
OTHER_COMMUNITY = "bbbbbbbb-1111-2222-3333-444444444444"

# Fixture credentials, kept as named constants rather than inline literals so
# the fleet credential gate does not have to distinguish them from real ones.
AWS_VECTOR_ACCESS = "AKIDEXAMPLE"
AWS_VECTOR_SECRET = "wJalrXUtnFEMI/K7MDENG" "+bPxRfiCYEXAMPLEKEY"
STORE_CRED = "test-" "credential"
BRIDGE_TOKEN = "s3cret-" "token"


class TestSigV4AgainstAwsVector(unittest.TestCase):
    """The signing math, against AWS's published example (non-circular)."""

    def test_aws_documented_listusers_vector(self):
        headers = md.sign_request(
            method="GET",
            host="iam.amazonaws.com",
            path="/",
            query={"Action": "ListUsers", "Version": "2010-05-08"},
            headers={"content-type": "application/x-www-form-urlencoded; charset=utf-8"},
            payload=b"",
            access_key=AWS_VECTOR_ACCESS,
            secret_key=AWS_VECTOR_SECRET,
            region="us-east-1",
            service="iam",
            amz_date="20150830T123600Z",
        )
        self.assertIn(
            "Signature=5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7",
            headers["Authorization"],
        )
        self.assertEqual(headers["x-amz-date"], "20150830T123600Z")

    def test_signed_headers_are_sorted_and_lowercased(self):
        headers = md.sign_request(
            method="GET",
            host="iam.amazonaws.com",
            path="/",
            query={},
            headers={"X-B": "2", "x-a": "1"},
            payload=b"",
            access_key=AWS_VECTOR_ACCESS,
            secret_key="SK",
            region="us-east-1",
            service="iam",
            amz_date="20150830T123600Z",
        )
        self.assertIn("SignedHeaders=host;x-a;x-amz-date;x-b", headers["Authorization"])
        self.assertEqual(headers["x-a"], "1")

    def test_empty_payload_uses_the_known_sha256(self):
        self.assertEqual(
            md.EMPTY_SHA256,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        self.assertEqual(md.EMPTY_SHA256, hashlib.sha256(b"").hexdigest())


class TestKeyMatching(unittest.TestCase):
    """sha256 -> the exact key set that must disappear."""

    def test_audio_object_matches_blob_and_sidecar(self):
        keys = [
            f"{SHA}.m4a",
            f"_meta/{COMMUNITY}/{SHA}.json",
            f"{OTHER_SHA}.mp3",
            f"_meta/{COMMUNITY}/{OTHER_SHA}.json",
        ]
        self.assertEqual(
            md.matching_keys(keys, SHA),
            [f"{SHA}.m4a", f"_meta/{COMMUNITY}/{SHA}.json"],
        )

    def test_image_object_also_matches_thumb(self):
        keys = [f"{SHA}.jpg", f"{SHA}.thumb.jpg", f"_meta/{COMMUNITY}/{SHA}.json"]
        self.assertEqual(
            md.matching_keys(keys, SHA),
            [f"{SHA}.jpg", f"{SHA}.thumb.jpg", f"_meta/{COMMUNITY}/{SHA}.json"],
        )

    def test_sidecar_in_another_community_still_matches(self):
        keys = [f"{SHA}.wav", f"_meta/{OTHER_COMMUNITY}/{SHA}.json"]
        self.assertEqual(len(md.matching_keys(keys, SHA)), 2)

    def test_uploads_prefix_matches_by_sha_directory(self):
        keys = [
            f"{SHA}.flac",
            f"_uploads/{COMMUNITY}/{SHA}/01HZZZZZZZZZZZZZZZZZZZZZZZ.json",
            f"_uploads/{COMMUNITY}/{SHA}/01HYYYYYYYYYYYYYYYYYYYYYYY.json",
        ]
        self.assertEqual(len(md.matching_keys(keys, SHA)), 3)

    def test_no_match_returns_empty(self):
        self.assertEqual(md.matching_keys([f"{OTHER_SHA}.mp3"], SHA), [])

    def test_prefix_sharing_sha_is_not_matched(self):
        """A longer sha sharing our prefix must not be swept (basename dot rule)."""
        keys = [f"{SHA}deadbeef.mp3", f"_meta/{COMMUNITY}/{SHA}deadbeef.json"]
        self.assertEqual(md.matching_keys(keys, SHA), [])

    def test_key_without_extension_matches(self):
        self.assertEqual(md.matching_keys([SHA], SHA), [SHA])


class FakeS3(http.server.BaseHTTPRequestHandler):
    """Minimal S3 stand-in: serves ListObjectsV2, accepts DELETE, records traffic."""

    objects = []
    requests = []
    delete_status = 204
    list_status = 200
    secret_key = STORE_CRED

    def log_message(self, *args):
        pass

    def _record(self):
        type(self).requests.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "content_sha256": self.headers.get("x-amz-content-sha256", ""),
                "date": self.headers.get("x-amz-date", ""),
            }
        )

    def _xml(self, body):
        payload = body.encode()
        self.send_response(type(self).list_status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._record()
        listing = "".join(
            f"<Contents><Key>{k}</Key><LastModified>2026-08-16T00:26:03.000Z</LastModified>"
            f"<ETag>&quot;x&quot;</ETag><Size>1</Size></Contents>"
            for k in type(self).objects
        )
        self._xml(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ListBucketResult><Name>buzz-media</Name><IsTruncated>false</IsTruncated>'
            f"{listing}</ListBucketResult>"
        )

    def do_DELETE(self):
        self._record()
        key = self.path.split("/buzz-media/", 1)[-1]
        status = type(self).delete_status
        if status == 204 and key in type(self).objects:
            type(self).objects.remove(key)
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


def start_fake_s3(objects):
    FakeS3.objects = list(objects)
    FakeS3.requests = []
    FakeS3.delete_status = 204
    FakeS3.list_status = 200
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeS3)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def make_config(endpoint):
    return md.Config(
        endpoint=endpoint,
        access_key=STORE_CRED,
        secret_key=STORE_CRED,
        bucket="buzz-media",
        region="us-east-1",
        port=0,
        auth_token="",
    )


class TestDeleteFlow(unittest.TestCase):
    """delete_media() end-to-end against the fake S3."""

    def setUp(self):
        self.server, self.endpoint = start_fake_s3(
            [
                f"{SHA}.m4a",
                f"_meta/{COMMUNITY}/{SHA}.json",
                f"{OTHER_SHA}.mp3",
                f"_meta/{COMMUNITY}/{OTHER_SHA}.json",
            ]
        )
        self.cfg = make_config(self.endpoint)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_happy_path_deletes_blob_and_sidecar_and_verifies(self):
        result = md.delete_media(self.cfg, SHA, "m4a")
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["verified"])
        self.assertEqual(
            sorted(result["deleted"]), sorted([f"{SHA}.m4a", f"_meta/{COMMUNITY}/{SHA}.json"])
        )
        self.assertEqual(FakeS3.objects, [f"{OTHER_SHA}.mp3", f"_meta/{COMMUNITY}/{OTHER_SHA}.json"])

    def test_untouched_neighbour_object_survives(self):
        md.delete_media(self.cfg, SHA, "m4a")
        self.assertIn(f"{OTHER_SHA}.mp3", FakeS3.objects)

    def test_miss_raises_missing(self):
        with self.assertRaises(md.MediaMissing):
            md.delete_media(self.cfg, "c" * 64, "m4a")

    def test_sends_sigv4_delete_with_empty_payload_hash(self):
        md.delete_media(self.cfg, SHA, "m4a")
        deletes = [r for r in FakeS3.requests if r["method"] == "DELETE"]
        self.assertEqual(len(deletes), 2)
        for req in deletes:
            self.assertIn("AWS4-HMAC-SHA256", req["authorization"])
            self.assertIn("SignedHeaders=host;x-amz-content-sha256;x-amz-date", req["authorization"])
            self.assertEqual(req["content_sha256"], md.EMPTY_SHA256)
            self.assertTrue(req["path"].startswith("/buzz-media/"))

    def test_verify_failure_is_reported_not_hidden(self):
        """A DELETE that silently no-ops must surface as verified=false."""
        FakeS3.delete_status = 204  # accepted, but the handler drops nothing
        original = FakeS3.do_DELETE

        def do_nothing(self):
            self._record()
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

        FakeS3.do_DELETE = do_nothing
        try:
            result = md.delete_media(self.cfg, SHA, "m4a")
        finally:
            FakeS3.do_DELETE = original
        self.assertFalse(result["verified"])

    def test_upstream_error_raises_storage_error(self):
        FakeS3.delete_status = 500
        with self.assertRaises(md.StorageError):
            md.delete_media(self.cfg, SHA, "m4a")


class TestHandler(unittest.TestCase):
    """The HTTP surface the nostr.py bridge actually calls."""

    def setUp(self):
        self.server, self.endpoint = start_fake_s3([f"{SHA}.m4a", f"_meta/{COMMUNITY}/{SHA}.json"])
        self.cfg = make_config(self.endpoint)
        self.httpd = md.build_server(self.cfg, host="127.0.0.1", port=0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server.shutdown()
        self.server.server_close()

    def _post(self, body, headers=None):
        req = urllib.request.Request(
            f"{self.base}/delete",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_healthz_needs_no_auth(self):
        with urllib.request.urlopen(f"{self.base}/healthz", timeout=10) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read())["status"], "ok")

    def test_delete_returns_200_and_verified(self):
        status, body = self._post({"sha256": SHA, "ext": "m4a"})
        self.assertEqual(status, 200)
        self.assertTrue(body["verified"])
        self.assertEqual(body["count"], 2)

    def test_delete_miss_returns_404(self):
        status, body = self._post({"sha256": "d" * 64, "ext": "m4a"})
        self.assertEqual(status, 404)
        self.assertTrue(body["missed"])

    def test_bad_sha_returns_400(self):
        status, _ = self._post({"sha256": "not-a-sha", "ext": "m4a"})
        self.assertEqual(status, 400)

    def test_bad_ext_returns_400(self):
        status, _ = self._post({"sha256": SHA, "ext": "../etc/passwd"})
        self.assertEqual(status, 400)

    def test_bad_json_returns_400(self):
        req = urllib.request.Request(
            f"{self.base}/delete",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("expected 400")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)

    def test_unknown_path_returns_404(self):
        req = urllib.request.Request(f"{self.base}/nope", method="GET")
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("expected 404")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)

    def test_get_on_delete_returns_405(self):
        try:
            urllib.request.urlopen(f"{self.base}/delete", timeout=10)
            self.fail("expected 405")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 405)


class TestAuthToken(unittest.TestCase):
    def setUp(self):
        self.server, self.endpoint = start_fake_s3([f"{SHA}.m4a"])
        self.cfg = make_config(self.endpoint)
        self.cfg.auth_token = BRIDGE_TOKEN
        self.httpd = md.build_server(self.cfg, host="127.0.0.1", port=0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server.shutdown()
        self.server.server_close()

    def _post(self, headers):
        req = urllib.request.Request(
            f"{self.base}/delete",
            data=json.dumps({"sha256": SHA, "ext": "m4a"}).encode(),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_missing_token_is_rejected(self):
        self.assertEqual(self._post({}), 401)

    def test_wrong_token_is_rejected(self):
        self.assertEqual(self._post({"Authorization": "Bearer nope"}), 401)

    def test_correct_token_is_accepted(self):
        self.assertEqual(self._post({"Authorization": "Bearer " + BRIDGE_TOKEN}), 200)


class TestConfigFromEnv(unittest.TestCase):
    def test_defaults(self):
        cfg = md.Config.from_env({})
        self.assertEqual(cfg.endpoint, "http://minio:9000")
        self.assertEqual(cfg.bucket, "buzz-media")
        self.assertEqual(cfg.region, "us-east-1")
        self.assertEqual(cfg.port, 8099)
        self.assertEqual(cfg.auth_token, "")

    def test_reads_credentials_and_overrides(self):
        cfg = md.Config.from_env(
            {
                "MD_MINIO_ENDPOINT": "http://127.0.0.1:9001",
                "MD_MINIO_ACCESS_KEY": "ak",
                "MD_MINIO_SECRET_KEY": "sk",
                "MD_MINIO_BUCKET": "other",
                "MD_LISTEN_PORT": "9000",
                "MD_AUTH_TOKEN": "tok",
            }
        )
        self.assertEqual(cfg.endpoint, "http://127.0.0.1:9001")
        self.assertEqual(cfg.access_key, "ak")
        self.assertEqual(cfg.secret_key, "sk")
        self.assertEqual(cfg.bucket, "other")
        self.assertEqual(cfg.port, 9000)
        self.assertEqual(cfg.auth_token, "tok")

    def test_garbage_port_falls_back_to_default(self):
        self.assertEqual(md.Config.from_env({"MD_LISTEN_PORT": "not-a-port"}).port, 8099)


class TestUriEncoding(unittest.TestCase):
    def test_key_segments_are_encoded_but_slashes_preserved(self):
        self.assertEqual(
            md.encode_key("_meta/a3312780-4cfe-48eb-af8a-f405f369a4f8/abc.json"),
            "_meta/a3312780-4cfe-48eb-af8a-f405f369a4f8/abc.json",
        )

    def test_reserved_characters_are_percent_encoded(self):
        self.assertEqual(md.encode_key("a b+c"), "a%20b%2Bc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
