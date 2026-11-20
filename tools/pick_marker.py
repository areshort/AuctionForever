"""Find commodity items whose cheapest listing differs in each Alliance house and has lots of time left (so it's still there to check in game)."""
import json, sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))
from probe_lib import get

HOUSES = (110, 111, 119, 123)
data = {}
for hid in HOUSES:
    st, body, _, _ = get(f'/data/wow/ruleset/1/auctions/{hid}/commodities')
    per = {}
    for a in json.loads(body).get('auctions', []) or []:
        per.setdefault(a['item']['id'], []).append(a)
    data[hid] = per

common = set.intersection(*(set(d) for d in data.values()))
cands = []
for item in common:
    rows = []
    ok = True
    for hid in HOUSES:
        ls = data[hid][item]
        lo = min(a['unit_price'] for a in ls)
        cheapest = [a for a in ls if a['unit_price'] == lo]
        if not all(a['time_left'] in ('LONG', 'VERY_LONG') for a in cheapest) or len(ls) > 25:
            ok = False
            break
        rows.append((lo, sum(a['quantity'] for a in cheapest)))
    if ok and len({r for r in rows}) == len(rows) and len({r[0] for r in rows}) == len(rows):
        cands.append((item, rows))
print(len(cands), 'candidates')
def name(item):
    st, body, _, _ = get(f'/data/wow/item/{item}', ns='static-forever-us')
    if st != 200: return '?'
    n = json.loads(body).get('name')
    return n.get('en_US') if isinstance(n, dict) else n
for item, rows in sorted(cands, key=lambda c: sum(len(data[h][c[0]]) for h in HOUSES))[:12]:
    print(item, name(item), '|', ' | '.join(f'{h}: {p}c x{q}' for h, (p, q) in zip(HOUSES, rows)))
