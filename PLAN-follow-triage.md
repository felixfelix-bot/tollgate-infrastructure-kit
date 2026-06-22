# Plan: AI-Assisted Follow-List Triage + Curated Purge + Helper

## Context

User's npub `npub1c03rad0r6q833vh57kyd3ndu2jry30nkr0wepqfpsm05vq7he25slryrnw`
has a raw kind-3 follow list: 225 follows, none with petnames or relay hints
(217 of 225 profiles resolvable). Goal: identify, triage into sets using AI,
curate (keep a subset with enriched tags), purge the rest, and build a reusable
AI-assisted follow-review helper.

Signing via **Amber** (Android NIP-46 signer): `nak event --sec "bunker://..."`
— the nsec never leaves Amber. AI via **ppq.ai** (OpenAI-compatible API).

## Workflow

### Phase 1 — Enrich follows into dossiers (automated, read-only)
- [ ] 1.1 Fetch ~8 recent kind-1 notes per followed pubkey (batched via `nak req`)
- [ ] 1.2 Fetch NIP-51 follow-pack membership (kind 39000-39009) per pubkey
- [ ] 1.3 Compute mutuals / WoT overlap (how many of user's follows also follow each)
- [ ] 1.4 Write `follows-enriched.jsonl` (profile + notes_sample + packs + mutuals)

### Phase 2 — Criteria rubric (conversation)
- [ ] 2.1 Capture user's "what I'm looking for" (topics, signal-type, recency, engagement)
- [ ] 2.2 Capture "what to avoid" (spam, memes-only, inactive)
- [ ] 2.3 Encode as a scoring rubric prompt

### Phase 3 — AI clustering via ppq.ai
- [ ] 3.1 `scripts/follow-triage.py` — batch dossiers + rubric to ppq.ai
- [ ] 3.2 Categorise 217 npubs into named sets + per-npub rationale + suggested petname
- [ ] 3.3 Output `triage.json` (sets: keep clusters, borderline, purge)
- [ ] 3.4 User reviews/merges/splits sets

### Phase 4 — Curated purge (signed by Amber)
- [ ] 4.1 Backup current kind-3 to `follows-backup.json`
- [ ] 4.2 Fetch each keeper's kind-10002 for relay hints
- [ ] 4.3 Confirm AI-suggested petnames with user
- [ ] 4.4 Build new kind-3 with keep-set (`-p <pk>;<relay>;<petname>`)
- [ ] 4.5 Publish via `nak event -k 3 --sec "bunker://..." <relays>` (Amber approval)
- [ ] 4.6 Verify agg relay reconciles down to keep-set

### Phase 5 — `follow-review` helper (reusable, ppq.ai)
- [ ] 5.1 `scripts/follow-review.sh <npub>` — fetch profile + notes + WoT overlap
- [ ] 5.2 Call ppq.ai for recommendation (alignment, spam flags, suggested petname)
- [ ] 5.3 Offer to follow via Amber with petname + relay hint

### Phase 6 — Follow-pack ingestion (optional)
- [ ] 6.1 `scripts/follow-pack-review.sh <pack-event-id>` — pull NIP-51 pack
- [ ] 6.2 Run each candidate through follow-review; bulk-add approved

## Inputs needed from user
- ppq.ai API key (`ppq_...`) — for Phase 3/5
- Amber bunker URI (`bunker://...`) — for Phase 4
- Criteria (Phase 2): what to seek / avoid

## Key Config
| Item | Value |
|------|-------|
| User npub | npub1c03rad0r6q833vh57kyd3ndu2jry30nkr0wepqfpsm05vq7he25slryrnw |
| Current follows | 225 (217 resolved) |
| AI provider | ppq.ai (https://api.ppq.ai/chat/completions, OpenAI-compatible) |
| Signer | Amber (NIP-46 bunker, `nak --sec bunker://...`) |
| Agg relay synergy | agg.orangesync.tech reconciles to the new keep-set |
