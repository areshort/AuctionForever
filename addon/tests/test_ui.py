"""Offline test of UI.lua with a fake WoW API (wowmock.lua). Proves it loads and its flows run; not that it looks right in game.
Run: venv python -I test_ui.py [path to a real AuctionForeverData.lua]"""
import os, sys
from lupa.luajit21 import LuaRuntime

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HERE), 'AuctionForever')
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute('function __Load(src, name, ...) local f = assert(loadstring(src, name)); return f(...) end')


def run(path, *args):
    lua.globals().__Load(open(path, encoding='utf-8').read(), os.path.basename(path), *args)


run(os.path.join(HERE, 'wowmock.lua'))
lua.execute('AF_NS = {}')
ns = lua.eval('AF_NS')
run(os.path.join(ADDON, 'Core.lua'), 'AuctionForever', ns)
real = sys.argv[1] if len(sys.argv) > 1 else None
if real:
    lua.execute(open(real, encoding='utf-8').read())
run(os.path.join(ADDON, 'Scan.lua'), 'AuctionForever', ns)
run(os.path.join(ADDON, 'UI.lua'), 'AuctionForever', ns)
fails = 0


def ok(c, m):
    global fails
    print(('PASS ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


L, X = lua.eval, lua.execute
S = 'AF_NS.Session'
X('FireEvent("PLAYER_LOGIN")')
ok(L('AuctionForeverMinimapButton ~= nil'), 'minimap button created')
ok(L('#TooltipPostCalls == 1'), 'tooltip hook registered')
X('SlashCmdList.AUCTIONFOREVER("")')
ok(L('AuctionForeverFrame:IsShown() and AuctionForeverFrame.selectedTab == 1'), '/af opens the Farm tab')
if real:
    ok(not L('AuctionForeverFrame.Empty:IsShown()'), 'farm list has rows from real data')
X('AuctionForeverMinimapButton:GetScript("OnClick")(AuctionForeverMinimapButton, "RightButton")')
ok(L('AuctionForeverFrame:IsShown() and AuctionForeverFrame.selectedTab == 2'), 'minimap right-click switches to Flips')
X('AuctionForeverMinimapButton:GetScript("OnClick")(AuctionForeverMinimapButton, "RightButton")')
ok(L('not AuctionForeverFrame:IsShown()'), 'right-click again closes it')
X('Money = 5000; SlashCmdList.AUCTIONFOREVER("flip")')
ok(L('AuctionForeverFrame.Empty:IsShown()') and 'budget' in L('AuctionForeverFrame.Empty:GetText()'), 'under 1g: says there is no flip budget')
X('Money = 2000000; AuctionForeverFrame:Hide()')

# Sessions
X('SlashCmdList.AUCTIONFOREVER("sessions")')
X(f'{S}.Start()')
X('FireEvent("CHAT_MSG_LOOT", "You receive loot: |cffffffff|Hitem:2589::::::::60:::::|h[Linen Cloth]|h|rx3.")')
X('FireEvent("CHAT_MSG_LOOT", "You receive loot: |cffffffff|Hitem:2589::::::::60:::::|h[Linen Cloth]|h|r.")')
X('FireEvent("CHAT_MSG_MONEY", "You loot 1 Gold, 2 Silver, 3 Copper")')
ok(L(f'{S}.Current().items[2589]') == 4, 'loot messages counted (x3 + single)')
ok(L(f'{S}.Current().money') == 10203, 'money message parsed: 1g 2s 3c')
X('AdvanceTime(1800)')
ok(abs(L(f'{S}.Seconds({S}.Current())') - 1800) < 1e-6, 'timer counts while running')
X(f'{S}.Stop(); AdvanceTime(600)')
ok(abs(L(f'{S}.Seconds({S}.Current())') - 1800) < 1e-6, 'stopped timer does not count')
X('FireEvent("CHAT_MSG_LOOT", "You receive loot: |cffffffff|Hitem:2589::::::::60:::::|h[Linen Cloth]|h|r.")')
ok(L(f'{S}.Current().items[2589]') == 4, 'loot while stopped is not counted')
X('AF_NS.UI.RefreshSessions()')
g = L('AuctionForeverFrame.SessionPane.Gold:GetText()')
ok('per hour' in g, 'gold per hour shown: ' + g)
X(f'{S}.New()')
ok(L('#AuctionForeverChar.sessions') == 1, 'New session archives the old one')
X('AF_NS.UI.RefreshSessions()')
ok('Arathi' in L('AuctionForeverFrame.SessionPane.History:GetText()'), 'past session listed: ' + L('AuctionForeverFrame.SessionPane.History:GetText()'))
X('StaticPopupDialogs.AUCTIONFOREVER_CLEAR_SESSIONS.OnAccept()')
ok(L('#AuctionForeverChar.sessions') == 0 and L('AuctionForeverChar.current == nil'), 'Clear sessions empties everything')
X(f'{S}.Start(); FireEvent("PLAYER_LOGOUT")')
ok(L(f'not {S}.Running()'), 'logout stops the timer')

# Moving: position saved per character
X('AuctionForeverFrame:GetScript("OnDragStop")(AuctionForeverFrame)')
ok(L('AuctionForeverChar.pos ~= nil and AuctionForeverChar.pos[3] == 10'), 'position saved per character on drag stop')

if real:
    X('TooltipPostCalls[1](GameTooltip, {id = 2589})')
    lines = [str(v) for v in L('TipLines').values()]
    ok('AuctionForever' in lines, 'Linen Cloth tooltip: ' + ' | '.join(lines[2:]))
# Scan: rebuild the auction house from the cloud data's ladders, 40 min later, with Linen Cloth's two cheapest levels bought.
if real:
    X("""
    Listings = {}
    local D = AuctionForeverData
    local LI; for i, n in ipairs(D.fields) do if n == "ladder" then LI = i end end
    for id, Row in pairs(D.items) do
      local Lad = Row[LI] or {}
      for j, Step in ipairs(Lad) do
        local Q = Step[2]
        if id == 2589 and j <= 2 then Q = 0 elseif id == 2589 and j == 3 then Q = math.floor(Q / 2) end
        if Q > 0 then table.insert(Listings, { id, Q, Step[1] * Q, 2 }) end
      end
    end
    LinenBefore = D.items[2589][LI]
    C_AuctionHouse = {
      ReplicateItems = function() ReplicateCalled = true end,
      GetNumReplicateItems = function() return #Listings end,
      GetReplicateItemInfo = function(i) local E = Listings[i]; return "x", 1, E[2], 1, true, 1, "", 0, 0, E[3], 0, false, nil, "o", "o", 0, E[1], true end,
      GetReplicateItemTimeLeft = function(i) return Listings[i][4] end,
    }
    AuctionHouseFrame = CreateFrame("Frame", "AuctionHouseFrame")
    local RealTime = time
    time = function() return D.time + 2400 end
    FireEvent("AUCTION_HOUSE_SHOW")
    AuctionForeverScanButton:GetScript("OnClick")()
    FireEvent("REPLICATE_ITEM_LIST_UPDATE")
    """)
    ok(L('ReplicateCalled == true'), 'Scan button asks the server for the full listing')
    # Pump the per-frame worker until finished.
    X("""
    -- find the worker frame (the one with an OnUpdate set) and pump it
    for _ = 1, 10000 do
      if not AF_NS.Scan.Busy() then break end
      for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end
    end
    """)
    ok(not L('AF_NS.Scan.Busy()'), 'scan finished')
    expect = L('LinenBefore[1][2] + LinenBefore[2][2] + (LinenBefore[3][2] - math.floor(LinenBefore[3][2] / 2))')
    obs = L('AuctionForeverDB.obs[2589] and AuctionForeverDB.obs[2589][1]')
    ok(obs is not None and obs[3] == expect and abs(obs[2] - 2400 / 3600) < 1e-6, f'Linen Cloth: {obs and obs[3]} sold measured over 40 min (expected {expect})')
    others = L('(function() local n = 0 for id, O in pairs(AuctionForeverDB.obs) do if id ~= 2589 and O[1][3] > 0 then n = n + 1 end end return n end)()')
    ok(others == 0, f'unchanged items show no sales ({others} false sales)')
    ok(L('AuctionForeverDB.fresh.items[2589][1]') == L('LinenBefore[3][1]'), 'fresh lowest price for Linen comes from the scan')
    I = L('AF_NS.Core.Info(2589)')
    ok(I.fromScan and I.perHour > 0, f'Linen now shows {I.perHour:.0f}/h, status {L("AF_NS.Core.Status(AF_NS.Core.Info(2589))")}')
    ok('scanned' in str(L('LastPrint')), 'chat summary: ' + str(L('LastPrint')))
    # Incomplete scan: only a handful of items comes back
    X("""time = function() return AuctionForeverData.time + 4800 end; Listings = { Listings[1], Listings[2] }
    AuctionForeverScanButton:GetScript("OnClick")(); FireEvent("REPLICATE_ITEM_LIST_UPDATE")
    for _ = 1, 100 do if not AF_NS.Scan.Busy() then break end for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end""")
    ok('incomplete' in str(L('LastPrint')) and len(list(L('AuctionForeverDB.obs[2589]').values())) == 1, 'incomplete scan: prices kept, no fake sales')

print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
