#!/usr/bin/env bash
# follow-review.sh — review a candidate npub before following, AI-assisted.
#
# Fetches the npub's profile + recent notes, asks ppq.ai for a recommendation
# (alignment, spam flags, suggested petname), then optionally follows via Amber
# (NIP-46 bunker) with a petname + relay hint.
#
# Usage: follow-review.sh <npub> [--follow]
# Env:   PPQ_API_KEY (required for AI), AMBER_BUNKER (bunker://... for --follow)
#        PPQ_BASE_URL (default https://api.ppq.ai), PPQ_MODEL (default gpt-5)
set -euo pipefail

NPUB="${1:?usage: follow-review.sh <npub> [--follow]}"
FOLLOW=0; [[ "${2:-}" == "--follow" ]] && FOLLOW=1

command -v nak >/dev/null || { echo "nak not found"; exit 1; }
RELAYS=(wss://relay.damus.io wss://nos.lol wss://relay.primal.net)

echo "==> fetching profile + notes for $NPUB ..."
PROFILE_JSON=$(nak req -k 0 -a "$NPUB" -l 1 "${RELAYS[@]}" 2>/dev/null | head -1 || true)
NOTES_JSONL=$(nak req -k 1 -a "$NPUB" -l 8 "${RELAYS[@]}" 2>/dev/null || true)

[[ -z "$PROFILE_JSON" ]] && { echo "no profile found for $NPUB"; exit 1; }

DOSSIER=$(python3 - "$PROFILE_JSON" <<'PY'
import json,sys
e=json.loads(sys.argv[1])
try: m=json.loads(e.get("content","{}"))
except: m={}
notes=[]
for line in sys.stdin: pass
print(json.dumps({
  "pubkey":e.get("pubkey",""),
  "name":m.get("display_name") or m.get("name",""),
  "nip05":m.get("nip05",""),
  "about":(m.get("about","") or "")[:300],
},ensure_ascii=False))
PY
)

# prepend notes into dossier
DOSSIER_FULL=$(python3 - "$DOSSIER" <<'PY'
import json,sys
d=json.loads(sys.argv[1])
notes=[]
import subprocess
notes_blob=subprocess.run(["cat"],capture_output=True,text=True).stdout if False else ""
print(json.dumps(d,ensure_ascii=False))
PY
)

echo
echo "----- profile -----"
echo "$DOSSIER" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('name'),'/ '+d.get('nip05') if d.get('nip05') else ''); print(d.get('about',''))"
echo
echo "----- recent notes -----"
echo "$NOTES_JSONL" | python3 -c "
import json,sys
n=0
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try: e=json.loads(line)
    except: continue
    c=(e.get('content') or '').strip()
    if c and not c.startswith('nostr:'):
        print(' •', c[:140]); n+=1
    if n>=6: break
" || echo "(no text notes found)"

if [[ -z "${PPQ_API_KEY:-}" ]]; then
  echo
  echo "(set PPQ_API_KEY to get an AI recommendation)"
else
  echo
  echo "==> asking ppq.ai for a recommendation ..."
  python3 - "$NPUB" "$DOSSIER" "$NOTES_JSONL" <<'PY'
import json,os,sys,urllib.request
npub,dossier_json,notes_jsonl=sys.argv[1:4]
dossier=json.loads(dossier_json)
notes=[json.loads(l) for l in notes_jsonl.splitlines() if l.strip()]
notes_text=" || ".join((e.get("content","") or "")[:160] for e in notes[:6] if not (e.get("content","") or "").startswith("nostr:"))
prompt=(f"Candidate npub to follow: {npub}\nName: {dossier.get('name')}\nNIP-05: {dossier.get('nip05')}\n"
        f"About: {dossier.get('about')}\nRecent notes: {notes_text}\n\n"
        f"Should I follow them? Give: (1) a one-line verdict KEEP/SKIP, (2) alignment + spam/low-signal flags, "
        f"(3) a suggested lowercase petname <=20 chars. Be concise.")
req=urllib.request.Request(os.environ.get("PPQ_BASE_URL","https://api.ppq.ai").rstrip("/")+"/chat/completions",
    data=json.dumps({"model":os.environ.get("PPQ_MODEL","gpt-5"),"messages":[
        {"role":"system","content":"You are a concise Nostr follow advisor."},
        {"role":"user","content":prompt}],"temperature":0.3}).encode(),
    headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["PPQ_API_KEY"]})
with urllib.request.urlopen(req,timeout=90) as r:
    print(json.loads(r.read())["choices"][0]["message"]["content"])
PY
fi

if [[ "$FOLLOW" -eq 1 ]]; then
  [[ -z "${AMBER_BUNKER:-}" ]] && { echo "set AMBER_BUNKER (bunker://...) to follow"; exit 1; }
  read -rp "petname (suggested above): " PETNAME
  read -rp "relay hint (e.g. wss://relay.damus.io): " RELAY
  RELAY="${RELAY:-wss://relay.damus.io}"
  USER_NPUB="${USER_NPUB:?set USER_NPUB to your npub so we can merge with your current follows}"
  HEXPK=$(nak decode "$NPUB" 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin)['pubkey'])" 2>/dev/null || echo "")
  [[ -z "$HEXPK" ]] && { echo "could not decode npub to hex"; exit 1; }

  echo "==> merging into your current kind-3 (approve sign in Amber) ..."
  CUR_K3=$(nak req -k 3 -a "$USER_NPUB" -l 1 "${RELAYS[@]}" 2>/dev/null | head -1 || true)
  MERGED=$(python3 - "$CUR_K3" "$HEXPK" "$RELAY" "$PETNAME" <<'PY'
import json,sys
cur,pk,relay,petname=sys.argv[1:5]
tags=[]
if cur.strip():
    try:
        e=json.loads(cur)
        tags=[t for t in e.get("tags",[]) if t and t[0]=="p"]
    except: pass
tags=[t for t in tags if not (len(t)>=2 and t[1]==pk)]   # drop existing entry for this pk
tags.append(["p",pk,relay,petname])
print(json.dumps({"tags":tags}))
PY
  )
  echo "$MERGED" | nak event -k 3 -c '{}' --sec "$AMBER_BUNKER" "${RELAYS[@]}"
  echo "done — follow published (merged, $(echo "$MERGED" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["tags"]))') total follows)"
fi
