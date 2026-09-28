"""Coverage gap: parse.py — ParseError __eq__/__hash__, non-string input,
JSON edge cases (non-dict root, integer-float fraction nonce)."""
from __future__ import annotations

import pytest

from tollgate_dm_issuer.parse import (
    ErrorCode,
    JsonRequest,
    ParseError,
    PlainRequest,
    _validate_amount,
    parse_dm_request,
)


class TestParseErrorEquality:
    def test_eq_same_code_and_message(self):
        a = ParseError(ErrorCode.BAD_REQUEST, "msg")
        b = ParseError(ErrorCode.BAD_REQUEST, "msg")
        assert a == b

    def test_eq_different_message(self):
        a = ParseError(ErrorCode.BAD_REQUEST, "msg1")
        b = ParseError(ErrorCode.BAD_REQUEST, "msg2")
        assert a != b

    def test_eq_different_code(self):
        a = ParseError(ErrorCode.BAD_REQUEST, "msg")
        b = ParseError(ErrorCode.AMOUNT_INVALID, "msg")
        assert a != b

    def test_eq_against_non_parse_error(self):
        a = ParseError(ErrorCode.BAD_REQUEST, "msg")
        assert a != 42
        assert a != "string"

    def test_hash_stable(self):
        a = ParseError(ErrorCode.BAD_REQUEST, "msg")
        b = ParseError(ErrorCode.BAD_REQUEST, "msg")
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_str_returns_code_value(self):
        assert str(ErrorCode.BAD_REQUEST) == "BAD_REQUEST"


class TestNonStringInput:
    def test_non_string_raises_bad_request(self):
        with pytest.raises(ParseError) as exc:
            parse_dm_request(123)
        assert exc.value.code == ErrorCode.BAD_REQUEST

    def test_bytes_input_raises_bad_request(self):
        with pytest.raises(ParseError):
            parse_dm_request(b"ecash 5000")


class TestValidateAmountBool:
    def test_bool_rejected_as_amount(self):
        with pytest.raises(ParseError) as exc:
            _validate_amount(True)
        assert exc.value.code == ErrorCode.AMOUNT_INVALID

    def test_oversized_amount_rejected(self):
        with pytest.raises(ParseError) as exc:
            _validate_amount(1_000_000_000)
        assert exc.value.code == ErrorCode.AMOUNT_INVALID


class TestJsonEdgeCases:
    def test_json_root_not_object_raises_bad_request(self):
        with pytest.raises(ParseError) as exc:
            parse_dm_request("[1, 2, 3]")
        assert exc.value.code == ErrorCode.BAD_REQUEST

    def test_json_amount_float_with_fraction_rejected(self):
        with pytest.raises(ParseError) as exc:
            parse_dm_request(
                '{"type":"ecash_request","amount":1.5}'
            )
        assert exc.value.code == ErrorCode.AMOUNT_INVALID

    def test_json_amount_integer_float_accepted(self):
        r = parse_dm_request('{"type":"ecash_request","amount":1000.0}')
        assert isinstance(r, JsonRequest)
        assert r.amount == 1000

    def test_json_nonce_not_string_rejected(self):
        with pytest.raises(ParseError) as exc:
            parse_dm_request(
                '{"type":"ecash_request","amount":1000,"nonce":42}'
            )
        assert exc.value.code == ErrorCode.BAD_REQUEST

    def test_json_with_nonce_returns_json_request(self):
        r = parse_dm_request(
            '{"type":"ecash_request","schema_version":2,"amount":500,"nonce":"abc"}'
        )
        assert isinstance(r, JsonRequest)
        assert r.nonce == "abc"
        assert r.schema_version == 2

    def test_malformed_json_raises_bad_request(self):
        with pytest.raises(ParseError) as exc:
            parse_dm_request('{"type":"ecash_request",')
        assert exc.value.code == ErrorCode.BAD_REQUEST


class TestPlainMatchMisses:
    def test_underscores_only_rejected(self):
        with pytest.raises(ParseError):
            parse_dm_request("___")

    def test_amount_followed_by_unrecognized_unit_rejected(self):
        with pytest.raises(ParseError):
            parse_dm_request("ecash 1000 eur")
