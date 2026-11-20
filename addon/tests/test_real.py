"""Tests on real WoW Forever data: the cloud file and a saved full scan from the game (addon/tests/fixtures/, kept off git).
These catch wrong assumptions that made-up numbers can't. Run: venv python -I test_real.py
Skips (exit 0) if the fixtures aren't on this PC."""
import os, sys
from lupa import LuaRuntime  # Lua 5.5: the saved file is too big for LuaJIT's constant limit (WoW loads it fine)

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HERE), 'AuctionForever')
FIX = os.path.join(HERE, 'fixtures')
CLOUD, SAVED = os.path.join(FIX, 'scan1_cloud.lua'), os.path.join(FIX, 'scan1_saved.lua')
if not (os.path.exists(CLOUD) and os.path.exists(SAVED)):
    print('SKIPPED: no real-data fixtures on this PC')
    sys.exit(0)

lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute('loadstring = loadstring or load; unpack = unpack or table.unpack')
lua.execute('function __Load(src, name, ...) local f = assert(loadstring(src, name)); return f(...) end')


def run(path, *args):
    lua.globals().__Load(open(path, encoding='utf-8').read(), os.path.basename(path), *args)


run(os.path.join(HERE, 'wowmock.lua'))
lua.execute('NS = {}')
ns = lua.eval('NS')
run(os.path.join(ADDON, 'Core.lua'), 'AuctionForever', ns)
run(CLOUD)
run(SAVED)
run(os.path.join(ADDON, 'Scan.lua'), 'AuctionForever', ns)
L, X = lua.eval, lua.execute
fails = 0


def ok(c, m):
    global fails
    print(('PASS ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


C = 'NS.Core'
RUNECLOTH, LINEN, THORIUM = 14047, 2589, 10620
X('FieldIndex = {} for i, n in ipairs(AuctionForeverData.fields) do FieldIndex[n] = i end')
X('function CloudLadder(id) local r = AuctionForeverData.items[id]; return r and r[FieldIndex.ladder] or {} end')
X('function FreshMap(id) local m = {} local F = AuctionForeverDB.fresh.items[id]; for _, s in ipairs(F and F[3] or {}) do m[s[1]] = s[2] end return m end')

# 1. Every real item rates without errors.
n, errs = L('''(function() local n, e = 0, 0
  for id in pairs(AuctionForeverData.items) do n = n + 1
    local okk = pcall(function() local I = NS.Core.Info(id); NS.Core.Status(I); NS.Core.ValuePerDay(I); NS.Core.ChooseDuration(I, 5); NS.Core.Flip(I, 20000) end)
    if not okk then e = e + 1 end end return n, e end)()''')
ok(n > 5000 and errs == 0, f'real data: {n} items rate without errors ({errs} errors)')

# 2. Invariant: no item is a steady seller ("good") on a single window of sales.
bad = L('''(function() local t = {}
  for id in pairs(AuctionForeverData.items) do local I = NS.Core.Info(id)
    if NS.Core.Status(I) == "good" and (I.salesWindows or 0) < 2 then t[#t+1] = id end end return #t end)()''')
ok(bad == 0, f'no item rated a steady seller from one window ({bad} found)')

# 3. Runecloth: the real buyout window (about 7,900 gone in 43 min) alone can't make it a steady seller.
st = L(f'{C}.Status({C}.Info({RUNECLOTH}))')
ok(st == 'early', f'Runecloth after the buyout window only: "{st}" (not a steady seller)')
flips = L(f'{C}.Flip({C}.Info({RUNECLOTH}), 20000)')
ok(flips is None, 'Runecloth not offered as a flip on the buyout window')

# 4. Same buyout, then two normal windows (~300/h): the buyout is caught as a burst, the normal rate is used.
X(f'''Saved = AuctionForeverDB.obs[{RUNECLOTH}]
  AuctionForeverDB.obs[{RUNECLOTH}] = {{ Saved[1], {{0, 0.5, 150, 150*516, 4, 520, 13989}}, {{0, 0.5, 160, 160*517, 4, 520, 13900}} }}''')
I = L(f'{C}.Info({RUNECLOTH})')
ok(I.spikes == 1 and 290 <= I.perHour <= 330, f'buyout + normal windows: burst left out, {I.perHour:.0f}/h (was ~10,900/h)')
X(f'AuctionForeverDB.obs[{RUNECLOTH}] = Saved')

# 5. Today's code agrees with the real comparison: cloud ladder vs scanned ladder for Runecloth.
sold = L(f'(function() local s = {C}.CompareLadders(CloudLadder({RUNECLOTH}), FreshMap({RUNECLOTH})) return s end)()')
saved_sold = L(f'AuctionForeverDB.obs[{RUNECLOTH}][1][3]')
ok(sold == saved_sold, f'Runecloth comparison reproduces what the game measured ({sold} vs {saved_sold})')

# 6. No false sales: items whose cheapest price levels didn't change show nothing sold.
same, false_sales = L(f'''(function() local same, bad = 0, 0
  for id in pairs(AuctionForeverData.items) do
    local B, F = CloudLadder(id), AuctionForeverDB.fresh.items[id]
    if F and #B > 0 and #F[3] > 0 and B[1][1] == F[3][1][1] and B[1][2] == F[3][1][2] then
      same = same + 1
      if {C}.CompareLadders(B, FreshMap(id)) > 0 then bad = bad + 1 end
    end
  end return same, bad end)()''')
ok(same > 100 and false_sales == 0, f'{same} items with an untouched cheapest level: {false_sales} false sales')

# 7. Old saved format (one starting point for everything) converts to per-item starting points.
X('OldBase = AuctionForeverDB.base')
is_old = L('type(OldBase) == "table" and OldBase.items ~= nil')
X('AuctionForeverDB.base = { time = AuctionForeverDB.fresh.time, items = AuctionForeverDB.fresh.items }')
X(f'NS.Scan.Observe({LINEN}, FreshMap({LINEN}), nil, nil, nil, AuctionForeverDB.fresh.time + 60, true)')
b = L(f'AuctionForeverDB.base[{LINEN}]')
ok(b is not None and b.t == L('AuctionForeverDB.fresh.time') and L(f'AuctionForeverDB.base.items == nil'),
   f'old one-starting-point format converts per item{" (your file had the old format)" if is_old else ""}')

# 8. A full scan 20 min later replays cleanly on real data: listings rebuilt from your scan, Runecloth's cheapest
#    level bought out. Only Runecloth sells; nothing else shows false sales.
X('''Levels, Exp = {}, {}
  for id, F in pairs(AuctionForeverDB.fresh.items) do if F[2] and F[2] > 0 then local m = {} for _, s in ipairs(F[3]) do m[s[1]] = s[2] end Levels[id] = m end end
  local R = AuctionForeverDB.fresh.items[14047][3][1]
  RuneBought = R[2]
  Levels[14047][R[1]] = nil''')
X('M, W, P, Soon = NS.Scan.FinishFull(Levels, Exp, AuctionForeverDB.fresh.time + 1200)')
others = L('''(function() local n = 0 for id, O in pairs(AuctionForeverDB.obs) do local x = O[#O]
  if id ~= 14047 and x[1] == AuctionForeverDB.fresh.time and x[3] > 0 then n = n + 1 end end return n end)()''')
rune = L('(function() local O = AuctionForeverDB.obs[14047]; return O[#O][3] end)()')
ok(not L('P') and rune == L('RuneBought') and others == 0, f'replayed full scan: Runecloth {rune} sold (expected {L("RuneBought")}), {others} false sales elsewhere')

# 9. Quick scan (browse) on real data: lowest prices and stock applied, sales history untouched.
X('''Items = {} for id, F in pairs(AuctionForeverDB.fresh.items) do if F[1] then Items[id] = { F[1] - 1, F[2] + 5 } end end
  ObsCount = 0 for _, O in pairs(AuctionForeverDB.obs) do ObsCount = ObsCount + #O end
  NS.Scan.ApplyBrowse(Items, AuctionForeverDB.fresh.time + 1500, true)
  ObsAfter = 0 for _, O in pairs(AuctionForeverDB.obs) do ObsAfter = ObsAfter + #O end''')
f = L(f'AuctionForeverDB.fresh.items[{THORIUM}]')
ok(L('ObsCount == ObsAfter') and f[4] == L('AuctionForeverDB.fresh.time + 1500') and f[3][1][1] == f[1], f'quick scan on real data: prices applied (Thorium lowest {f[1]}c), sales history untouched')

print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
