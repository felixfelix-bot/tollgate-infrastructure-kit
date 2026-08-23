#!/usr/bin/env python3
"""Cost & performance escalation checker.

Runs via cron (no_agent=true). Silent on success (empty stdout = nothing
to report). Non-empty stdout ONLY when something needs operator attention:

1. PAID BLEED: hourly paid spend > $2.00/h (sustained paid token burn)
2. KEY DEATH: any zai key marked dead (not just exhausted — exhausted is
   routine, dead is structural)
3. COST INEFFICIENCY: anomaly_events cost_inefficiency unresolved in last 1h
4. GATE BLOCKS: kanban tasks blocked with GATE/BLEED in title (operator action needed)
5. REPEATED CRASHES: 3+ consecutive_failures on any non-done task
6. QUOTA RECOVERY: zai quota transitions from 0% → >0% (free window opened)
7. DAILY SPEND SPIKE: today's total paid spend > $50

Thresholds are conservative — only surface what actually costs money or
blocks progress. Routine reclaims, promotions, chain advances stay silent
(handled by the pipeline advancers delivering to local).
"""
import sqlite3, os, time, json, sys, math

NOW = time.time()
ALERTS = []

EWMA_STATE_PATH = os.path.expanduser("~/.hermes/bot/escalation_ewma_state.json")
EWMA_ALPHA = 0.3           # ~5h effective memory
EWMA_MIN_SAMPLES = 6       # cold start: no outlier alert below this
EWMA_MAX_SAMPLES = 24      # rolling window for mean/std
EWMA_REARM_SECS = 2 * 3600  # same outlier type alerts max once per 2h


def _load_ewma_state():
    try:
        st = json.load(open(EWMA_STATE_PATH))
        if not isinstance(st.get("samples"), list):
            raise ValueError
        return st
    except Exception:
        # cold start / corrupted -> reset
        return {"ewma": None, "samples": [], "last_sample_hour": None,
                "last_alert_ts": 0}


def _save_ewma_state(st):
    try:
        json.dump(st, open(EWMA_STATE_PATH, "w"))
    except Exception:
        pass


def ewma_outlier_check(hourly_spend, db_conn=None):
    """Returns an alert string when trailing-hour paid spend is an outlier
    vs the EWMA baseline; composes with the Kalman token-burn prediction
    when available (actual >> predicted => paid failover dominating)."""
    st = _load_ewma_state()
    hour_now = int(NOW // 3600)
    samples = st["samples"]

    # Hour rollover: push the PREVIOUS completed hour's spend (we only ever
    # see trailing-window sums, so store the latest observation per hour).
    if st.get("last_sample_hour") is not None and hour_now != st["last_sample_hour"]:
        samples.append(st.get("last_hour_spend", 0.0))
        samples = samples[-EWMA_MAX_SAMPLES:]
        prev = samples[-1]
        st["ewma"] = prev if st["ewma"] is None else \
            EWMA_ALPHA * prev + (1 - EWMA_ALPHA) * st["ewma"]

    st["last_sample_hour"] = hour_now
    st["last_hour_spend"] = hourly_spend
    st["samples"] = samples
    _save_ewma_state(st)

    if len(samples) < EWMA_MIN_SAMPLES:
        return None  # cold start

    ewma = st["ewma"] if st["ewma"] is not None else (sum(samples) / len(samples))
    mean = sum(samples) / len(samples)
    var = sum((s - mean) ** 2 for s in samples) / len(samples)
    std = math.sqrt(var)
    threshold = max(3.0 * ewma, mean + 2.0 * std)

    if hourly_spend <= threshold or hourly_spend < 0.10:
        return None
    if NOW - st.get("last_alert_ts", 0) < EWMA_REARM_SECS:
        return None  # re-arm guard

    ratio = hourly_spend / ewma if ewma > 1e-9 else float("inf")
    msg = (f"💸 SPEND OUTLIER: ${hourly_spend:.2f}/h, {ratio:.1f}x normal "
           f"(EWMA ${ewma:.2f}/h)")

    # Kalman composition: predicted $/h = burn_rate_tph * price_per_M / 1M
    try:
        if db_conn is not None:
            row = db_conn.execute(
                "SELECT burn_rate_tph FROM kalman_samples ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            rp = db_conn.execute(
                "SELECT effective_price FROM routing_profit ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if row and rp and row["burn_rate_tph"] and rp["effective_price"]:
                pred = row["burn_rate_tph"] * rp["effective_price"] / 1e6
                if pred > 0 and hourly_spend / pred > 10:
                    msg += f" — paid failover dominating (Kalman predicted ${pred:.2f}/h)"
    except Exception:
        pass

    st["last_alert_ts"] = NOW
    _save_ewma_state(st)
    return msg

# ── 1. Paid burn rate (last 1h) ──
try:
    db = os.path.expanduser("~/.hermes/bot/zai_usage.db")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    row = c.execute("""SELECT SUM(cost_usd) as spend, COUNT(*) as calls
                       FROM api_calls WHERE cost_usd > 0 AND ts > ?""", (NOW - 3600,)).fetchone()
    hourly_spend = row['spend'] or 0
    hourly_calls = row['calls'] or 0
    if hourly_spend > 2.00:
        ALERTS.append(f"💸 PAID BLEED: ${hourly_spend:.2f} in last 1h ({hourly_calls} paid calls)")

    # ── 2. Key health ──
    for r in c.execute("SELECT key_name, healthy, failure_count, last_error_type FROM key_health"):
        if r['last_error_type'] == 'dead' and not r['healthy']:
            ALERTS.append(f"💀 KEY DEAD: {r['key_name']} ({r['failure_count']} failures, marked dead)")

    # ── 3. Cost inefficiency anomalies ──
    anoms = c.execute("""SELECT title, detail FROM anomaly_events
                         WHERE ts > ? AND resolved=0 AND category='cost_inefficiency'
                         ORDER BY ts DESC LIMIT 3""", (NOW - 3600,)).fetchall()
    for a in anoms:
        ALERTS.append(f"⚠️ INEFFICIENT ROUTING: {a['title'][:80]}")

    # ── 7. Daily spend ──
    today_str = time.strftime("%Y-%m-%d")
    spend_row = c.execute("""SELECT SUM(spend_usd) as total FROM daily_spend
                             WHERE date=? AND tier NOT IN ('ours','friend')""", (today_str,)).fetchone()
    today_paid = spend_row['total'] or 0
    if today_paid > 50:
        ALERTS.append(f"💰 DAILY PAID SPEND: ${today_paid:.2f} today (threshold $50)")
    # ── 8. EWMA spend outlier ──
    outlier = ewma_outlier_check(hourly_spend, c)
    if outlier:
        ALERTS.append(outlier)

    c.close()
except Exception as e:
    # Don't alert on DB errors — just skip
    pass

# ── 4. Kanban gate blocks + 5. Repeated crashes ──
try:
    kdb = os.path.expanduser("~/.hermes/kanban/boards/cost-gate-reform/kanban.db")
    kc = sqlite3.connect(f"file:{kdb}?mode=ro", uri=True, timeout=5)
    kc.row_factory = sqlite3.Row

    # Only surface gates where OPERATOR is the bottleneck (manager assignee, Felix/verdict/KEYGATE in title)
    gate_blocks = kc.execute("""SELECT id, title, assignee FROM tasks WHERE status='blocked'
                                AND (assignee='manager' OR title LIKE '%Felix%' OR title LIKE '%verdict%'
                                     OR title LIKE '%KEYGATE%' OR title LIKE '%KEY-GATE%')""").fetchall()
    for b in gate_blocks:
        ALERTS.append(f"🚫 OPERATOR GATE: {b['id']} {b['title'][:60]} — needs your action")

    crashing = kc.execute("""SELECT id, title, consecutive_failures FROM tasks
                             WHERE consecutive_failures >= 3 AND status != 'done'""").fetchall()
    for cr in crashing:
        ALERTS.append(f"🔄 REPEATED CRASH: {cr['id']} x{cr['consecutive_failures']} failures — {cr['title'][:50]}")
    kc.close()
except Exception:
    pass

# ── 6. Quota recovery (zai_state.json) ──
try:
    zp = os.path.expanduser("~/.hermes/bot/zai_state.json")
    if os.path.exists(zp):
        st = json.load(open(zp))
        pct = float(st.get("friend_token_pct", 0) or 0)
        ours_pct = float(st.get("ours_token_pct", 0) or 0)
        if pct > 5 or ours_pct > 5:
            ALERTS.append(f"🟢 QUOTA RECOVERY: friend={pct:.0f}% ours={ours_pct:.0f}% — free window open")
except Exception:
    pass

# ── 9. Aux-model audit surfacing (once/day when actionable) ──
try:
    audit_report = os.path.expanduser("~/.hermes/bot/aux_model_audit_report.md")
    flag_path = os.path.expanduser("~/.hermes/bot/escalation_aux_alert_date.txt")
    if os.path.exists(audit_report) and time.time() - os.path.getmtime(audit_report) < 26 * 3600:
        body = open(audit_report).read()
        if "## Actionable" in body:
            today_flag = time.strftime("%Y-%m-%d")
            last = open(flag_path).read().strip() if os.path.exists(flag_path) else ""
            if last != today_flag:
                lines = [l for l in body.splitlines() if l.startswith("- ⚠️ AUX ON PAID PATH")]
                n = len(lines)
                first = lines[0].split("—")[0].strip() if lines else ""
                ALERTS.append(f"📋 AUX AUDIT: {n} aux flow(s) on paid providers (24h) — see aux_model_audit_report.md ({first}…)")
                open(flag_path, "w").write(today_flag)
except Exception:
    pass

# ── Output ──
if ALERTS:
    # Deduplicate
    seen = set()
    unique = []
    for a in ALERTS:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    print(f"⚠️ {len(unique)} alert(s) at {time.strftime('%H:%M UTC')}:")
    for a in unique:
        print(f"  {a}")
else:
    # Silent — nothing to report
    pass
