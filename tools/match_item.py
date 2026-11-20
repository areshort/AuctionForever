"""Show the cheapest commodity listings of one item in each Alliance house right now."""
import json, sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))
from probe_lib import get

item = int(sys.argv[1]) if len(sys.argv) > 1 else 2589  # Linen Cloth
for hid in (110, 111, 119, 123):
    st, body, _, _ = get(f'/data/wow/ruleset/1/auctions/{hid}/commodities')
    rows = [a for a in json.loads(body).get('auctions', []) or [] if a['item']['id'] == item]
    byprice = {}
    for a in rows:
        byprice[a['unit_price']] = byprice.get(a['unit_price'], 0) + a['quantity']
    cheap = sorted(byprice.items())[:6]
    print(f'house {hid}: {len(rows)} listings; cheapest (price c: total qty) ' + ', '.join(f'{p}c: {q}' for p, q in cheap))
