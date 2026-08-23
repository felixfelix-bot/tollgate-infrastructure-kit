#!/usr/bin/env python3
"""
issue_ecash.py — client-side Cashu minting for the gRPC-paid production mint.
Pure-Python secp256k1 point math (no C deps beyond coincurve-free stdlib).

Flow (operator):
  1) ./issue_ecash.py quote 5000            -> prints quote id
  2) mark quote PAID via mint-orchestrator gRPC (issue_to_friend.py)
  3) ./issue_ecash.py mint <quote_id>        -> /tmp/sitarani_token.txt (cashuA)
  4) ./issue_ecash.py swap                   -> verifies proofs spendable at mint

hash_to_curve per Cashu spec (matches cashu SDK core/crypto/b_dhke.py):
  Y = lift_x_even(sha256(sha256("Secp256k1_HashToCurve_Cashu_" || secret) || le32(counter)))
"""
import base64, hashlib, json, secrets, sys, urllib.request, urllib.error

MINT = "https://mint.orangesync.tech"
P = 2**256 - 2**32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
TAG = b"Secp256k1_HashToCurve_Cashu_"
G = (GX, GY)

def sha(b): return hashlib.sha256(b).digest()

def _inv(a): return pow(a, P - 2, P)

def pt_add(p1, p2):
    if p1 is None: return p2
    if p2 is None: return p1
    x1, y1 = p1; x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0: return None
    if p1 == p2:
        l = (3 * x1 * x1) * _inv(2 * y1) % P
    else:
        l = (y2 - y1) * _inv((x2 - x1) % P) % P
    x3 = (l * l - x1 - x2) % P
    y3 = (l * (x1 - x3) - y1) % P
    return (x3, y3)

def pt_mul(k, pt):
    r = None
    k %= N
    while k:
        if k & 1: r = pt_add(r, pt)
        pt = pt_add(pt, pt); k >>= 1
    return r

def pt_bytes(pt):
    x, y = pt
    return (b"\x02" if y % 2 == 0 else b"\x03") + x.to_bytes(32, "big")

def pt_parse(b33):
    x = int.from_bytes(b33[1:33], "big")
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if (y * y) % P != y2: raise ValueError("not on curve")
    if y % 2 != b33[0] % 2: y = P - y
    return (x, y)

def lift_x_even(x):
    if x >= P: return None
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if (y * y) % P != y2: return None
    if y % 2: y = P - y
    return (x, y)

def hash_to_curve(secret: bytes):
    h1 = sha(TAG + secret)
    counter = 0
    while True:
        x = int.from_bytes(sha(h1 + counter.to_bytes(4, "little")), "big")
        pt = lift_x_even(x)
        if pt is not None: return pt
        counter += 1

def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(MINT + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def get_keyset():
    st, data = http("GET", "/v1/keys")
    if st != 200: raise SystemExit(f"keys failed {st}: {data}")
    for ks in data["keysets"]:
        if ks.get("unit") == "sat" and ks.get("active", True):
            return ks["id"], {int(a): pt_parse(bytes.fromhex(k)) for a, k in ks["keys"].items()}
    raise SystemExit("no active sat keyset: " + json.dumps(data)[:300])

def split_amount(amount):
    out, a = [], amount
    while a:
        p = 1 << (a.bit_length() - 1)
        out.append(p); a -= p
    return out

def blinded_messages(amounts, ksid):
    outs, meta = [], []
    for a in amounts:
        secret = secrets.token_hex(32)          # hex STRING — proof transmits ASCII
        Y = hash_to_curve(secret.encode())      # hash the ASCII bytes (mint-side does same)
        r = secrets.randbelow(N - 1) + 1
        B_ = pt_add(Y, pt_mul(r, G))
        outs.append({"amount": a, "id": ksid, "B_": pt_bytes(B_).hex()})
        meta.append((a, secret, r))
    return outs, meta

def unblind(sigs, meta, keys):
    proofs = []
    for s, (a, secret, r) in zip(sigs, meta):
        C_ = pt_parse(bytes.fromhex(s["C_"]))
        K = keys[a]
        C = pt_add(C_, pt_mul((N - r) % N, K))  # C = C_ - r*K
        proofs.append({"secret": secret, "C": pt_bytes(C).hex(), "amount": a, "id": s["id"]})
    return proofs

def token_from_proofs(proofs):
    inner = {"token": [{"mint": MINT, "proofs": proofs}], "unit": "sat",
             "memo": "operator issuance"}
    b = json.dumps(inner, separators=(",", ":")).encode()
    return "cashuA" + base64.urlsafe_b64encode(b).decode().rstrip("=")

def cmd_quote(amount):
    st, data = http("POST", "/v1/mint/quote/bolt11", {"amount": amount, "unit": "sat"})
    print(st, json.dumps(data)[:300])
    if st in (200, 201):
        print("QUOTE_ID=" + data["quote"])

def cmd_mint(quote_id, amount=5000):
    ksid, keys = get_keyset()
    outs, meta = blinded_messages(split_amount(amount), ksid)
    st, data = http("POST", "/v1/mint/bolt11", {"quote": quote_id, "outputs": outs})
    print(st, json.dumps(data)[:300])
    if st != 200: raise SystemExit("mint failed")
    proofs = unblind(data["signatures"], meta, keys)
    open("/tmp/sitarani_token.txt", "w").write(token_from_proofs(proofs))
    open("/tmp/proofs.json", "w").write(json.dumps(proofs))
    print(f"OK minted {sum(p['amount'] for p in proofs)} sats -> /tmp/sitarani_token.txt")

def cmd_swap():
    proofs = json.load(open("/tmp/proofs.json"))
    ksid, keys = get_keyset()
    total = sum(p["amount"] for p in proofs)
    outs, meta = blinded_messages(split_amount(total), ksid)
    st, data = http("POST", "/v1/swap", {"inputs": proofs, "outputs": outs})
    print(st, json.dumps(data)[:300])
    if st != 200: raise SystemExit("SWAP FAILED — proofs invalid")
    new_proofs = unblind(data["signatures"], meta, keys)
    open("/tmp/proofs.json", "w").write(json.dumps(new_proofs))
    open("/tmp/sitarani_token.txt", "w").write(token_from_proofs(new_proofs))
    print(f"SWAP OK — {total} sats re-issued, proofs verified spendable at mint")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "quote": cmd_quote(int(sys.argv[2]))
    elif cmd == "mint": cmd_mint(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 5000)
    elif cmd == "swap": cmd_swap()
    else: print(__doc__)
