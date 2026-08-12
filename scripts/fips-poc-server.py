#!/usr/bin/env python3
"""FIPS Ingress Gate PoC — test web server bound to T470 FIPS address.

Serves a simple HTML page on the FIPS mesh IPv6 address so VPS2 Caddy
can reverse-proxy public traffic to it.

Usage:
    python3 fips-poc-server.py [--host fd97:...] [--port 8888]
"""

import argparse
import html
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler


PAGE_TITLE = "FIPS Ingress Gate PoC"
PAGE_BODY = "FIPS Ingress Gate PoC - served from T470"


class PoCHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"<!DOCTYPE html><html><head><title>{html.escape(PAGE_TITLE)}</title></head><body><h1>{html.escape(PAGE_BODY)}</h1><p>Served via FIPS mesh IPv6 reverse proxy.</p></body></html>"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[fips-poc] {self.address_string()} - {fmt % args}\n")


def main():
    parser = argparse.ArgumentParser(description="FIPS Ingress Gate PoC server")
    parser.add_argument(
        "--host",
        default="fd97:77d4:cd27:a6ae:1b29:e92e:fd96:dee8",
        help="FIPS IPv6 address to bind (default: T470)",
    )
    parser.add_argument("--port", type=int, default=8888, help="Port to bind (default: 8888)")
    args = parser.parse_args()

    addr = (args.host, args.port, 0, 0)
    server = HTTPServer(addr, PoCHandler)
    print(f"[fips-poc] listening on [{args.host}]:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[fips-poc] shutting down", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()