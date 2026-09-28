import hashlib
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _create_event(tags: list[list[str]], content: str) -> dict:
    return {
        "kind": 1985,
        "tags": tags,
        "content": content,
        "created_at": int(time.time()),
    }


def build_nostr_event(
    repo_url: str,
    commit_sha: str,
    branch: str,
    status: str,
    duration_ms: int,
    log_url: str = "",
    nsec: str = "",
) -> dict:
    tags = [
        ["d", f"{repo_url}:{branch}"],
        ["commit", commit_sha],
        ["branch", branch],
        ["status", status],
        ["duration_ms", str(duration_ms)],
    ]

    content = json.dumps(
        {
            "repo": repo_url,
            "commit": commit_sha,
            "branch": branch,
            "status": status,
            "duration_ms": duration_ms,
            "log_url": log_url,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )

    event = _create_event(tags, content)

    if nsec:
        try:
            from pynostr.key import PrivateKey

            pk = PrivateKey.from_nsec(nsec)
            event["pubkey"] = pk.public_key.hex()
            event_serialized = json.dumps(
                [0, event["pubkey"], event["kind"], event["tags"], event["content"]],
                separators=(",", ":"),
            )
            event_id = hashlib.sha256(event_serialized.encode()).hexdigest()
            event["id"] = event_id
            sig = pk.sign(event_id)
            event["sig"] = sig
        except Exception as e:
            logger.error(f"Failed to sign Nostr event: {e}")

    return event


async def publish_event(event: dict, relay_urls: list[str]) -> list[str]:
    import asyncio

    successful = []

    for relay_url in relay_urls:
        try:
            import websockets

            ws_relay = relay_url.replace("wss://", "ws://").replace(
                "https://", "ws://"
            )
            if not ws_relay.startswith("ws://"):
                ws_relay = "ws://" + ws_relay

            async with websockets.connect(ws_relay, close_timeout=5) as ws:
                message = json.dumps(["EVENT", event])
                await ws.send(message)
                response = await asyncio.wait_for(ws.recv(), timeout=5)
                resp = json.loads(response)
                if resp[0] == "OK" and resp[2]:
                    successful.append(relay_url)
                    logger.info(f"Published to {relay_url}")
                else:
                    logger.warning(f"Relay {relay_url} rejected: {resp}")
        except Exception as e:
            logger.error(f"Failed to publish to {relay_url}: {e}")

    return successful
