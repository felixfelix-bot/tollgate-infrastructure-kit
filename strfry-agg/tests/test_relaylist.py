from strfry_agg.relaylist import RelayList, extract_relays_from_10002, pick_scrape_relays

R1 = "wss://relay.damus.io"
R2 = "wss://nos.lol"
R3 = "wss://relay.orangesync.tech"


def _ev(tags):
    return {"kind": 10002, "tags": tags}


def test_extract_read_write_markers():
    rl = extract_relays_from_10002(_ev([["r", R1, "read"], ["r", R2, "write"]]))
    assert rl.read == [R1]
    assert rl.write == [R2]
    assert rl.both == []


def test_extract_bare_r_counts_as_both():
    rl = extract_relays_from_10002(_ev([["r", R1]]))
    assert rl.both == [R1]
    assert rl.read == [] and rl.write == []


def test_extract_ignores_other_tags_and_empty():
    rl = extract_relays_from_10002(_ev([["e", "x"], ["r", ""], ["p", "y"], ["r", R3]]))
    assert rl.both == [R3]


def test_pick_scrape_relays_prefers_write_then_both_then_read():
    rl = RelayList(read=[R1], write=[R2], both=[R3])
    out = pick_scrape_relays(rl)
    assert out[0] == R2
    assert out[1] == R3
    assert out[2] == R1


def test_pick_scrape_relays_dedup_and_strip_trailing_slash():
    rl = RelayList(both=["wss://nos.lol/", "wss://nos.lol"])
    out = pick_scrape_relays(rl)
    assert out == ["wss://nos.lol"]


def test_pick_scrape_relays_fallback_when_empty():
    out = pick_scrape_relays(RelayList(), fallback=[R1, R2])
    assert out == [R1, R2]


def test_pick_scrape_relays_no_fallback_when_present():
    out = pick_scrape_relays(RelayList(write=[R3]), fallback=[R1])
    assert out == [R3]
