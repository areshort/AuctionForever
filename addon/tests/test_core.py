"""Offline tests for Core.lua, run in LuaJIT (Lua 5.1, like WoW) through lupa.
Run: C:\\Users\\RyanPC\\wow-addon-dev\\venv\\Scripts\\python -I test_core.py"""
import os, sys
from lupa.luajit21 import LuaRuntime

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HERE), 'AuctionForever')
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute('time = os.time')
core_src = open(os.path.join(ADDON, 'Core.lua'), encoding='utf-8').read()
lua.execute('function LoadCore(src) local f = assert(loadstring(src, "Core.lua")); f("AuctionForever", {}) end')
lua.globals().LoadCore(core_src)
fails = 0


def ok(cond, msg):
    global fails
    print(('PASS ' if cond else 'FAIL ') + msg)
    fails += 0 if cond else 1


L = lua.eval
# A healthy fast seller: 40 sold an hour, 72 h watched, sells in nearly every hour.
lua.execute('''function MakeItem(over)
  local I = { id = 1, low = 500, qty = 300, med = 1000, hi = 1100, med24 = 1000, medAll = 1000, perHour = 40, medHour = 40,
    hoursSeen = 72, hoursWithSales = 70, sales = 500, sellThrough = 0.8, qtyDayAgo = 280,
    ladder = { {500, 10}, {950, 30}, {1000, 100}, {1050, 160} } }
  for k, v in pairs(over or {}) do I[k] = v end
  return I
end''')
C = 'AuctionForever.Core'

ok(L(f'{C}.Status(MakeItem())') == 'good', 'healthy fast seller: good')
ok(L(f'{C}.Status(MakeItem({{sales = 4}}))') == 'warming up', 'few sales: warming up')
ok(L(f'{C}.Status(MakeItem({{hoursWithSales = 20}}))') == 'slow', 'sells in few hours: slow')
ok(L(f'{C}.Status(MakeItem({{sellThrough = 0.4}}))') == 'slow', 'mostly expires: slow')
ok(L(f'{C}.Status(MakeItem({{qty = 2000}}))') == 'flooded', 'more than a day of stock: flooded')
ok(L(f'{C}.Status(MakeItem({{med24 = 850}}))') == 'falling', 'last-24 h price 15% down: falling')

# Fill time: 10 below 950 + my 20 = 30 at 40/h = 0.75 h
ok(abs(L(f'{C}.FillHours(MakeItem().ladder, 949, 20, 40)') - 0.75) < 1e-9, 'fill hours counts stock below my price')
# Post price for 2 h with 20 to sell: 1049 has 140 below + 20 = 4 h (too slow); 999 has 40 below +20 = 1.5 h: ok.
p, f = L(f'{C}.PostPrice(MakeItem(), 20, 2)')
ok(p == 999 and abs(f - 1.5) < 1e-9, f'2 h post price is the highest that fills in time: {p}')
# 8 h allows 1049 (fill 4 h), ceiling 1100 has 300 below -> 8 h: ok too -> 1100
p8, f8 = L(f'{C}.PostPrice(MakeItem(), 20, 8)')
ok(p8 == 1100, f'8 h: up to the ceiling: {p8}')
ok(L(f'{C}.PostPrice(MakeItem({{hi = 900, med = 900}}), 20, 24)')[0] == 900, 'never above what buyers recently paid')
# Duration by expected earnings: chance it sells x price after the cut, minus the deposit lost when it doesn't.
# 2 h: 999, 8 h: 1100 (10.1% more) -> 8 h even at 80% sell-through (the old rule needed 90%).
h, idx, price, fill = L(f'{C}.ChooseDuration(MakeItem(), 20)')
ok(h == 8 and idx == 2 and price == 1100, f'10%+ more at 8 h, 80% sell: {h} h at {price}')
# A big deposit for 8 h that's lost 20% of the time outweighs the gain: stays 2 h.
lua.execute(f"{C}.Deposit = function(I, H, Q) return H == 2 and 100 or 20000 end")
ok(L(f'{C}.ChooseDuration(MakeItem(), 20)')[0] == 2, 'deposit risk outweighs the higher price: 2 h')
lua.execute(f"{C}.Deposit = nil")
# Same price at every duration: shortest.
ok(L(f'{C}.ChooseDuration(MakeItem({{ladder = {{ {{500, 10}} }}, hi = 600, med = 600}}), 5)')[0] == 2, 'no gain from longer: 2 h')
# Selling price with other sellers posting: everything cheaper than you plus your stack must clear within 2 h at
# (sales speed x 75%) - new listings per hour, since new listings land in front of you.
# MakeItem: 40 sold/h -> 30/h planned. Ladder 10 at 5s, 30 at 9s 50c, 100 at 10s, 160 at 10s 50c.
def sp(over, qty, floor=1):
    return L(f'{C}.SellPrice(MakeItem({over}), {qty}, {floor})')
P_, H_, I_, Q_, F_ = sp('{newHour = 0}', 20)
ok(P_ == 999 and H_ == 2 and Q_ == 20 and not F_, f'nobody posting: can sit above the cheap 40 (they clear in 1.3 h): {P_}, {H_} h')
P_, H_, I_, Q_, F_ = sp('{newHour = 25}', 20)
ok(P_ == 499 and H_ == 8 and F_ is None, f'25 new/h leaves 5/h: 1c under the cheapest, 8 h for 20 units: {P_}, {H_} h')
P_, H_, I_, Q_, F_ = sp('{newHour = 40}', 20)
ok(P_ == 499 and F_ == 'flooding', f'more posted than sold: 1c under the cheapest, flagged ({F_})')
P_, H_, I_, Q_, F_ = sp('{}', 20)
ok(P_ == 499 and F_ == 'guess', f'new listings not measured yet: 1c under the cheapest ({F_})')
P_, H_, I_, Q_, F_ = sp('{newHour = 25}', 20, 600)
ok(P_ == 600 and F_ == 'loss', f'in front would be below your floor: floor, flagged ({P_}, {F_})')
P_, H_, I_, Q_, F_ = sp('{newHour = 0}', 1000)
ok(P_ == 499 and H_ == 24 and Q_ == 720, f'more than a day of sales: in front, 24 h, posts what sells in a day ({P_}, {H_}, {Q_})')
ok(sp('{newHour = 0, ladder = {}}', 5)[0] == 1100, 'nothing listed: what buyers recently paid')
# Quantity: 2 h at 999 -> room 40*2 - 40 below = 40
ok(L(f'{C}.PostQuantity(MakeItem(), 100, 2, 999)') == 40, 'post only what sells in time')
# Budget
ok(L(f'{C}.Budget(100000)') == 50000, '10g -> 5g budget')
ok(L(f'{C}.Budget(15000)') == 5000, '1.5g -> 0.5g (keep 1g)')
ok(L(f'{C}.Budget(8000)') == 0, 'under 1g: nothing')
# Flip options: you must be the cheapest after buying, reselling 1c under what's left.
# Buy 10 at 5s -> resell 949: floor(949*10*0.95) - 5000 = 4015. Buy those + 30 at 9s 50c -> resell 999:
# floor(999*40*0.95) - 33500 = 4462 (best).
lua.execute(f'O = {C}.FlipOptions(MakeItem(), 500000); Flip = {C}.Flip(MakeItem(), 500000)')
ok(L('O[1].buyQty == 10 and O[1].resell == 949 and O[1].profit == 4015'), f'first option: resell 1c under the next listing ({L("O[1].resell")})')
ok(L('Flip.buyQty == 40 and Flip.buyUpTo == 950 and Flip.resell == 999 and Flip.profit == 4462'), f'best: buy both cheap levels, resell under 10s ({L("Flip.resell")}, {L("Flip.profit")})')
# Only the 12 cheapest levels are kept: buying through all of them, with more listings above, isn't a flip
# (seen with Minor Mana Potion: "resell at 6s 15c" after buying every known level).
lua.execute(f"Trunc = {C}.FlipOptions(MakeItem({{ ladder = {{ {{500, 10}}, {{950, 30}} }}, qty = 300 }}), 500000)")
ok(L('#Trunc') == 1 and L('Trunc[1].buyQty') == 10, f'more listings above the kept levels: never buys out the last known level ({L("#Trunc")} options)')
lua.execute(f"All = {C}.FlipOptions(MakeItem({{ ladder = {{ {{500, 10}}, {{950, 30}} }}, qty = 40 }}), 500000)")
ok(L('#All') == 2, 'every listing known: buying them all is allowed')
# Medium Leather (real ladder): 20 cheap at 91c, then 207 at 98c. Reselling at 97c doesn't pay; buying the 98c ones
# too is over budget, and a partly bought level leaves cheaper stock in front of you. No flip.
lua.execute("""Leather = AuctionForever.Core.Flip(MakeItem({ low = 91, qty = 6204, med = 118, hi = 135, med24 = 118, medAll = 118,
  perHour = 1826, medHour = 1826, ladder = { {91, 20}, {98, 207}, {99, 14}, {100, 986}, {101, 152}, {102, 437} } }), 14982)""")
ok(L('Leather == nil'), 'Medium Leather case: buying 1% of the market and posting behind 2000 cheaper units is not a flip')
# Same cheap listing, but a wall of stock right above it: no flip.
lua.execute('Wall = AuctionForever.Core.Flip(MakeItem({ ladder = { {500, 10}, {510, 2000} }, qty = 900 }), 500000)')
ok(L('Wall == nil'), 'cheap listing with lots of stock just above: skipped')
ok(L('AuctionForever.Core.Flip(MakeItem({ sales = 3 }), 500000) == nil'), 'warming up: no flip')
# Value per day and money text
ok(L(f'{C}.ValuePerDay(MakeItem())') == 1000 * 40 * 24, 'value per day = price x sold per day')
ok(L(f'{C}.Money(12345)') == '1g 23s' and L(f'{C}.Money(250)') == '2s 50c' and L(f'{C}.Money(7)') == '7c', 'money text')
# Loot value: 30 Silverleaf-like, 2 h room 40 -> all at post price after cut
v = L(f'{C}.LootValue(MakeItem(), 30, 1)')
ok(v > 0 and v <= 30 * 1100 * 0.95, f'loot value at what it would sell for: {v}')

# Comparing an earlier ladder with a fresh scan ({price = qty})
CL = f'{C}.CompareLadders'
r = L(f'{{{CL}({{{{100,10}},{{110,20}},{{120,30}}}}, {{[110]=5, [120]=30}})}}')
ok(list(r.values()) == [25, 100*10 + 110*15, 2, 110], f'cheapest gone + next level partly: 25 sold {list(r.values())}')
r = L(f'{{{CL}({{{{100,10}},{{110,20}}}}, {{[90]=50, [100]=4, [110]=20}})}}')
ok(list(r.values())[0] == 6, 'a new cheaper listing does not hide real sales')
r = L(f'{{{CL}({{{{100,10}},{{110,20}}}}, {{[100]=10, [110]=0}})}}')
ok(list(r.values())[0] == 0, 'level above an untouched one vanished: cancelled, not sold')
r = L(f'{{{CL}({{{{100,10,4}},{{110,20}}}}, {{[110]=20}})}}')
ok(list(r.values())[0] == 6, 'listings that were about to expire are not counted as sold')
# Merging scan observations into an item with no cloud sales yet
lua.execute("""AuctionForeverDB = { obs = { [1] = { {0, 0.5, 30, 30000, 4, 1100} } } }""")
lua.execute("MI = AuctionForever.Core.MergeScan(MakeItem({ perHour = 0, hoursSeen = 0, hoursWithSales = 0, sales = 0, med = nil, hi = nil, med24 = nil, medAll = nil, sellThrough = nil, soldQty = 0, qty = 20 }), 0)")
ok(abs(L('MI.perHour') - 60) < 1e-9 and L('MI.med') == 1000 and L('MI.hi') == 1100, f"scan only: 30 sold in 30 min = {L('MI.perHour')}/h at {L('MI.med')}")
ok(L(f'{C}.Status(MI)') == 'early', 'one window with sales: "early", not yet a steady seller: ' + L(f'{C}.Status(MI)'))
FRESH = "MakeItem({ perHour = 0, hoursSeen = 0, hoursWithSales = 0, sales = 0, med = nil, hi = nil, med24 = nil, medAll = nil, sellThrough = nil, soldQty = 0, qty = 20 })"
# Two windows with sales -> steady seller; rate = the lower of the two.
lua.execute("AuctionForeverDB = { obs = { [1] = { {0, 0.5, 30, 30000, 4, 1100, 400}, {0, 0.5, 20, 20000, 3, 1050, 400} } } }")
lua.execute(f"MI = AuctionForever.Core.MergeScan({FRESH}, 0)")
ok(L(f'{C}.Status(MI)') == 'good' and abs(L('MI.perHour') - 40) < 1e-9, f"two windows: steady seller at the lower rate ({L('MI.perHour')}/h)")
# Three windows: the median, so one huge window doesn't set the rate.
lua.execute("AuctionForeverDB = { obs = { [1] = { {0, 0.5, 30, 30000, 4, 1100, 4000}, {0, 0.5, 20, 20000, 3, 1050, 4000}, {0, 0.5, 75, 75000, 9, 1100, 4000} } } }")
lua.execute(f"MI = AuctionForever.Core.MergeScan({FRESH}, 0)")
ok(abs(L('MI.perHour') - 60) < 1e-9 and L('MI.spikes') == 0, f"three windows (60, 40, 150/h): median rate, not the average ({L('MI.perHour')}/h)")
# Burst: Runecloth-like window (7,888 in 43 min) against usual windows of ~40/h is left out.
lua.execute("AuctionForeverDB = { obs = { [1] = { {0, 0.72, 7888, 7888*505, 12, 510, 21373}, {0, 0.5, 20, 20000, 3, 1050, 13989}, {0, 0.5, 22, 22000, 3, 1050, 13900} } } }")
lua.execute(f"MI = AuctionForever.Core.MergeScan({FRESH}, 0)")
ok(L('MI.spikes') == 1 and abs(L('MI.perHour') - 40) < 1e-9 and L(f'{C}.Status(MI)') == 'good',
   f"burst (7,888 in 43 min vs ~40/h usual) left out: {L('MI.perHour')}/h, status {L(f'{C}.Status(MI)')}")
# A busy hour at the usual pace is NOT a burst, even if it's a big share of the stock (Linen: 26% in 55 min).
lua.execute("AuctionForeverDB = { obs = { [1] = { {0, 0.92, 4353, 4353*29, 3, 30, 16427}, {0, 1.0, 4000, 4000*29, 3, 30, 12000}, {0, 1.0, 4500, 4500*29, 3, 30, 12500} } } }")
lua.execute(f"MI = AuctionForever.Core.MergeScan({FRESH}, 0)")
ok(L('MI.spikes') == 0 and L(f'{C}.Status(MI)') in ('good', 'flooded'), f"busy but usual pace (a quarter of the stock in an hour): kept, {L('MI.perHour'):.0f}/h")
# One window alone can't be judged (no usual rate yet), and it can't make a steady seller either.
lua.execute("AuctionForeverDB = { obs = { [1] = { {0, 0.72, 7888, 7888*505, 12, 510, 21373} } } }")
lua.execute(f"MI = AuctionForever.Core.MergeScan({FRESH}, 0)")
ok(L('MI.spikes') == 0 and L(f'{C}.Status(MI)') == 'early', 'one window: no burst verdict yet, but only "early"')
# Burst then a normal window: two windows -> the lower (normal) rate is used.
lua.execute("AuctionForeverDB = { obs = { [1] = { {0, 0.72, 7888, 7888*505, 12, 510, 21373}, {0, 0.5, 20, 20000, 3, 1050, 13989} } } }")
lua.execute(f"MI = AuctionForever.Core.MergeScan({FRESH}, 0)")
ok(abs(L('MI.perHour') - 40) < 1e-9, f"burst + one normal window: the normal rate wins ({L('MI.perHour')}/h)")
# Cloud hours count as windows (2 cloud hours with sales = steady).
lua.execute("AuctionForeverDB = nil")
ok(L(f'{C}.Status(MakeItem())') == 'good', 'cloud history alone (70 hours with sales) is enough')
lua.execute("AuctionForeverDB = nil")

# Real data file from the collector loads, and every item gets a status without errors.
real = sys.argv[1] if len(sys.argv) > 1 else None
if real and os.path.exists(real):
    lua.execute(open(real, encoding='utf-8').read())
    n = L('''(function() local n, bad = 0, 0
      for id in pairs(AuctionForeverData.items) do
        local I = AuctionForever.Core.Info(id); n = n + 1
        local s = AuctionForever.Core.Status(I)
        if type(s) ~= "string" then bad = bad + 1 end
        AuctionForever.Core.ChooseDuration(I, 5); AuctionForever.Core.Flip(I, 100000); AuctionForever.Core.ValuePerDay(I)
      end return n, bad end)()''')
    ok(n[0] > 1000 and n[1] == 0, f'real data: {n[0]} items processed, {n[1]} errors')
    linen = L('AuctionForever.Core.Info(2589)')
    ok(linen is not None and linen.low is not None, f'real data: Linen Cloth lowest {linen and linen.low}c')
# ---- Budget plan: the combination of items and amounts with the most total profit within the budget.
def opts(*o): return '{' + ','.join('{qty=%d,cost=%d,profit=%d}' % x for x in o) + '}'
# The user's example: Linen 500 cheap at 20c (8.5c profit each), Wool 20 cheap at 60c (54c profit each).
LINEN = opts((150, 3000, 1275), (300, 6000, 2550), (500, 10000, 4250))
WOOL = opts((20, 1200, 1080))
X = lua.execute
X(f"Cands = {{ {{ id = 2589, options = {LINEN} }}, {{ id = 2592, options = {WOOL} }} }}")
X(f"P = {C}.Plan(Cands, 7200)")  # 72s budget
ids = [L('P[%d].id' % i) for i in range(1, int(L('#P')) + 1)]
ok(ids == [2592, 2589] and L('P[2].option.qty') == 300, f'72s: Wool first (best return), then the most Linen that fits (300): {ids}, linen {L("P[2] and P[2].option.qty")}')
ok(L('P.cost') <= 7200 and L('P.profit') == 1080 + 2550, f'plan stays in budget ({L("P.cost")}c) and adds up ({L("P.profit")}c)')
X(f"P = {C}.Plan(Cands, 3000)")  # 30s: only one fits
ok(int(L('#P')) == 1 and L('P[1].id') == 2589 and L('P[1].option.qty') == 150, 'tiny budget: picks the single best option that fits (150 Linen, 12s 75c beats Wool 10s 80c)')
X(f"P = {C}.Plan(Cands, 20000)")
ok(L('P.profit') == 1080 + 4250, 'big budget: everything worth buying')
ok(L(f'{C}.ItemShare(15000)') == 0.40 and abs(L(f'{C}.ItemShare(275000)') - 0.30) < 1e-9 and L(f'{C}.ItemShare(600000)') == 0.20,
   'per-item share: 40% up to a 5g budget, 30% at 27g 50s, 20% from 50g')
X(f"P = {C}.Plan({{}}, 20000)")
ok(int(L('#P')) == 0 and L('P.profit') == 0, 'no candidates: empty plan')
# Flip and FlipOptions agree: Flip is the best option under the per-item cap.
X(f"I = MakeItem(); O = {C}.FlipOptions(I, 20000 * {C}.ItemShare(20000)); F = {C}.Flip(I, 20000)")
best = L('(function() local b for _, o in ipairs(O) do if not b or o.profit > b.profit then b = o end end return b and b.profit end)()')
ok(best == L('F and F.profit'), f'Flip = best of FlipOptions ({best} vs {L("F and F.profit")})')
# ---- What you paid: purchases, cost per unit still held, and how flips turned out.
X = lua.execute
X(f"""CDB = {{}}
  {C}.AddBuy(CDB, 250069, 2, 4998, 1000, 919)   -- 2 Flank au Poivre at 24s 99c, plan expected 9s 19c profit each
  {C}.AddBuy(CDB, 250069, 2, 6000, 2000, 500)   -- 2 more at 30s
  H1, C1 = {C}.Holding(CDB, 250069)""")
ok(L('H1') == 4 and L('C1') == 2750, f"holding 4, average cost 27s 50c ({L('H1')}, {L('C1')})")
X(f"""CDB.mysales = {{ {{ 3000, 250069, 3, 3 * 3598, "sold" }} }}   -- 3 sold at 35s 98c
  H2, C2 = {C}.Holding(CDB, 250069)""")
ok(L('H2') == 1 and L('C2') == 3000, f"after 3 sold: 1 left, at 30s (first bought, first sold) ({L('H2')}, {L('C2')})")
X(f"R = {C}.FlipResults(CDB, 3000 + 60, 7)")
# revenue 3 * 3598 * 0.95 = 10254.3 -> 10254; cost 4998 + 3000 = 7998; profit 2256; expected 2*919 + 500 = 2338
ok(L('R.sold') == 3 and L('R.profit') == 2256 and L('R.expected') == 2338, f"flip results: sold 3, profit {L('R.profit')} (expected {L('R.expected')})")
X(f"CDB.mysales[2] = {{ 3100, 250069, 1, 0, 'expired' }}; H3 = {C}.Holding(CDB, 250069)")
ok(L('H3') == 1, 'expired mail: you still hold it')
ok(L(f"({C}.Holding(CDB, 2589))") == 0, 'never bought: nothing held')
ok(L(f"{C}.CostFloor(2750)") == -(-2750 * 100 // 95), 'cost floor: what you paid plus the 5% cut')
X(f"{C}.AddBuy(CDB, 2589, 5, 100, 1000 - 31 * 86400, 0); R2 = {C}.Holding(CDB, 2589)")
ok(L('R2') == 0 and not any(b[2] == 2589 for b in [list(v.values()) for v in L('CDB.buys').values()]) if L('CDB.buys') else True, 'purchases older than 30 days dropped')
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
