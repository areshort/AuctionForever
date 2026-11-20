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
# Duration: sellThrough 0.8 < 0.9 -> stays 2 h; with 0.95 -> 8 h (1100 >= 999 * 1.1)
ok(L(f'{C}.ChooseDuration(MakeItem(), 20)')[0] == 2, 'not reliable enough for longer: 2 h')
h, idx, price, fill = L(f'{C}.ChooseDuration(MakeItem({{sellThrough = 0.95}}), 20)')
ok(h == 8 and idx == 2 and price == 1100, f'reliable seller, 10%+ more at 8 h: {h} h at {price}')
# Quantity: 2 h at 999 -> room 40*2 - 40 below = 40
ok(L(f'{C}.PostQuantity(MakeItem(), 100, 2, 999)') == 40, 'post only what sells in time')
# Budget
ok(L(f'{C}.Budget(100000)') == 50000, '10g -> 5g budget')
ok(L(f'{C}.Budget(15000)') == 5000, '1.5g -> 0.5g (keep 1g)')
ok(L(f'{C}.Budget(8000)') == 0, 'under 1g: nothing')
# Flip: buy 10 at 5s, resell ~9s99c within 2 h -> profit ~ 10*999*0.95 - 5000 = 4490
lua.execute('Flip = AuctionForever.Core.Flip(MakeItem(), 500000)')
ok(L('Flip ~= nil and Flip.buyQty == 10 and Flip.buyUpTo == 500') and L('Flip.profit') >= 1000, f'cheap listing below a gap: flip {L("Flip and Flip.profit")}')
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
ok(L(f'{C}.Status(MI)') == 'good', 'one scan 30 min after the cloud data is enough to rate a fast seller: ' + L(f'{C}.Status(MI)'))
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
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
