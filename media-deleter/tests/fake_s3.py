import http.server, sys

OBJECTS = [o for o in sys.argv[2].split(",") if o] if len(sys.argv) > 2 else []
DELETED = []


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        listing = "".join(
            f"<Contents><Key>{k}</Key><LastModified>2026-08-16T00:26:03.000Z</LastModified>"
            f"<Size>1</Size></Contents>"
            for k in OBJECTS
        )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?><ListBucketResult>'
            f"{listing}<IsTruncated>false</IsTruncated></ListBucketResult>"
        ).encode()
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
        # Logged so the harness can assert exactly which keys were removed.
        print(f"DELETED {key}", flush=True)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()


http.server.ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), H).serve_forever()
