#!/usr/bin/env python3
"""Measuring real per-token costs of Cashu-metered providers.

Sends a fixed ~500-token prompt through each routstr-family provider
(routstr node on :8009, routstrd daemon on :8008), records the wallet
balance delta before/after, computes sats/M from reported usage tokens,
and stores it in zai_usage.db `measured_rates`. Also records BTC/USD spot
from CoinGecko (with env override fallback). Never raises; on failure
leaves prior measurements intact.

Cron: runs daily at 03:00 via crontab (before cost-escalation cron).
"""
import json, sqlite3, os, time, urllib.request

PROBE_PROMPT = "Summarize the following text in one sentence: " + " ".join(["word"] * 450)
PROBE_MAX_TOKENS = 30
DB_PATH = os.path.expanduser("~/.hermes/bot/zai_usage.db")
BTC_CACHE_PATH = os.path.expanduser("~/.hermes/bot/btc_usd_cache.json")


def btc_usd_rate():
    env_rate = os.environ.get("BTC_USD_RATE", "").strip()
    if env_rate:
        try:
            return float(env_rate)
        except ValueError:
            pass
    try:
        if os.path.exists(BTC_CACHE_PATH):
            st = json.load(open(BTC_CACHE_PATH))
            if st.get("rate") and time.time() - st.get("ts", 0) < 600:
                return st["rate"]
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            rate = float(json.loads(resp.read())["bitcoin"]["usd"])
        json.dump({"rate": rate, "ts": time.time()}, open(BTC_CACHE_PATH, "w"))
        return rate
    except Exception:
        if os.path.exists(BTC_CACHE_PATH):
            try:
                return float(json.load(open(BTC_CACHE_PATH)).get("rate") or 100000.0)
            except Exception:
                pass
        return 100000.0


def probe_provider(base, key, model):
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    bal_url = base + "/v1/balance/info"
    chat_url = base + "/v1/chat/completions"
    hdrs_chat = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    hdrs_bal = {"Authorization": f"Bearer {key}"}
    try:
        bal_before = json.loads(urllib.request.urlopen(
            urllib.request.Request(bal_url, headers=hdrs_bal), timeout=10).read()).get("balance")
    except Exception as e:
        return {"error": f"balance_before: {e}"}
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": PROBE_PROMPT}],
                       "max_tokens": PROBE_MAX_TOKENS}).encode()
    try:
        resp = urllib.request.urlopen(
            urllib.request.Request(chat_url, data=body, headers=hdrs_chat, method="POST"),
            timeout=60).read()
        usage = json.loads(resp).get("usage", {}) or {}
    except Exception as e:
        return {"error": f"chat: {e}"}
    try:
        bal_after = json.loads(urllib.request.urlopen(
            urllib.request.Request(bal_url, headers=hdrs_bal), timeout=10).read()).get("balance")
    except Exception as e:
        return {"error": f"balance_after: {e}"}
    sats_spent = bal_before - bal_after
    pt = usage.get("prompt_tokens", 0) or 0
    ct = usage.get("completion_tokens", 0) or 0
    tok_total = pt + ct
    if tok_total <= 0 or sats_spent <= 0:
        return {"error": f"no_spend (sats={sats_spent} tok={tok_total})"}
    sats_per_M = sats_spent / (tok_total / 1e6)
    btc = btc_usd_rate()
    usd_per_M = sats_per_M * btc / 1e8
    return {
        "sats_spent": sats_spent,
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "sats_per_M": sats_per_M,
        "usd_per_M": usd_per_M,
        "btc_usd": btc,
    }


def store(provider, model, result):
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS measured_rates (
        provider TEXT NOT NULL, model TEXT NOT NULL,
        sats_per_M REAL, usd_per_M REAL, btc_usd REAL,
        sats_spent REAL, prompt_tokens INTEGER, completion_tokens INTEGER,
        measured_at REAL NOT NULL, error TEXT
    )""")
    if "error" in result:
        c.execute("INSERT INTO measured_rates (provider, model, measured_at, error) VALUES (?,?,?,?)",
                  (provider, model, time.time(), result["error"]))
    else:
        c.execute("""INSERT INTO measured_rates
            (provider, model, sats_per_M, usd_per_M, btc_usd, sats_spent, prompt_tokens,
             completion_tokens, measured_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
                  (provider, model, result["sats_per_M"], result["usd_per_M"], result["btc_usd"],
                   result["sats_spent"], result["prompt_tokens"], result["completion_tokens"], time.time()))
    c.commit()
    c.close()


def main():
    keys_env = [
        os.path.expanduser("~/.hermes/profiles/manager/.env"),
        os.path.expanduser("~/.hermes/.env"),
    ]
    keys = {}
    for p in keys_env:
        if not os.path.exists(p):
            continue
        for line in open(p, errors="ignore").read().splitlines():
            line = line.strip()
            if line.startswith("ROUTSTR_API_KEY=") and "routstr" not in keys:
                keys["routstr"] = line.split("=", 1)[1].split("#")[0].strip().strip("'\"")
            elif line.startswith("ROUTSTR_BASE=") and "routstr_base" not in keys:
                keys["routstr_base"] = line.split("=", 1)[1].split("#")[0].strip().strip("'\"")
            elif line.startswith("ROUTSTRD_API_KEY=") and "routstrd" not in keys:
                keys["routstrd"] = line.split("=", 1)[1].split("#")[0].strip().strip("'\"")
            elif line.startswith("ROUTSTRD_BASE=") and "routstrd_base" not in keys:
                keys["routstrd_base"] = line.split("=", 1)[1].split("#")[0].strip().strip("'\"")

    targets = [
        ("routstr", keys.get("routstr_base", "http://localhost:8009"), keys.get("routstr", ""), "glm-5.2"),
        ("routstrd", keys.get("routstrd_base", "http://localhost:8008"), keys.get("routstrd", ""), "glm-5.2"),
    ]
    summary = []
    for provider, base, key, model in targets:
        if not key:
            store(provider, model, {"error": "no_api_key"})
            summary.append(f"{provider}: skip (no key)")
            continue
        r = probe_provider(base, key, model)
        store(provider, model, r)
        if "error" in r:
            summary.append(f"{provider}: ERR {r['error']}")
        else:
            summary.append(f"{provider}: {r['sats_per_M']:.2f} sat/M = ${r['usd_per_M']:.4f}/M (sats={r['sats_spent']}, tok={r['prompt_tokens']}+{r['completion_tokens']})")
    print(f"routstr_probe {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}:")
    for s in summary:
        print(f"  {s}")


if __name__ == "__main__":
    main()
