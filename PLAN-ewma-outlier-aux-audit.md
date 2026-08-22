# PLAN: EWMA Spend-Outlier Detection + Auxiliary-Model Audit

Date: 2026-08-22 · Status: DONE (all checks executed + verified 2026-08-22)
Related: `PLAN-routstr-upstreams-lnurl.md`, `docs/GAP-ROUTSTR-STACK.md`, escalation cron (15 min)

## Goal

Two additions to the cost-escalation layer, both LLM-free and script-only:

- **A. EWMA spend-outlier alert** — catch "normal-looking" hourly spend that is
  actually 10-150x baseline (today's routstrd failover bleed: $10.61/h vs
  $0.07/h Kalman-predicted).
- **B. Auxiliary-model routing audit** — find compression/summary/title/image
  calls landing on paid providers and quantify the savings of rerouting.

## Motivation (measured 2026-08-22)

- $75.87 daily paid spend, $10.61/h peak — 1,317 calls forced to paid
  routstrd/OR failover (`zai_exhausted_routstrd_failover`) because both z.ai
  keys were quota-dead.
- Existing Kalman filter tracks TOKEN burn on quota windows, not $ spend.
  Cost = kalman.burn_rate_tph × price/M — trivially composable.

## A. EWMA outlier detection — checklist

- [x] A1. State file `~/.hermes/bot/escalation_ewma_state.json`
      (`ewma`, `samples` last 24 hourly spends, `last_sample_hour`,
      `last_alert_hour`); create on first run; corrupt → reset cold.
- [x] A2. Hourly sampling: on UTC hour rollover, push completed hour's paid
      spend; update EWMA (alpha=0.3, ~5h memory).
- [x] A3. Alert #8 SPEND OUTLIER: trailing-hour paid spend >
      max(3x EWMA, mean+2sigma) → alert with ratio.
- [x] A4. Kalman composition: predicted $/h = burn_rate_tph × price/M
      (from zai_state.json); actual/predicted > 10x → append
      "paid failover dominating (zai quota dead)" reason.
- [x] A5. Guards: cold start (no alert < 6 samples); re-arm (same outlier
      type max once per 2h).
- [x] A6. Dry-run against live DB — must fire on current data (~16x).
- [x] A7. Synthetic-state tests: cold start, re-arm suppression.

## B. Auxiliary-model audit — checklist

- [x] B1. Inspect `zai_usage.db` schema; discover non-chat aux call markers
      (compression, summaries, session titles, image analysis).
- [x] B2. Classify aux traffic by model/provider/price tier; count calls/day.
- [x] B3. Report script `~/.hermes/profiles/manager/scripts/aux-model-audit.py`:
      writes `~/.hermes/bot/aux_model_audit_report.md`; surfaces paid-path
      aux traffic once via escalation output; includes est. $/day savings
      if rerouted to node z.ai.
- [x] B4. Report-only (no auto rerouting); actual config changes become a
      follow-up task with operator sign-off.
- [x] B5. Run once, review report, then wire daily quiet cron line.

## C. Delivery / reproducibility — checklist

- [x] C1. Extend `cost-escalation-check.py` with A (no new cron — rides
      the 15-min escalation cron).
- [x] C2. Add daily crontab line for B (quiet, appends to report).
- [x] C3. Mirror both scripts into `~/tollgate-infrastructure-kit`
      (role files, pattern like buzz_signal_bridge / routstr_node_access).
- [x] C4. Update kit plan doc; commit + push to buzz-audio-bridge-docs.

## Outcome (2026-08-22)

- Live verification: outlier fired at $5.45/h = 10.9x EWMA; cold start,
  re-arm suppression, and once-daily aux-audit surfacing all tested.
- Aux audit headline: **$81.83/24h of aux (NULL-session) traffic on paid
  providers** — 1,287 routstrd calls (~$74.69, 74M prompt tokens,
  compression signature) + 607 OpenRouter calls ($7.14). Node-z.ai
  equivalent would be ~$0.04. Follow-up task: route aux calls
  (compression/summary/title) through the routstr node z.ai provider —
  needs operator sign-off before config changes.
- Delivered via playbook `50-cost-escalation-ewma.yml`
  (role hermes_cost_escalation; idempotent rerun changed=0 verified).

## Out of scope

- CG-12a proper Kalman-cost composition (stays queued).
- Auto-rerouting of aux models (audit recommends, human decides).
