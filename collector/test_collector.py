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
s = C.load_state(st)
ok(s['soldprices']['17'][-1][1:] == [100, 30], 'new snapshot: 30 sold at 100c recorded')
lua = open(out, encoding='utf-8').read()
ok(lua.startswith('-- Written by the AuctionForever collector') and '[17]=' in lua and 'house=110' in lua, 'data file written with item 17')
g3 = [good(22, 17, 110, 5, 'VERY_LONG')]
C.run(st, out, [], g3, now_ts=1_003_600 + 73 * 3600)
s = C.load_state(st)
ok(all(r[0] >= 1_003_600 + 73 * 3600 - 72 * 3600 for r in s['hourly']['17']), 'rows older than 72 h dropped')
ok(len(s.get('daily', {}).get('17', [])) >= 1, 'daily summary kept for a finished day')
n = C.item_numbers('17', s, C.market(C.listings([], g3)), 1_003_600 + 73 * 3600)
ok(n['low'] == 110 and n['qty'] == 5, 'numbers: current lowest and quantity')
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
