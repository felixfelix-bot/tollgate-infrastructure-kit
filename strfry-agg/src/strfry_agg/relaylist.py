"""NIP-65 (kind 10002) relay-list parsing.

Each followed npub advertises the relays it writes to via a kind 10002 event
with ``["r", <url>, <"read"|"write>]`` tags. The scraper uses these to decide
which upstream relays to negentropy-sync each author from.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RelayList:
    read: list[str] = field(default_factory=list)
    write: list[str] = field(default_factory=list)
    both: list[str] = field(default_factory=list)


def extract_relays_from_10002(event: dict) -> RelayList:
    """Parse a kind 10002 relay list event into read/write/both buckets.

    A bare ``["r", url]`` (no marker) counts as both read and write.
    """
    rl = RelayList()
    for tag in event.get("tags", []) or []:
        if not tag or tag[0] != "r" or len(tag) < 2:
            continue
        url = str(tag[1]).strip()
        if not url:
            continue
        marker = str(tag[2]).strip().lower() if len(tag) >= 3 else ""
        if marker == "read":
            rl.read.append(url)
        elif marker == "write":
            rl.write.append(url)
        else:
            rl.both.append(url)
    return rl


def pick_scrape_relays(relay_list: RelayList, fallback: list[str] | None = None) -> list[str]:
    """Choose relays to scrape an author from, de-duplicated, order-preserving.

    Preference: write+both relays (where the author publishes), then read,
    then fallback relays. Falls back to ``fallback`` when the author advertises
    nothing (e.g. no kind 10002 found).
    """
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(url: str) -> None:
        norm = url.rstrip("/")
        key = norm.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(norm)

    for url in relay_list.write + relay_list.both:
        _add(url)
    for url in relay_list.read:
        _add(url)
    if not ordered:
        for url in fallback or []:
            _add(url)
    return ordered
