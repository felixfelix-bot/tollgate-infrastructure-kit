import argparse
import hashlib
import json
import os
import time
import asyncio
import websockets


SUPPORTED_UNITS = ["sat", "usd", "eur", "B", "KB", "MB", "GB", "sec", "min", "hr", "day", "wk", "mo"]


def _hex_from_npub(npub: str) -> str:
    try:
        from pynostr.nip19 import npub_decode
        return npub_decode(npub)
    except ImportError:
        pass
    try:
        from bech32 import bech32_decode, convertbits
        hrp, data = bech32_decode(npub)
        if hrp != "npub" or data is None:
            raise ValueError(f"Invalid npub: {npub}")
        decoded = convertbits(data, 5, 8, False)
        if decoded is None:
            raise ValueError(f"Invalid npub: {npub}")
        return bytes(decoded).hex()
    except ImportError:
        if npub.startswith("npub1") and len(npub) == 63:
            raise ImportError("Install pynostr or bech32 to decode npub")
        return npub


def _hex_from_nsec(nsec: str) -> str:
    try:
        from pynostr.nip19 import nsec_decode
        return nsec_decode(nsec)
    except ImportError:
        pass
    try:
        from bech32 import bech32_decode, convertbits
        hrp, data = bech32_decode(nsec)
        if hrp != "nsec" or data is None:
            raise ValueError(f"Invalid nsec: {nsec}")
        decoded = convertbits(data, 5, 8, False)
        if decoded is None:
            raise ValueError(f"Invalid nsec: {nsec}")
        return bytes(decoded).hex()
    except ImportError:
        if nsec.startswith("nsec1") and len(nsec) == 63:
            raise ImportError("Install pynostr or bech32 to decode nsec")
        return nsec


def _derive_npub_hex(nsec_hex: str) -> str:
    try:
        from pynostr.key import PrivateKey
        pk = PrivateKey(bytes.fromhex(nsec_hex))
        return pk.public_key.hex()
    except ImportError:
        pass
    try:
        import secp256k1
        pk = secp256k1.PrivateKey(bytes.fromhex(nsec_hex), raw=True)
        return pk.pubkey.serialize()[1:].hex()
    except ImportError:
        raise ImportError("Install pynostr or secp256k1 to derive npub from nsec")


def _sign_event(event: dict, nsec_hex: str) -> dict:
    try:
        from pynostr.event import Event
        from pynostr.key import PrivateKey
        pk = PrivateKey(bytes.fromhex(nsec_hex))
        evt = Event(
            pubkey=pk.public_key.hex(),
            created_at=event["created_at"],
            kind=event["kind"],
            tags=event["tags"],
            content=event["content"],
        )
        evt.sign(pk.hex())
        return {
            "id": evt.id,
            "pubkey": evt.pubkey,
            "created_at": evt.created_at,
            "kind": evt.kind,
            "tags": evt.tags,
            "content": evt.content,
            "sig": evt.sig,
        }
    except ImportError:
        pass

    serialized = json.dumps(
        [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    event_id = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    try:
        import secp256k1
        pk = secp256k1.PrivateKey(bytes.fromhex(nsec_hex), raw=True)
        sig = pk.schnorr_sign(
            bytes.fromhex(event_id),
            None,
            raw=True,
        )
        return {
            **event,
            "id": event_id,
            "sig": sig.hex(),
        }
    except ImportError:
        raise ImportError("Install pynostr or secp256k1 to sign events")


async def _publish_event(event: dict, relay_url: str):
    async with websockets.connect(relay_url) as ws:
        msg = json.dumps(["EVENT", event])
        await ws.send(msg)
        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
        return json.loads(response)


def approve(args):
    nsec = args.nsec or os.environ.get("NSEC", "")
    if not nsec:
        print("Error: --nsec or NSEC env var required")
        return 1

    nsec_hex = _hex_from_nsec(nsec)
    npub_hex = _derive_npub_hex(nsec_hex)

    event = {
        "pubkey": npub_hex,
        "created_at": int(time.time()),
        "kind": 38010,
        "tags": [
            ["t", "mint-approval"],
            ["mint", args.mint],
            ["quote", args.quote],
            ["amount", str(args.amount)],
            ["unit", args.unit],
        ],
        "content": f"Mint approval for quote {args.quote} ({args.amount} {args.unit})",
    }

    signed = _sign_event(event, nsec_hex)

    print(f"Event ID: {signed['id']}")
    print(f"Pubkey:   {signed['pubkey']}")
    print(f"Kind:     {signed['kind']}")
    print(f"Tags:     {signed['tags']}")
    print()

    relay = args.relay or os.environ.get("RELAY", "wss://relay.orangesync.tech")
    print(f"Publishing to {relay}...")

    try:
        result = asyncio.run(_publish_event(signed, relay))
        if isinstance(result, list) and result[0] == "OK":
            print(f"Published successfully: {result}")
            return 0
        else:
            print(f"Relay response: {result}")
            return 0
    except Exception as e:
        print(f"Error publishing: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Approve Cashu mint quotes via Nostr events")
    parser.add_argument("--nsec", help="Nostr private key (nsec or hex)")
    parser.add_argument("--mint", required=True, help="Mint URL (e.g. https://abc.mints.domain)")
    parser.add_argument("--quote", required=True, help="Quote ID to approve")
    parser.add_argument("--amount", required=True, type=int, help="Amount to approve")
    parser.add_argument("--unit", default="sat", choices=SUPPORTED_UNITS, help="Unit (default: sat)")
    parser.add_argument("--relay", help="Nostr relay URL (default: wss://relay.orangesync.tech)")

    args = parser.parse_args()
    exit(approve(args))


if __name__ == "__main__":
    main()
