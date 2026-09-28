"""Nostr pubkey encoding helpers (npub <-> hex).

A Nostr pubkey is a 32-byte secp256k1 x-only public key, serialized as 64 hex
chars. The human-friendly form is bech32 with HRP ``npub``.
"""

from __future__ import annotations

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_NPUB_HRP = "npub"


def _polymod(values: list[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create_checksum(hrp: str, data: list[int]) -> list[int]:
    values = _hrp_expand(hrp) + data
    polymod = _polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _bech32_verify_checksum(hrp: str, data: list[int]) -> bool:
    return _polymod(_hrp_expand(hrp) + data) == 1


def _convertbits(data: list[int], frombits: int, tobits: int, pad: bool) -> list[int]:
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            raise ValueError("invalid data value for convertbits")
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError("non-zero padding bits in convertbits")
    return ret


def _bech32_encode(hrp: str, data: list[int]) -> str:
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(_BECH32_CHARSET[d] for d in combined)


def _bech32_decode(bech: str) -> tuple[str, list[int]]:
    if any(ord(x) < 33 or ord(x) > 126 for x in bech):
        raise ValueError("invalid character in bech32 string")
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech):
        raise ValueError("invalid bech32 separator position")
    if not all(x in _BECH32_CHARSET for x in bech[pos + 1:]):
        raise ValueError("invalid character in data part")
    hrp = bech[:pos]
    data = [_BECH32_CHARSET.index(x) for x in bech[pos + 1:]]
    if not _bech32_verify_checksum(hrp, data):
        raise ValueError("invalid bech32 checksum")
    return hrp, data[:-6]


def hex_to_npub(hex_str: str) -> str:
    """Convert a 64-char hex pubkey to its bech32 ``npub1...`` form."""
    cleaned = hex_str.lower().strip()
    if len(cleaned) != 64:
        raise ValueError(f"expected 64-char hex pubkey, got {len(cleaned)} chars")
    raw = bytes.fromhex(cleaned)
    return _bech32_encode(_NPUB_HRP, _convertbits(list(raw), 8, 5, True))


def npub_to_hex(npub: str) -> str:
    """Convert a bech32 ``npub1...`` to its 64-char lowercase hex form."""
    hrp, data = _bech32_decode(npub.strip())
    if hrp != _NPUB_HRP:
        raise ValueError(f"expected HRP 'npub', got '{hrp}'")
    decoded = _convertbits(data, 5, 8, False)
    if len(decoded) != 32:
        raise ValueError(f"expected 32 bytes after decode, got {len(decoded)}")
    return bytes(decoded).hex()


def is_valid_pubkey_hex(value: str) -> bool:
    """True if value is a 64-char lowercase hex string."""
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
