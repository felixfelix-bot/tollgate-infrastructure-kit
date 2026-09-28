from strfry_agg.crypto import npub_to_hex
from strfry_agg.reconcile import (
    build_delete_filter,
    build_sync_filter,
    diff_followed,
    extract_followed_pubkeys,
    format_allowlist,
    format_env_npubs,
    parse_allowlist,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
ROOT_NPUB = "npub1c03rad0r6q833vh57kyd3ndu2jry30nkr0wepqfpsm05vq7he25slryrnw"


def _kind3(pubkeys_hex):
    return {"kind": 3, "tags": [["p", pk] for pk in pubkeys_hex], "content": "{}"}


def test_extract_followed_pubkeys_basic():
    ev = _kind3([HEX_A, HEX_B])
    assert extract_followed_pubkeys(ev) == {HEX_A, HEX_B}


def test_extract_followed_pubkeys_skips_non_p_tags():
    ev = {"tags": [["e", "evt1"], ["p", HEX_A], ["x", "y"], ["p", HEX_B]]}
    assert extract_followed_pubkeys(ev) == {HEX_A, HEX_B}


def test_extract_followed_pubkeys_normalises_case():
    ev = _kind3([HEX_A.upper()])
    assert extract_followed_pubkeys(ev) == {HEX_A}


def test_extract_followed_pubkeys_accepts_npub_form():
    ev = {"tags": [["p", ROOT_NPUB]]}
    extracted = extract_followed_pubkeys(ev)
    assert npub_to_hex(ROOT_NPUB) in extracted


def test_extract_followed_pubkeys_ignores_malformed():
    ev = {"tags": [["p"], ["p", ""], ["p", "tooshort"], ["p", HEX_A]]}
    assert extract_followed_pubkeys(ev) == {HEX_A}


def test_extract_followed_pubkeys_no_tags():
    assert extract_followed_pubkeys({}) == set()
    assert extract_followed_pubkeys({"tags": []}) == set()


def test_diff_added_removed_unchanged():
    old = {HEX_A, HEX_B, HEX_C}
    new = {HEX_B, HEX_C, HEX_D}
    res = diff_followed(old, new)
    assert res.added == {HEX_D}
    assert res.removed == {HEX_A}
    assert res.unchanged == {HEX_B, HEX_C}
    assert res.new_set == new
    assert res.old_set == old
    assert res.changed


def test_diff_no_change():
    res = diff_followed({HEX_A}, {HEX_A})
    assert not res.changed
    assert res.added == set() and res.removed == set()


def test_diff_shrink_only():
    res = diff_followed({HEX_A, HEX_B}, {HEX_A})
    assert res.removed == {HEX_B}
    assert res.added == set()


def test_diff_grow_only():
    res = diff_followed({HEX_A}, {HEX_A, HEX_B})
    assert res.added == {HEX_B}
    assert res.removed == set()


def test_build_delete_filter():
    flt = build_delete_filter([HEX_A, HEX_B])
    assert flt["authors"] == [HEX_A, HEX_B]
    assert "kinds" not in flt


def test_build_delete_filter_empty_sentinel():
    assert build_delete_filter([]) == {}


def test_build_delete_filter_with_kinds():
    flt = build_delete_filter([HEX_A], kinds=[1, 3])
    assert flt["kinds"] == [1, 3]


def test_build_sync_filter():
    flt = build_sync_filter([HEX_A], kinds=[1])
    assert flt == {"authors": [HEX_A], "kinds": [1]}


def test_format_and_parse_allowlist_roundtrip():
    s = format_allowlist({HEX_B, HEX_A})
    assert s.splitlines() == sorted([HEX_A, HEX_B])
    parsed = parse_allowlist(s)
    assert parsed == {HEX_A, HEX_B}


def test_parse_allowlist_handles_npub_and_comments():
    text = f"# comment\n{HEX_A}\n\n{HEX_B}\n"
    assert parse_allowlist(text) == {HEX_A, HEX_B}


def test_format_env_npubs_valid():
    out = format_env_npubs([HEX_A])
    assert out.startswith("npub1")


def test_format_env_npubs_empty():
    assert format_env_npubs([]) == ""


def test_format_env_npubs_skips_invalid():
    out = format_env_npubs([HEX_A, "bad"])
    assert "bad" not in out
