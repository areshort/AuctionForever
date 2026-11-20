"""Which Alliance house is PvP? Compare rulesets' names, house lists, and whether a house's data differs by ruleset."""
import json, sys, hashlib
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, __import__('os').path.dirname(__file__))
from probe_lib import get

for rs in (1, 2, 3, 15):
    st, body, _, _ = get(f'/data/wow/ruleset/{rs}')
    j = json.loads(body)
    nm = j.get('name', {})
    print('ruleset', rs, nm.get('en_US') if isinstance(nm, dict) else nm, '| keys:', [k for k in j if k not in ('_links', 'name')])
    st, body, _, _ = get(f'/data/wow/ruleset/{rs}/auctions/')
    ids = [a['id'] for a in json.loads(body).get('auctions', [])]
    print('   houses', ids)

for hid in (110, 111, 119, 123):
    sigs = []
    for rs in (1, 2):
        st, body, _, _ = get(f'/data/wow/ruleset/{rs}/auctions/{hid}')
        a = json.loads(body).get('auctions', []) or []
        sigs.append((len(a), hashlib.md5(json.dumps(sorted(x['id'] for x in a[:2000])).encode()).hexdigest()[:8]))
    print('house', hid, 'ruleset 1 vs 2:', sigs, 'same' if sigs[0] == sigs[1] else 'DIFFERENT')
