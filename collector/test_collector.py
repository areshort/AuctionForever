"""Offline tests for the collector's sold/expired logic and history. Run: python -I test_collector.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collector as C

fails = 0
def ok(cond, msg):
    global fails
    print(('PASS ' if cond else 'FAIL ') + msg)
    fails += 0 if cond else 1

def good(i, item, price, qty, tl): return {'id': i, 'item': {'id': item}, 'unit_price': price, 'quantity': qty, 'time_left': tl}
def gear(i, item, buyout, tl): return {'id': i, 'item': {'id': item}, 'buyout': buyout, 'quantity': 1, 'time_left': tl}

# 1. Long-bucket listing gone after 1 h: sold. Very-long gone: sold.
prev = C.listings([], [good(1, 10, 50, 20, 'LONG'), good(2, 10, 60, 5, 'VERY_LONG')])
ev = C.compare(prev, {}, 1.0)
ok(sum(q for _, q in ev[10]['sold']) == 25 and ev[10]['expired'] == 0, 'long and very long gone after 1 h: all sold')
# 2. Short bucket gone: expired (can't tell, safe side).
ev = C.compare(C.listings([], [good(3, 11, 50, 7, 'SHORT')]), {}, 1.0)
ok(ev[11]['expired'] == 7 and not ev[11]['sold'], 'short gone: counted expired')
# 3. Medium bucket gone after 1 h: one third expired, two thirds sold.
ev = C.compare(C.listings([], [good(4, 12, 50, 30, 'MEDIUM')]), {}, 1.0)
ok(abs(ev[12]['expired'] - 10) < 1e-9 and abs(ev[12]['sold'][0][1] - 20) < 1e-9, 'medium gone after 1 h: 1/3 expired, 2/3 sold')
# 4. Commodity quantity drop: the difference sold.
p = C.listings([], [good(5, 13, 40, 100, 'LONG')]); n = C.listings([], [good(5, 13, 40, 60, 'LONG')])
ev = C.compare(p, n, 1.0)
ok(ev[13]['sold'] == [(40, 40)], 'stack dropped 100 -> 60: 40 sold at its price')
# 5. Unchanged: nothing.
ok(C.compare(p, p, 1.0) == {}, 'unchanged listings: no events')
# 6. Gear listing gone: sold at its buyout.
ev = C.compare(C.listings([gear(6, 14, 9000, 'LONG')], []), {}, 1.0)
ok(ev[14]['sold'] == [(9000, 1)], 'gear gone: sold at buyout')
# 7. Bid-only listings ignored.
ok(C.listings([{'id': 7, 'item': {'id': 15}, 'bid': 100, 'quantity': 1, 'time_left': 'LONG'}], []) == {}, 'bid-only ignored')
# 8. Market ladder sorted, summed by price.
mk = C.market(C.listings([], [good(8, 16, 30, 5, 'LONG'), good(9, 16, 20, 3, 'LONG'), good(10, 16, 30, 2, 'LONG')]))
ok(mk[16]['low'] == 20 and mk[16]['ladder'] == [(20, 3), (30, 7)] and mk[16]['qty'] == 10, 'ladder: cheapest first, same price summed')
# 9. Full run: unchanged snapshot is skipped; a new one records sales; history pruned after 72 h.
d = tempfile.mkdtemp()
st, out = os.path.join(d, 's.gz'), os.path.join(d, 'o.lua')
g1 = [good(20, 17, 100, 50, 'LONG'), good(21, 17, 120, 10, 'VERY_LONG')]
ok(C.run(st, out, [], g1, now_ts=1_000_000) is True, 'first run writes')
ok(C.run(st, out, [], g1, now_ts=1_001_800) is False, 'same snapshot again: skipped')
g2 = [good(20, 17, 100, 20, 'LONG'), good(21, 17, 120, 10, 'VERY_LONG')]
C.run(st, out, [], g2, now_ts=1_003_600)
ok('17' not in C.load_state(st).get('soldprices', {}), 'comparison starting from the very first snapshot is not counted')
g2 = [good(20, 17, 100, 20, 'LONG'), good(23, 17, 130, 1, 'VERY_LONG')]
C.run(st, out, [], g2, now_ts=1_007_200)
s = C.load_state(st)
ok(s['soldprices']['17'][-1][1:] == [120, 10], 'next snapshot an hour later: 10 sold at 120c recorded')
n1 = C.item_numbers('17', s, C.market(C.listings([], g2)), 1_007_200)
ok(n1['hoursSeen'] == 1 and abs(n1['perHour'] - 10) < 1e-9, f"only the timed hour counts: {n1['hoursSeen']} h, {n1['perHour']}/h")
ok(n1['newHour'] == 1, f"new listings per hour: 1 posted in that hour ({n1['newHour']})")
ok('"newHour"' in open(out, encoding='utf-8').read().split('items=')[0], 'data file lists the newHour field')
ev5 = C.compare({}, C.listings([], [good(90, 18, 50, 7, 'LONG')]), 1.0)
ok(ev5[18].get('new') == 7 and not ev5[18]['sold'], 'listing not seen before: counted as newly posted')
ok('hours=1.0,' in open(out, encoding='utf-8').read(), 'data file says 1 h of sales watched')
lua = open(out, encoding='utf-8').read()
ok(lua.startswith('-- Written by the AuctionForever collector') and '[17]=' in lua and 'house=110' in lua, 'data file written with item 17')
g3 = [good(22, 17, 110, 5, 'VERY_LONG')]
C.run(st, out, [], g3, now_ts=1_007_200 + 73 * 3600)
s = C.load_state(st)
ok(all(r[0] >= 1_003_600 + 73 * 3600 - 72 * 3600 for r in s['hourly']['17']), 'rows older than 72 h dropped')
ok(len(s.get('daily', {}).get('17', [])) >= 1, 'daily summary kept for a finished day')
n = C.item_numbers('17', s, C.market(C.listings([], g3)), 1_007_200 + 73 * 3600)
ok(n['low'] == 110 and n['qty'] == 5, 'numbers: current lowest and quantity')
# Item names: looked up once for new items, written into the data file, never asked again.
asked = []
def fake_names(ids):
    asked.extend(ids)
    return {i: (['Linen "Cloth"', 7, 1] if i == 17 else ['', 0, 1]) for i in ids}
st2, out2 = os.path.join(d, 'n_state.json.gz'), os.path.join(d, 'n_data.lua')
C.run(st2, out2, [], g1, now_ts=2_000_000, names_fn=fake_names)
body = open(out2, encoding='utf-8').read()
ok('names={' in body and '[17]="Linen \\"Cloth\\""' in body, 'names written into the data file (quotes escaped)')
ok('info={' in body and '[17]={7,1,1}' in body, 'vendor price, quality and commodity flag written into the data file')
first = len(asked)
C.run(st2, out2, [], g2, now_ts=2_003_600, names_fn=fake_names)
ok(first > 0 and all(i not in asked[first:] for i in asked[:first]), 'known names are not looked up again')
# Unchanged snapshot but names missing (e.g. first run after this update): names added and the file rewritten.
st3, out3 = os.path.join(d, 'm_state.json.gz'), os.path.join(d, 'm_data.lua')
C.run(st3, out3, [], g1, now_ts=3_000_000)
ok(C.run(st3, out3, [], g1, now_ts=3_001_800, names_fn=fake_names) is True and 'Linen' in open(out3, encoding='utf-8').read(),
   'unchanged snapshot: missing names still added and written')
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
