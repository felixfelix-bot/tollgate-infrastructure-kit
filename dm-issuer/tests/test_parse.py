import pytest

from tollgate_dm_issuer.parse import (
    ErrorCode,
    ParseError,
    ParseResult,
    parse_dm_request,
    PlainRequest,
    JsonRequest,
)


class TestPlainText:
    def test_simple_ecash_amount(self):
        r = parse_dm_request("ecash 5000")
        assert isinstance(r, PlainRequest)
        assert r.amount == 5000
        assert r.nonce is None

    def test_ecash_amount_sat_suffix(self):
        r = parse_dm_request("ecash 5000 sats")
        assert r.amount == 5000
        r2 = parse_dm_request("ecash 5000 sat")
        assert r2.amount == 5000

    def test_whitespace_tolerance(self):
        r = parse_dm_request("  ecash   1234  ")
        assert r.amount == 1234

    def test_case_insensitive(self):
        r = parse_dm_request("ECASH 1000")
        assert r.amount == 1000
        r2 = parse_dm_request("Ecash 10 Sats")
        assert r2.amount == 10

    def test_wraps_in_quotes(self):
        r = parse_dm_request('"ecash 7"')
        assert isinstance(r, PlainRequest)
        assert r.amount == 7

class TestJsonEnvelope:
    def test_json_envelope(self):
        r = parse_dm_request('{"type":"ecash_request","schema_version":1,"amount":5000,"nonce":"abc"}')
        assert isinstance(r, JsonRequest)
        assert r.amount == 5000
        assert r.nonce == "abc"

    def test_json_envelope_no_nonce(self):
        r = parse_dm_request('{"type":"ecash_request","schema_version":1,"amount":1000}')
        assert isinstance(r, JsonRequest)
        assert r.amount == 1000
        assert r.nonce is None

    def test_json_envelope_wrong_type_rejected(self):
        with pytest.raises(ParseError) as exc:
            parse_dm_request('{"type":"wrong","schema_version":1,"amount":1000}')
        assert exc.value.code == ErrorCode.BAD_REQUEST

    def test_json_envelope_negative_amount_rejected(self):
        with pytest.raises(ParseError) as exc:
            parse_dm_request('{"type":"ecash_request","schema_version":1,"amount":-1}')
        assert exc.value.code == ErrorCode.AMOUNT_INVALID

    def test_json_envelope_oversized_amount_rejected(self):
        with pytest.raises(ParseError) as exc:
            parse_dm_request('{"type":"ecash_request","schema_version":1,"amount":99999999999}')
        assert exc.value.code == ErrorCode.AMOUNT_INVALID


class TestFailures:
    @pytest.mark.parametrize("body", [
        "",
        "hello",
        "ecash",
        "ecash abc",
        "ecash 0",
        "ecash -1",
        "ecash 100 200",
        "ecash 1.5",  # floats rejected per grammar
        '{"type":"ecash_request","schema_version":1,"amount":"abc"}',
        '{"type":"ecash_request","schema_version":1}',
        'not json at all',
    ])
    def test_bad(self, body):
        with pytest.raises(ParseError):
            parse_dm_request(body)

    def test_low_amount_returns_amount_invalid(self):
        from tollgate_dm_issuer.parse import _validate_amount
        with pytest.raises(ParseError):
            _validate_amount(-1)
        with pytest.raises(ParseError) as exc:
            _validate_amount(0)
        assert exc.value.code == ErrorCode.AMOUNT_INVALID


class TestPropertyRoundtrip:
    @pytest.mark.parametrize("a", [1, 2, 100, 10_000, 99_999_999, 1_234_567])
    def test_positive_integer_roundtrips(self, a):
        r = parse_dm_request(f"ecash {a}")
        assert r.amount == a
