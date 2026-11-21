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
ok(L(f'{C}.Budget(100000)') == 95000, '10g -> 9g 50s budget (keep 50s)')
ok(L(f'{C}.Budget(15000)') == 10000, '1g 50s -> 1g (keep 50s)')
ok(L(f'{C}.Budget(4000)') == 0, 'under 50s: nothing')
# Flip options: you must be the cheapest after buying, reselling 1c under what's left.
# Buy 10 at 5s -> resell 949, profit planned at 97% of it: floor(949*10*0.95*0.97) - 5000 = 3745. Buying the 30 at
# 9s 50c too (resell 999) would plan floor(999*40*0.95*0.97) - 33500 = 3323, a 9.9% return: under the 10% minimum.
lua.execute(f'O = {C}.FlipOptions(MakeItem({{ sellThrough = 1 }}), 500000); Flip = {C}.Flip(MakeItem({{ sellThrough = 1 }}), 500000)')
ok(L('O[1].buyQty == 10 and O[1].resell == 949 and O[1].profit == 3745'), f'first option: resell 1c under the next listing ({L("O[1].resell")}, {L("O[1].profit")})')
ok(L('#O == 1 and Flip.buyQty == 10 and Flip.profit == 3745'), f'buying the next level too is a 9.9% return: not offered ({L("#O")} options)')
# Only the 12 cheapest levels are kept: buying through all of them, with more listings above, isn't a flip
# (seen with Minor Mana Potion: "resell at 6s 15c" after buying every known level).
lua.execute(f"Trunc = {C}.FlipOptions(MakeItem({{ ladder = {{ {{500, 10}}, {{950, 30}} }}, qty = 300 }}), 500000)")
ok(L('#Trunc') == 1 and L('Trunc[1].buyQty') == 10, f'more listings above the kept levels: never buys out the last known level ({L("#Trunc")} options)')
lua.execute(f"All = {C}.FlipOptions(MakeItem({{ sellThrough = 1, ladder = {{ {{500, 10}}, {{600, 30}} }}, qty = 40 }}), 500000)")
ok(L('(function() for _, o in ipairs(All) do if o.buyQty == 40 and o.resell == 1000 then return true end end end)()'),
   'every listing known: buying them all is allowed (resold at the sale median)')
# Medium Leather (real ladder): 20 cheap at 91c, then 207 at 98c. Reselling at 97c doesn't pay; buying the 98c ones
# too is over budget, and a partly bought level leaves cheaper stock in front of you. No flip.
lua.execute("""Leather = AuctionForever.Core.Flip(MakeItem({ low = 91, qty = 6204, med = 118, hi = 135, med24 = 118, medAll = 118,
  perHour = 1826, medHour = 1826, ladder = { {91, 20}, {98, 207}, {99, 14}, {100, 986}, {101, 152}, {102, 437} } }), 14982)""")
ok(L('Leather == nil'), 'Medium Leather case: buying 1% of the market and posting behind 2000 cheaper units is not a flip')
# Same cheap listing, but a wall of stock right above it: no flip.
lua.execute('Wall = AuctionForever.Core.Flip(MakeItem({ ladder = { {500, 10}, {510, 2000} }, qty = 900 }), 500000)')
ok(L('Wall == nil'), 'cheap listing with lots of stock just above: skipped')
ok(L('AuctionForever.Core.Flip(MakeItem({ sales = 3 }), 500000) == nil'), 'warming up: no flip')
# Expected profit: only sellThrough of what you post sells (80% here); the rest is worth half. 10 at 5s resold at 949:
# N = 949 * 10 * 0.95 * 0.97; floor(0.8 N + 0.2 N * 0.5) - 5000 = 2870. Buying the 9s 50c level too doesn't pay.
lua.execute(f'EO = {C}.FlipOptions(MakeItem(), 500000)')
ok(L('#EO') == 1 and L('EO[1].profit') == 2870, f"profit counts the chance of selling: {L('#EO')} options, {L('EO[1] and EO[1].profit')}")
# Never buy more than the cautious resale speed sells in 8 h: 15/h planned -> at most 120. (Without the cap, buying
# the 9s 50c level too would be offered: 150 units, 10 h of sales.)
lua.execute(f"Big = {C}.FlipOptions(MakeItem({{ perHour = 20, medHour = 20, sellThrough = 1, qty = 250, ladder = {{ {{400, 60}}, {{450, 60}}, {{950, 30}}, {{1000, 100}} }} }}), 10000000)")
ok(L('#Big') >= 1 and max(L(f'Big[{i}].buyQty') for i in range(1, int(L('#Big')) + 1)) <= 120,
   f"flip size capped at 8 h of resale: {[L(f'Big[{i}].buyQty') for i in range(1, int(L('#Big')) + 1)]}")
# Other sellers posting more than sells doesn't stop a flip: resale speed is measured sales x 0.75 (flooded items are
# skipped by Status instead).
lua.execute(f"NH = {C}.FlipOptions(MakeItem({{ newHour = 100 }}), 500000)")
ok(L('#NH') >= 1, f"new listings outpacing sales (100/h vs 40/h sold): still a flip target ({L('#NH')} options)")
# Slow sellers (sales in only some hours) can be flipped, marked slow; steady ones aren't marked.
lua.execute(f"SL = {C}.FlipOptions(MakeItem({{ hoursWithSales = 20 }}), 500000)")
ok(L(f"{C}.Status(MakeItem({{ hoursWithSales = 20 }}))") == 'slow' and L('#SL') >= 1 and L('SL[1].slow') == True,
   f"slow seller: still a flip target, marked slow ({L('#SL')} options)")
ok(L('EO[1].slow') is None, 'steady seller: not marked slow')
# Too little history: needs 4 h of data before it's a flip target (selling is unaffected).
ok(L(f'#{C}.FlipOptions(MakeItem({{ hoursSeen = 3 }}), 500000)') == 0 and L(f'{C}.FlipStatus(MakeItem({{ hoursSeen = 3 }}))') == 'warming up'
   and L(f'{C}.Status(MakeItem({{ hoursSeen = 3 }}))') == 'good', 'under 4 h of data: no flip (still fine to sell)')
# Minimum profit: a fixed 5s at any budget.
ok(L(f'{C}.MinFlipProfitFor(4848)') == 500 and L(f'{C}.MinFlipProfitFor(15000)') == 500 and L(f'{C}.MinFlipProfitFor(100000)') == 500,
   f"minimum flip profit: {L(f'{C}.MinFlipProfitFor(4848)')}, {L(f'{C}.MinFlipProfitFor(15000)')}, {L(f'{C}.MinFlipProfitFor(100000)')}")
lua.execute(f"Small = {C}.FlipOptions(MakeItem({{ sellThrough = 1, ladder = {{ {{500, 1}}, {{1000, 100}} }}, qty = 101 }}), 600, 300)")
ok(L('#Small') == 1 and L('Small[1].profit') == 420, f"a 4s 20c flip counts when your minimum is 3s ({L('#Small')}, {L('Small[1] and Small[1].profit')})")
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
# Per-item cap = 40% up to a 5g budget, then 20% of the budget + 1g (always grows with the budget, share eases to 20%).
ok(L(f'{C}.ItemShare(15000)') == 0.40 and abs(L(f'{C}.ItemShare(100000)') * 100000 - 30000) < 1e-6 and abs(L(f'{C}.ItemShare(1000000)') - 0.21) < 1e-9,
   'per-item share: 40% up to 5g, 3g of a 10g budget, 21% of 100g')
caps = [L(f'{C}.ItemShare({b})') * b for b in range(10000, 2000000, 10000)]
ok(all(caps[i] <= caps[i + 1] for i in range(len(caps) - 1)), 'a bigger budget never lowers the per-item cap')
# Gold needed for a flip that costs C: the least gold whose budget (gold minus 50s) gives a big enough item cap.
# 20s: cap 0.4 x budget -> budget 50s -> gold 1g. 3g: budget 10g (0.2 x 10g + 1g) -> gold 10g 50s.
ok(abs(L(f'{C}.GoldFor(2000)') - 10000) <= 1 and abs(L(f'{C}.GoldFor(30000)') - 105000) <= 2,
   f"gold needed: 20s flip -> {L(f'{C}.GoldFor(2000)')}, 3g flip -> {L(f'{C}.GoldFor(30000)')}")
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
# ---- Review fixes ------------------------------------------------------------------------------------------------
# Resale never above what buyers actually paid, in both the last day and the longer window (med24, medAll).
X(f"RC = {C}.FlipOptions(MakeItem({{ sellThrough = 1, med = 900, medAll = 900 }}), 500000, 200)")
ok(L('#RC') >= 1 and L('RC[1].resell') <= 900, f"resale capped at the real sale median (900c), not 1c under the next listing ({L('RC[1] and RC[1].resell')})")
# Profit planned at 97% of the resale price (commodity buyers take the cheapest, newest first at a tie, so matching
# the lowest sells; 3% for the odd undercut): 10 at 5s resold at 900 -> floor(900*0.97*0.95*10) - 5000 = 3293.
ok(L('RC[1].buyQty') == 10 and L('RC[1].profit') == 3293, f"profit planned at 97% of the resale price ({L('RC[1] and RC[1].profit')})")
ok(L(f'{C}.UndercutHaircut') == 0.97, 'undercut haircut is 3%')
# Expected deposit loss counts: deposit 1s a unit at 2 h, 60% chance -> 40% of the deposit expected lost; unsold
# 40% valued at half price: floor(N*0.6 + N*0.4*0.5 - 0.4*1000) - 5000 with N = 900*10*0.95*0.97 = 8293.5 -> 1234.
X(f"{C}.Deposit = function(I, H, Q) return 100 * Q * (H == 2 and 1 or 4) end")
X(f"DP = {{ {C}.Resale(MakeItem({{ sellThrough = 0.6, med = 900, medAll = 900 }}), 10, 5000) }}")
X(f"{C}.Deposit = nil")
ok(L('#DP') >= 1 and L('DP[1].profit') == 1234, f"expected deposit loss and half-value leftovers counted ({L('DP[1] and DP[1].profit')})")
# Unsold units are worth half the resale (a later relist at a worse price), not nothing: 60% chance, no deposit ->
# floor(8293.5 * 0.8) - 5000 = 1634.
X(f"US = {C}.FlipOptions(MakeItem({{ sellThrough = 0.6, med = 900, medAll = 900 }}), 500000, 0)")
ok(L('#US') >= 1 and L('US[1].profit') == 1634, f"leftovers valued at half the resale ({L('US[1] and US[1].profit')})")
# Minimum return, on top of the minimum amount: 10% of the cost for fast, steady sellers, 20% for slow ones.
# 10 at 10s resold at R: floor(R*10*0.95*0.97) - 10000. (More is listed above the known levels, so buying through
# the second level is never an option.)
def MR(next_price, slow=False):
    extra = ', hoursWithSales = 20' if slow else ''
    X(f"MRX = {C}.FlipOptions(MakeItem({{ sellThrough = 1, med = 1400, medAll = 1400, med24 = 1400, hi = 1500{extra}, ladder = {{ {{1000, 10}}, {{{next_price}, 100}} }}, qty = 210 }}), 500000, 200)")
    return int(L('#MRX')), L('MRX[1] and MRX[1].profit')
n, p = MR(1184)
ok(n == 0, f"steady seller, resold at 11s 83c: 9.0% return is under the 10% minimum: no flip ({n})")
n, p = MR(1206)
ok(n == 1 and p == 1104, f"steady seller, resold at 12s 05c: 11.0% return is a flip ({n}, {p})")
n, p = MR(1206, slow=True)
ok(n == 0, f"slow seller, same 11% return: under its 20% minimum, no flip ({n})")
n, p = MR(1250, slow=True)
ok(n == 0, f"slow seller, 15.1% return: no flip ({n})")
n, p = MR(1326, slow=True)
ok(n == 1 and p == 2209, f"slow seller, 22.1% return: a flip ({n}, {p})")
# FlipNeed: the return by speed (an item or its FlipStatus); unknown speed is held to the slow sellers' return.
ok(L(f'{C}.FlipNeed(10000, 200, "good")') == 1000 and L(f'{C}.FlipNeed(10000, 200, "slow")') == 2000
   and L(f'{C}.FlipNeed(10000, 200)') == 2000 and L(f'{C}.FlipNeed(1000, 500, "good")') == 500,
   f"flip need: 10% steady, 20% slow or unknown, never under the minimum profit ({L(f'{C}.FlipNeed(10000, 200, [[good]])')}, {L(f'{C}.FlipNeed(10000, 200, [[slow]])')})")
ok(L(f'{C}.FlipNeed(10000, 200, MakeItem())') == 1000 and L(f'{C}.FlipNeed(10000, 200, MakeItem({{ hoursWithSales = 20 }}))') == 2000,
   'flip need from an item: its FlipStatus decides (steady 10%, slow 20%)')
# What you already hold counts against the 4 h limit: 30/h planned -> 120, holding 100 -> at most 20 more.
X(f"HD = {C}.FlipOptions(MakeItem({{ sellThrough = 1, held = 220, qty = 150, ladder = {{ {{400, 20}}, {{950, 30}}, {{1000, 100}} }} }}), 10000000, 0)")
ok(L('#HD') >= 1 and max(L(f'HD[{i}].buyQty') for i in range(1, int(L('#HD')) + 1)) <= 20, f"holding 220 already (8 h of resale = 240): buys at most 20 more ({[L(f'HD[{i}].buyQty') for i in range(1, int(L('#HD')) + 1)]})")
# 4 h of data before flipping (two 2 h posting cycles).
ok(L(f"{C}.FlipStatus(MakeItem({{ hoursSeen = 3.5 }}))") == 'warming up' and L(f"{C}.FlipStatus(MakeItem({{ hoursSeen = 4 }}))") == 'good', 'flips need 4 h of data')
# Falling knife: lowest price 40% under the 3-day median and dropping snapshot after snapshot: no flip (selling unaffected).
ok(L(f"{C}.FlipStatus(MakeItem({{ low = 600, lows = {{ 900, 800, 600 }} }}))") == 'falling' and L(f"{C}.Status(MakeItem({{ low = 600, lows = {{ 900, 800, 600 }} }}))") == 'good',
   'price dropping fast and far under the median: not a flip target')
ok(L(f"{C}.FlipStatus(MakeItem({{ low = 600, lows = {{ 600, 650, 600 }} }}))") == 'good', 'cheap but steady (not dropping): still a target')
# Resale recomputed for a purchase from the data at hand (used when the server gives the live price).
X(f"RS = {C}.Resale(MakeItem({{ sellThrough = 1, med = 900, medAll = 900 }}), 10, 5000)")
ok(L('RS ~= nil and RS.resell <= 900 and RS.profit == 3293'), f"resale for a purchase from current data ({L('RS and RS.profit')})")
ok(L(f"{C}.Resale(MakeItem({{ sales = 3 }}), 10, 5000) == nil"), 'no resale once the item is no longer a good seller')
# Your own trades aren't the market: your purchases aren't others' sales, your posts aren't others' new listings.
X(f"""AuctionForeverDB = {{ buys = {{ {{ 1000000, 1, 72, 7200, 0 }} }}, myposts = {{ {{ 1000000, 1, 36, 500 }} }} }}
  OT = {C}.MergeScan(MakeItem({{ newHour = 2 }}), 1003600)
  AuctionForeverDB = nil""")
ok(abs(L('OT.perHour') - 39) < 1e-9 and abs(L('OT.newHour') - 1.5) < 1e-9, f"own 72 bought / 36 posted in the 72 h window taken out: {L('OT.perHour')}/h sold, {L('OT.newHour')}/h new")
# Your own listings aren't stock in front of you.
X(f"RM = {C}.RemoveMine({{ {{500, 10}}, {{950, 30}} }}, {{ [500] = 4, [950] = 30 }})")
ok(L('#RM') == 1 and L('RM[1][1]') == 500 and L('RM[1][2]') == 6, 'own listings taken out of the price ladder')
# New listings that matter: up to the 25% stock price, at least lowest +10% (same rule as the cloud collector).
ok(L(f"{C}.NewCutoff({{ [100] = 10, [200] = 10, [105] = 3 }})") == 110, 'new-listing cutoff: 10% over the lowest here')
# Cutting a loss: the market's lowest has stayed under what you need all day, or it expired twice since you bought.
X(f"""CL1 = {C}.CutLoss(MakeItem({{ lowHi24 = 900 }}), 1000, {{}}, 1)
  CL2 = {C}.CutLoss(MakeItem({{ lowHi24 = 1100 }}), 1000, {{}}, 1)
  CDB2 = {{ buys = {{ {{ 100, 1, 5, 5000, 0 }} }}, mysales = {{ {{ 200, 1, 5, 0, 'expired' }}, {{ 300, 1, 5, 0, 'expired' }} }} }}
  CL3 = {C}.CutLoss(MakeItem(), 1000, CDB2, 1)
  CDB2.mysales[2] = nil
  CL4 = {C}.CutLoss(MakeItem(), 1000, CDB2, 1)""")
ok(L('CL1') and not L('CL2') and L('CL3') and not L('CL4'), f"cut the loss: under all day {L('CL1')}, not {L('CL2')}; 2 expiries {L('CL3')}, 1 {L('CL4')}")
# Buy to vendor: every listing under the vendor price, cheapest first; needs 2s+ profit; no AH cut.
X(f"VD = {C}.VendorDeal({{ {{500, 3}}, {{900, 2}}, {{1000, 5}} }}, 1000)")
ok(L('VD and VD.vendor and VD.buyQty == 5 and VD.buyUpTo == 900 and VD.cost == 3300 and VD.profit == 1700 and VD.resell == 1000'),
   f"vendor deal: 3 at 5s + 2 at 9s under a 10s vendor price -> 17s profit ({L('VD and VD.profit')})")
ok(L(f"{C}.VendorDeal({{ {{997, 50}} }}, 1000)") is None, 'under 2s total profit (50 x 3c = 1s 50c): not a target')
ok(L(f"{C}.VendorDeal({{ {{996, 50}} }}, 1000)") is not None and L(f"{C}.VendorDeal({{ {{995, 50}} }}, 1000).profit") == 250,
   '2s+ total profit (50 x 4c = 2s; 50 x 5c = 2s 50c): a target')
X(f"VC = {C}.VendorDeal({{ {{500, 3}}, {{900, 2}} }}, 1000, 1500)")
ok(L('VC and VC.buyQty == 3 and VC.cost == 1500'), 'vendor deal within the budget: buys only what it can afford')
ok(L(f"{C}.VendorDeal({{ {{1, 200}} }}, 0)") is None, 'vendor pays nothing (ammo): never a target')
# Rec counts the chance it sells and the deposit lost when it doesn't (deposit = 3x vendor for 24 h here).
X(f"OldDepF = {C}.Deposit; {C}.Deposit = function(I, H, Q) return math.floor(I.vendorForTest * 3 / 24 * H) * Q end")
# Patched Leather Shoulderpads: 10s 80c, vendor 2s 7c, sells 32%, slow: deposit 6s 21c -> vendor.
ok(L(f"{C}.Recommend(MakeItem({{ vendorForTest = 207, sellThrough = 0.32, hoursWithSales = 5 }}), 207, 1080)") == 'Vendor',
   'Shoulderpads: 32% x 8s 18c gained < 68% x 6s 21c deposit lost: Vendor (was Auction)')
# Blazing Wand (slow): 7s 34c, vendor 6s 72c, 88% sell: deposit 20s 16c -> vendor.
ok(L(f"{C}.Recommend(MakeItem({{ vendorForTest = 672, sellThrough = 0.88, hoursWithSales = 5 }}), 672, 734)") == 'Vendor', 'Wand: tiny gain, big deposit: Vendor')
# A steady seller, 2 h deposit: 87% x 5c gained > 13% x 1c: Auction.
ok(L(f"{C}.Recommend(MakeItem({{ vendorForTest = 13, sellThrough = 0.87 }}), 13, 19)") == 'Auction', 'steady seller, small 2 h deposit: Auction')
ok(L(f"{C}.Recommend(MakeItem({{ vendorForTest = 207, sellThrough = 0.9, hoursWithSales = 5 }}), 207, 1080)") == 'Auction', 'slow but usually sells: Auction')
X(f"{C}.Deposit = OldDepF")
# A loss in coin colors: a red minus and the amount (it used to show -11s 94c as "88s 06c").
neg = str(L(f"{C}.MoneyColor(-1194)"))
ok(neg.startswith('|cffff4040-|r') and '11s' in neg and '94c' in neg and '88s' not in neg, 'MoneyColor shows a loss as -11s 94c: ' + neg)
ok('-' not in str(L(f"{C}.MoneyColor(1194)")), 'positive amounts have no minus')
# Your flips: two real buys (crates at a loss, leather at a small gain) add up to a loss.
X('''FDB = { buys = { { 1795164538, 248687, 40, 4937, 54.575 }, { 1795164671, 2319, 43, 3999, 35 } },
 mysales = { { 1795208902, 248687, 30, 2850, "sold" }, { 1795208902, 2319, 128, 12800, "sold" }, { 1795218499, 248687, 10, 1000, "sold" } } }''')
ok(L(f"{C}.FlipResults(FDB, 1795220000, 7).profit") == -1194, 'flip results: real buys and sales come to -11s 94c')
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
