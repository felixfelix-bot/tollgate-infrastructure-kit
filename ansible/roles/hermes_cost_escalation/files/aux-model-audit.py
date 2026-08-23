#!/usr/bin/env python3
"""Auxiliary-model routing audit (report-only, LLM-free).

Identifies non-chat auxiliary LLM calls (context compression, summaries,
session titles, subagents, background workers) and checks whether they land
on PAID providers (routstrd paid path, OpenRouter, telnyx) instead of the
near-free z.ai coding key via the routstr node.

Classification heuristic (verified against zai_usage.db on 2026-08-22):
  aux call  := session_id IS NULL (no interactive session context)
  cron call := session_id LIKE 'cron_%'
  chat call := otherwise

Signature that matters: aux calls with prompt >> completion tokens are
compression/summarization — the most wasteful thing to run on a paid
provider.

Output: appends/rewrites ~/.hermes/bot/aux_model_audit_report.md and
prints a short summary on stdout (rides the escalation cron once/day;
stdout only lists actionable items, so silence = all aux traffic is on
free paths).
"""
import sqlite3, os, time

DB = os.path.expanduser("~/.hermes/bot/zai_usage.db")
REPORT = os.path.expanduser("~/.hermes/bot/aux_model_audit_report.md")
WINDOW_H = 24
# effective $/M we'd pay if the call went via the routstr node (z.ai key)
NODE_PRICE_PER_M = 0.0004

PAID_KEYS = ("openrouter", "routstrd", "telnyx")


def main():
    now = time.time()
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row

    rows = c.execute("""
        SELECT CASE WHEN session_id IS NULL THEN 'aux'
                    WHEN session_id LIKE 'cron_%' THEN 'cron'
                    ELSE 'chat' END AS klass,
               model, tier, key_name, COUNT(*) AS n,
               SUM(prompt_tokens) AS pt, SUM(completion_tokens) AS ct,
               SUM(cost_usd) AS cost
        FROM api_calls WHERE ts > ?
        GROUP BY 1, 2, 3, 4 ORDER BY cost DESC
    """, (now - WINDOW_H * 3600,)).fetchall()

    c.close()

    # effective $/M per paid key from routing_profit (routstrd costs are not
    # attributed in api_calls.cost_usd — estimate from tokens x price)
    prices = {}
    try:
        pc = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        for pr in pc.execute("""SELECT provider_used, effective_price FROM routing_profit
                                WHERE ts > ? GROUP BY 1 ORDER BY MAX(ts) DESC""",
                             (now - WINDOW_H * 3600,)):
            prices.setdefault(pr[0], pr[1])
        pc.close()
    except Exception:
        pass

    lines = [
        f"# Auxiliary-Model Routing Audit",
        f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(now))}"
        f" · window: last {WINDOW_H}h · source: zai_usage.db\n",
        "| class | model | tier | key | calls | prompt tok | compl tok | $ spent | est. $ if on node z.ai |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    actionable = []
    total_paid_aux = 0.0
    for r in rows:
        klass, model, tier, key = r["klass"], r["model"] or "(none)", r["tier"], r["key_name"]
        cost = r["cost"] or 0.0
        pt = r["pt"] or 0
        ct = r["ct"] or 0
        # routstrd (and any paid key with unattributed cost): estimate
        if key in PAID_KEYS and cost == 0.0 and pt + ct > 0:
            cost = (pt + ct) / 1e6 * prices.get(key, 1.0)
        est_node = (pt + ct) / 1e6 * NODE_PRICE_PER_M
        lines.append(
            f"| {klass} | {model} | {tier} | {key} | {r['n']} | {pt:,} | "
            f"{ct:,} | ${cost:.2f} | ${est_node:.4f} |")
        if klass == "aux" and key in PAID_KEYS:
            total_paid_aux += cost
            actionable.append(
                f"⚠️ AUX ON PAID PATH: {r['n']} calls {model} via {key} — "
                f"~${cost:.2f}/24h ({pt:,} prompt tok, {ct:,} compl tok; "
                f"compression signature={'yes' if pt > 10 * max(ct, 1) else 'no'}); "
                f"node z.ai est. ${est_node:.4f}")

    with open(REPORT, "w") as f:
        f.write("\n".join(lines) + "\n")
        if actionable:
            f.write("\n## Actionable (aux traffic on paid providers)\n\n")
            f.write("\n".join(f"- {a}" for a in actionable) + "\n")
        else:
            f.write("\nAll auxiliary traffic is on free paths. Nothing to do.\n")

    # stdout: only actionable items (escalation-cron friendly)
    for a in actionable:
        print(a)
    if total_paid_aux > 1.0:
        print(f"💰 AUX PAID TOTAL: ${total_paid_aux:.2f}/24h — reroute to node z.ai would cut it to ~$0")


if __name__ == "__main__":
    main()
