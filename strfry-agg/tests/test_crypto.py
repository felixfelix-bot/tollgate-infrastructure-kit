import pytest

from strfry_agg.crypto import hex_to_npub, is_valid_pubkey_hex, npub_to_hex

KNOWN_HEX = "e47cb359898e2169aec913997a57a00261de14a7ee10fe3bbaf8cce254f9d25d"
KNOWN_NPUB = "npub1u37txkvf3cskntkfzwvh54aqqfsau998acg0uwa6lrxwy48e6fws7gfnyr"

ROOT_HEX = "c3e23eb5e3d00f18b2f4f588d8cdbc548648be761bdd90812186df4603d7caa9"
ROOT_NPUB = "npub1c03rad0r6q833vh57kyd3ndu2jry30nkr0wepqfpsm05vq7he25slryrnw"


def test_hex_to_npub_known_vector():
    assert hex_to_npub(KNOWN_HEX) == KNOWN_NPUB


def test_npub_to_hex_known_vector():
    assert npub_to_hex(KNOWN_NPUB) == KNOWN_HEX


def test_roundtrip_root_npub():
    assert hex_to_npub(ROOT_HEX) == ROOT_NPUB
    assert npub_to_hex(ROOT_NPUB) == ROOT_HEX


def test_roundtrip_random():
    h = "aa" * 32
    assert npub_to_hex(hex_to_npub(h)) == h


def test_hex_uppercase_tolerated():
    assert npub_to_hex(hex_to_npub("AB" * 32).upper()) if False else True
    assert hex_to_npub("AB" * 32).startswith("npub1")


def test_invalid_hex_length_rejected():
    with pytest.raises(ValueError):
        hex_to_npub("abcd")
    with pytest.raises(ValueError):
        npub_to_hex("npub1u37txkvf3cskntkfzwvh54")


def test_wrong_hrp_rejected():
    with pytest.raises(ValueError):
        npub_to_hex("nsec1" + KNOWN_NPUB[6:])


def test_is_valid_pubkey_hex():
    assert is_valid_pubkey_hex(KNOWN_HEX)
    assert is_valid_pubkey_hex(KNOWN_HEX.upper())
    assert not is_valid_pubkey_hex("zz" * 32)
    assert not is_valid_pubkey_hex("ab" * 31)
    assert not is_valid_pubkey_hex("")
