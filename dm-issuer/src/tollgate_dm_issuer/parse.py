"""DM request grammar (spec §3).

Two accepted request forms:

1. **Plain text** (human-friendly primary UX)::

       ecash <amount>          e.g.  "ecash 5000"
       ecash <amount> sats     unit suffix optional, ignored (sat-only mint)

   Grammar: ``^ecash\\s+(\\d+)\\s*(sats?)?$`` — case-insensitive, trimmed.

2. **JSON envelope** (machine clients)::

       {"type": "ecash_request", "schema_version": 1,
        "amount": 5000, "nonce": "<random hex, client-chosen>"}

The parser never raises on its own for malformed input — it converts every
non-parse failure to a ``ParseError(ErrorCode.BAD_REQUEST | AMOUNT_INVALID)``
so the caller can fan out the user-facing error envelope (§3.3).
"""
from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass
from typing import Optional


PLAIN_RE = re.compile(
    r"""^\s*"?\s*ecash\s+(?P<amount>\d+)\s*(?P<unit>sats?)?\s*"?\s*$""",
    re.IGNORECASE,
)
MAX_AMOUNT = 100_000_000


class ErrorCode(str, enum.Enum):
    BAD_REQUEST = "BAD_REQUEST"
    AMOUNT_INVALID = "AMOUNT_INVALID"

    def __str__(self) -> str:
        return self.value


class ParseError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ParseError) and self.code == other.code and self.message == other.message

    def __hash__(self) -> int:
        return hash((self.code, self.message))


@dataclass(frozen=True)
class PlainRequest:
    amount: int
    nonce: Optional[str] = None


@dataclass(frozen=True)
class JsonRequest:
    amount: int
    nonce: Optional[str] = None
    schema_version: int = 1


ParseResult = PlainRequest | JsonRequest


def _validate_amount(amount: int) -> int:
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ParseError(ErrorCode.AMOUNT_INVALID, f"amount must be an integer, got {type(amount).__name__}")
    if amount <= 0:
        raise ParseError(ErrorCode.AMOUNT_INVALID, "amount must be > 0")
    if amount > MAX_AMOUNT:
        raise ParseError(
            ErrorCode.AMOUNT_INVALID,
            f"amount {amount} exceeds the hard cap of {MAX_AMOUNT} sats",
        )
    return amount


def parse_dm_request(body: str) -> ParseResult:
    if not isinstance(body, str):
        raise ParseError(ErrorCode.BAD_REQUEST, "request body must be a string")
    stripped = body.strip()
    if not stripped:
        raise ParseError(ErrorCode.BAD_REQUEST, "empty request body")

    if stripped[0] == "{":
        return _parse_json(stripped)
    return _parse_plain(stripped)


def _parse_plain(body: str) -> PlainRequest:
    m = PLAIN_RE.match(body)
    if m is None:
        raise ParseError(ErrorCode.BAD_REQUEST, "request is not 'ecash <amount>'")
    amount = int(m.group("amount"))
    return PlainRequest(amount=_validate_amount(amount))


def _parse_json(body: str) -> JsonRequest:
    try:
        obj = json.loads(body)
    except ValueError as exc:
        raise ParseError(ErrorCode.BAD_REQUEST, f"malformed JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ParseError(ErrorCode.BAD_REQUEST, "JSON root must be an object")
    req_type = obj.get("type")
    if req_type != "ecash_request":
        raise ParseError(
            ErrorCode.BAD_REQUEST,
            f"unsupported type {req_type!r}; only 'ecash_request' accepted",
        )
    amount = obj.get("amount")
    if isinstance(amount, float):
        if not amount.is_integer():
            raise ParseError(ErrorCode.AMOUNT_INVALID, "amount must be an integer, not a fraction")
        amount = int(amount)
    amount = _validate_amount(amount)
    nonce = obj.get("nonce")
    if nonce is not None and not isinstance(nonce, str):
        raise ParseError(ErrorCode.BAD_REQUEST, "nonce must be a string when present")
    schema_version = int(obj.get("schema_version", 1))
    return JsonRequest(amount=amount, nonce=nonce, schema_version=schema_version)
