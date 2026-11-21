"""Offline tests for the collector's sold/expired logic and history. Run: python -I test_collector.py"""
import gzip, json, os, sys, tempfile
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
# 5 of the cheapest bought (20 -> 15), so the 120c listing that's gone was bought too (not a cancel).
g2 = [good(20, 17, 100, 15, 'LONG'), good(23, 17, 130, 1, 'VERY_LONG')]
C.run(st, out, [], g2, now_ts=1_007_200)
s = C.load_state(st)
ok(s['soldprices']['17'][-1][1:] == [120, 10], 'next snapshot an hour later: 10 sold at 120c recorded')
n1 = C.item_numbers('17', s, C.market(C.listings([], g2)), 1_007_200)
ok(n1['hoursSeen'] == 1 and abs(n1['perHour'] - 15) < 1e-9, f"only the timed hour counts: {n1['hoursSeen']} h, {n1['perHour']}/h")
ok(n1['newHour'] == 0, f"a new listing far above the cheap end (130c, lowest 100c) doesn't land in front of anyone: not counted ({n1['newHour']})")
# Spans other than 1 h: 25 sold over 1.25 h and 40 over 2 h = 65 over 3.25 h = 20/h (not rates divided by hours again).
sx = {'hourly': {'99': [[1, 10, 100, 25, 250, 0, 1.25, 0], [2, 10, 100, 40, 400, 5, 2.0, 0]]}, 'soldprices': {}, 'daily': {}}
nx = C.item_numbers('99', sx, {}, 3)
ok(abs(nx['perHour'] - 20) < 1e-9, f"sales speed with 1.25 h and 2 h gaps: {nx['perHour']}/h (want 20)")
ok(abs(nx['sellThrough'] - 65 / 70) < 1e-9, f"sell-through from quantities: {nx['sellThrough']} (want {65 / 70:.4f})")
sy = {'hourly': {'98': [[1, 10, 100, 3, 30, 0, 0.25, 0], [2, 10, 100, 3, 30, 0, 0.25, 0]]}, 'soldprices': {}, 'daily': {}}
ny = C.item_numbers('98', sy, {}, 3)
ok(abs(ny['perHour'] - 12) < 1e-9, f"two 15-min gaps, 3 sold each = 12/h, not floored to an hour ({ny['perHour']})")
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
# ---- Cancels are not sales (buyers take the cheapest first).
pa = C.listings([], [good(101, 30, 100, 10, 'LONG'), good(102, 30, 200, 10, 'LONG')])
na = C.listings([], [good(101, 30, 100, 10, 'LONG')])
ev = C.compare(pa, na, 1.0)
ok(not ev.get(30, {}).get('sold') and sum(q for _, q in ev[30].get('cancel', [])) == 10,
   f"listing gone while a cheaper one is still there untouched: a cancel, not a sale ({ev.get(30)})")
ev = C.compare(pa, {}, 1.0)
ok(sum(q for _, q in ev[30]['sold']) == 20, 'both gone, cheapest first: both sold')
nb = C.listings([], [good(101, 30, 100, 4, 'LONG')])
ev = C.compare(pa, nb, 1.0)
ok(sum(q for _, q in ev[30]['sold']) == 16, f"cheapest partly bought (10 -> 4) and the next one gone: 6 + 10 sold ({ev[30]['sold']})")
# Repost: gone and an identical new listing (same price and quantity): nothing sold, nothing new.
pr = C.listings([], [good(110, 31, 100, 10, 'LONG')]); nr = C.listings([], [good(111, 31, 100, 10, 'VERY_LONG')])
ev = C.compare(pr, nr, 1.0)
ok(not ev.get(31, {}).get('sold') and not ev.get(31, {}).get('new'), f"cancel and repost of the same listing: neither a sale nor a new listing ({ev.get(31)})")
# Cancel at 200 while 100 is intact, new 7 at 200: the cancel and the repost cancel out; a new listing far above isn't counted.
nc = C.listings([], [good(101, 30, 100, 10, 'LONG'), good(103, 30, 200, 7, 'VERY_LONG'), good(104, 30, 1000, 50, 'VERY_LONG')])
ev = C.compare(pa, nc, 1.0)
ok(not ev[30].get('new'), f"repost at the cancelled price and a far-above listing: no new listings counted ({ev[30].get('new')})")
# A new listing at the cheap end (within 10% of the lowest) lands in front of sellers: counted.
nd = C.listings([], [good(101, 30, 100, 10, 'LONG'), good(102, 30, 200, 10, 'LONG'), good(105, 30, 105, 3, 'VERY_LONG')])
ev = C.compare(pa, nd, 1.0)
ok(ev[30].get('new') == 3, f"new listing at 105c with 100c lowest: counted ({ev[30].get('new')})")
# ---- Price ceiling ignores sales far above the median (cancel-looking spikes, mistakes).
sh = {'hourly': {'97': [[1, 100, 50, 30, 3000, 0, 1.0, 0]]}, 'soldprices': {'97': [[1, 100, 25], [1, 105, 5], [1, 1000, 20]]}, 'daily': {}}
nh = C.item_numbers('97', sh, {}, 2)
ok(nh['hi'] is not None and nh['hi'] <= 105, f"a few sales at 10x the median don't set the price ceiling (hi = {nh['hi']})")
# ---- Lowest-price history for the add-on: last 3 lows, and the highest lowest price over 24 h (when watched that long).
rows = [[1_000_000 + i * 3600, 200 - i, 10, 0, 0, 0, 1.0, 0] for i in range(24)]
sl = {'hourly': {'96': rows}, 'soldprices': {}, 'daily': {}}
nl = C.item_numbers('96', sl, {}, 1_000_000 + 23 * 3600)
ok(nl['lows'] == [179, 178, 177] and nl['lowHi24'] == 200, f"lows {nl['lows']}, highest lowest over 24 h {nl['lowHi24']}")
nl2 = C.item_numbers('96', {'hourly': {'96': rows[:5]}, 'soldprices': {}, 'daily': {}}, {}, 1_000_000 + 4 * 3600)
ok(nl2['lowHi24'] is None, 'under a day of hours: no 24 h figure')
ok(nl['lowRange24'] == [179, 189, 198], f"24 h range of the lowest price: 10th/50th/90th percentile ({nl['lowRange24']})")
rows3 = [[1_000_000 + i * 3600, 100, 10, 0, 0, 0, 1.0, 0] for i in range(12)]
rows3[5][1] = 5  # one stray cheap listing
nl3 = C.item_numbers('96', {'hourly': {'96': rows3}, 'soldprices': {}, 'daily': {}}, {}, 1_000_000 + 11 * 3600)
ok(nl3['lowRange24'] == [100, 100, 100] and nl2['lowRange24'] is None,
   f"one stray cheap listing doesn't widen the range ({nl3['lowRange24']}); under 12 hours: none ({nl2['lowRange24']})")
# ---- History counted the old way (cancels as sales) is dropped once, then kept.
d2 = tempfile.mkdtemp()
st4, out4 = os.path.join(d2, 's.gz'), os.path.join(d2, 'o.lua')
C.save_state(st4, {'hourly': {'17': [[1, 10, 5, 99, 990, 0, 1.0, 0]]}, 'soldprices': {'17': [[1, 10, 99]]}, 'daily': {'17': [[0, 10, 99, 0]]},
                   'compared': [[1, 1.0]], 'listings': C.listings([], g1), 'time': 1_000_000, 'timed': True, 'fmt': C.FMT})
C.run(st4, out4, [], g2, now_ts=1_003_600)
s4 = C.load_state(st4)
ok(s4.get('histv') == C.HISTV and all(r[0] != 1 for r in s4['hourly'].get('17', [])) and '17' not in s4.get('daily', {}),
   'old-style history dropped once (hourly, sales, daily)')
ok(s4['hourly'].get('17') and s4['hourly']['17'][-1][6] > 0, 'the comparison right after the reset still counts')
# The reset when Blizzard has no new snapshot yet (what the live run hit), then again with the same snapshot.
d3 = tempfile.mkdtemp()
st5, out5 = os.path.join(d3, 's.gz'), os.path.join(d3, 'o.lua')
C.save_state(st5, {'hourly': {'17': [[1, 10, 5, 99, 990, 0, 1.0, 0]]}, 'soldprices': {}, 'daily': {},
                   'listings': C.listings([], g1), 'time': 1_000_000, 'timed': True, 'fmt': C.FMT})
try:
    r1 = C.run(st5, out5, [], g1, now_ts=1_001_800)
    r2 = C.run(st5, out5, [], g1, now_ts=1_002_700)
    ok(r1 is True and r2 is False and 'AuctionForeverData' in open(out5, encoding='utf-8').read(), 'history reset with an unchanged snapshot: file rewritten, no crash')
except Exception as e:
    ok(False, f'history reset with an unchanged snapshot crashed: {e!r}')
# ---- Random-suffix gear: each version (bonus list) is its own market.
def sgear(i, item, buyout, tl, bonus=None):
    it = {'id': item, 'context': 1}
    if bonus:
        it['bonus_lists'] = [bonus]
        it['modifiers'] = [{'type': 28, 'value': 5239}]
    return {'id': i, 'item': it, 'buyout': buyout, 'quantity': 1, 'time_left': tl}


ls = C.listings([sgear(70, 10113, 9000, 'LONG', 12719), sgear(71, 10113, 3000, 'LONG', 12722), sgear(72, 10113, 5000, 'LONG'),
                 sgear(73, 10113, 9500, 'VERY_LONG', 12719)], [])
mk = C.market(ls)
ok(set(mk) == {'10113:12719', '10113:12722', 10113} and mk['10113:12719']['low'] == 9000 and mk['10113:12722']['low'] == 3000
   and mk[10113]['low'] == 5000 and mk['10113:12719']['qty'] == 2,
   f'suffix versions keyed apart ("of the Whale" 12719, "of the Bear" 12722), no suffix keeps the plain ID: {sorted(map(str, mk))}')
ok(C.key_parts('10113:12719') == (10113, '12719') and C.key_parts(10113) == (10113, None) and C.key_parts('17') == (17, None), 'key parts')
# The cheap Bear version still up doesn't make the Whale version's sale a cancel.
ev = C.compare(ls, {k: v for k, v in ls.items() if k != '70'}, 1.0)
ok(ev.get('10113:12719', {}).get('sold') == [(9000, 1)] and not ev.get('10113:12719', {}).get('cancel'),
   f"a Whale sold while a cheaper Bear is listed: a sale of the Whale ({ev.get('10113:12719')})")
# Full run: the data file has the suffix rows in sfx{} (plain items stay in items{}), names / info once per ID.
d4 = tempfile.mkdtemp()
st6, out6 = os.path.join(d4, 's.gz'), os.path.join(d4, 'o.lua')
items1 = [sgear(70, 10113, 9000, 'LONG', 12719), sgear(71, 10113, 3000, 'LONG', 12722), sgear(72, 10113, 5000, 'LONG')]
C.run(st6, out6, items1, [], now_ts=2_000_000, names_fn=lambda ids: {i: ['Wolf Rider\'s Belt', 2700, 2] for i in ids})
txt = open(out6, encoding='utf-8').read()
import re
ok(re.search(r'S\[10113\]=\{\[12719\]=\{9000,', txt) is not None and ',[12722]={3000,' in txt and 'sfx={}}' in txt and re.search(r'\nitems=\{\n\[10113\]=\{5000,', txt) is not None
   and txt.count("[10113]=\"Wolf Rider's Belt\"") == 1 and txt.count('[10113]={2700,2,0}') == 1,
   'data file: items{} has the plain listing, sfx{10113}{12719 / 12722} the suffix versions; name and info once')
ok(C.load_state(st6)['names'] == {'10113': "Wolf Rider's Belt"}, 'names looked up by item ID (not per suffix)')
# An older state (format 2) kept suffix versions under the plain ID: history dropped once, and its item auctions
# aren't compared with the new keys (no fake sales); commodities still are.
d5 = tempfile.mkdtemp()
st7, out7 = os.path.join(d5, 's.gz'), os.path.join(d5, 'o.lua')
old_ls = {'70': [10113, 9000, 1, 2, 'i'], '71': [10113, 3000, 1, 2, 'i'], '20': [17, 100, 50, 2, 'c']}
old_ls['72'] = [4444, 700, 1, 2, 'i']  # plain gear (no suffix): sold by the next snapshot
C.save_state(st7, {'histv': 2, 'fmt': 2, 'hourly': {'10113': [[1, 3000, 2, 5, 500, 0, 1.0, 0]], '17': [[1_999_000, 100, 60, 3, 300, 0, 1.0, 0]],
                                                    '4444': [[1_999_000, 700, 1, 1, 700, 0, 1.0, 0]]},
                   'soldprices': {'10113': [[1, 3000, 5]], '17': [[1_999_000, 100, 3]], '4444': [[1_999_000, 700, 1]]},
                   'daily': {'17': [[22, 100, 40, 0]], '10113': [[22, 3000, 2, 0]]}, 'compared': [[1_999_000, 1.0]], 'listings': old_ls,
                   'time': 2_000_000, 'timed': True, 'lastDay': 23})
C.run(st7, out7, items1, [good(20, 17, 100, 30, 'LONG')], now_ts=2_003_600, names_fn=lambda ids: {})
s7 = C.load_state(st7)
ok(s7['histv'] == C.HISTV and '10113' not in s7['soldprices'] and not any(k.startswith('10113') for k in s7['soldprices'])
   and s7['soldprices'].get('17', [[0, 0, 0]])[-1][1:] == [100, 20],
   f"format change: old suffix-mixed history dropped, item auctions not compared once, commodities still compared ({sorted(s7['soldprices'])})")
ok(s7['hourly']['17'][0] == [1_999_000, 100, 60, 3, 300, 0, 1.0, 0] and s7['soldprices']['17'][0] == [1_999_000, 100, 3] and s7['daily']['17'] == [[22, 100, 40, 0]]
   and s7['hourly']['4444'][0][0] == 1_999_000 and '10113' not in s7['daily'] and s7['compared'][0] == [1_999_000, 1.0],
   'format 2 -> 3: items without suffix versions keep their history (hourly, sold prices, daily, compared hours)')
ok([p[1:] for p in s7['soldprices']['4444']] == [[700, 1], [700, 1]], f"plain gear still compared at the migration: its sale counted ({s7['soldprices']['4444']})")
# ---- Restoring history a run dropped (2026-11-21): put in front of the state's own rows, once, suffix items left out.
d9 = tempfile.mkdtemp()
rp = os.path.join(d9, 'history-test.json.gz')
with gzip.open(rp, 'wt', encoding='utf-8') as f:
    json.dump({'hourly': {'17': [[10, 100, 50, 1, 100, 0, 1.0, 0], [20, 100, 50, 1, 100, 0, 1.0, 0]], '10113': [[10, 1, 1, 1, 1, 0, 1.0, 0]]},
               'soldprices': {'17': [[10, 100, 1]]}, 'daily': {'17': [[0, 100, 5, 0]]}, 'compared': [[10, 1.0], [20, 1.0]],
               'names': {'17': 'Thing'}, 'details': {'17': [5, 1]}}, f)
sr = {'histv': C.HISTV, 'hourly': {'17': [[20, 100, 50, 0, 0, 0, 0, 0], [30, 100, 50, 2, 200, 0, 1.0, 0]]}, 'soldprices': {'17': [[30, 100, 2]]},
      'daily': {}, 'compared': [[30, 1.0]], 'names': {}, 'details': {}}
n9 = C.restore_history(sr, {10113}, rp)
ok(n9 == 3 and [r[0] for r in sr['hourly']['17']] == [10, 20, 30] and sr['hourly']['17'][1][3] == 0 and sr['soldprices']['17'] == [[10, 100, 1], [30, 100, 2]]
   and sr['daily']['17'] == [[0, 100, 5, 0]] and '10113' not in sr['hourly'] and sr['compared'] == [[10, 1.0], [20, 1.0], [30, 1.0]]
   and sr['names'] == {'17': 'Thing'} and sr['restored'] == 'history-test.json.gz',
   f"restore: older rows go in front (the state's own row of the same hour wins), suffix items left out ({n9} rows)")
ok(C.restore_history(sr, {10113}, rp) == 0 and len(sr['hourly']['17']) == 3, 'restore happens once')
# ---- Items the game data API doesn't know: vendor price unknown (nil), not 0; asked again once a day.
asked = []
def api(ids):
    asked.append(sorted(ids))
    return {i: (['Linen Cloth', 13, 1] if i == 2589 else ['', 0, 1]) for i in ids}
su = {'names': {}, 'details': {}}
C.update_names(su, {2589: {}, 647: {}, '1168:12719': {}}, api, now_ts=1_000_000)
ok(asked[-1] == [647, 1168, 2589] and su['details']['647'] == [0, 1, 1_000_000] and su['details']['2589'] == [13, 1],
   f"unknown items remember when they were asked ({su['details']})")
C.update_names(su, {2589: {}, 647: {}, '1168:12719': {}}, api, now_ts=1_000_000 + 3600)
ok(len(asked) == 1, 'an hour later: not asked again')
C.update_names(su, {2589: {}, 647: {}, '1168:12719': {}}, api, now_ts=1_000_000 + 25 * 3600)
ok(asked[-1] == [647, 1168], f'a day later: only the unknown ones asked again ({asked[-1]})')
d8 = tempfile.mkdtemp()
st8, out8 = os.path.join(d8, 'state.json.gz'), os.path.join(d8, 'AuctionForeverData.lua')
C.run(st8, out8, [{'id': 1, 'item': {'id': 647}, 'buyout': 5000000, 'quantity': 1, 'time_left': 'VERY_LONG'}],
      [good(2, 2589, 13, 20, 'LONG')], now_ts=2_000_000, names_fn=api)
t8 = open(out8, encoding='utf-8').read()
ok('[647]={nil,1,0}' in t8 and '[2589]={13,1,1}' in t8, 'data file: an unknown item\'s vendor price is nil, a known one\'s is kept')
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
