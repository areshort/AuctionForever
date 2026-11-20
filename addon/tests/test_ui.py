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
import re
# Taint guard: reassigning a Blizzard global (even to itself) taints it and gets protected actions blocked
# ("AuctionForever has been blocked from an action only available to the Blizzard UI").
BLIZZ = r'StaticPopupDialogs|UISpecialFrames|SlashCmdList|GameTooltip|ItemRefTooltip|UIParent|Minimap|C_[A-Za-z]+|Enum|TooltipDataProcessor'
taint = [f'{f}:{n}' for f in os.listdir(ADDON) if f.endswith('.lua')
         for n, line in enumerate(open(os.path.join(ADDON, f), encoding='utf-8'), 1)
         if re.match(rf'^\s*(?:{BLIZZ})\s*=[^=]', line)]


def ok(c, m):
    global fails
    print(('PASS ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


L, X = lua.eval, lua.execute
ok(not taint, 'no Blizzard globals reassigned (taint): ' + (', '.join(taint) or 'none'))
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
# Auction house: build a fake one from the cloud data's ladders. Its tab row: Buy, Sell (Blizzard) and an
# Auctionator-style tab inside a container, so our tab must go right of all of them without joining Blizzard's list.
if real:
    X("""
    Listings = {}
    local D = AuctionForeverData
    local LI; for i, n in ipairs(D.fields) do if n == "ladder" then LI = i end end
    for id, Row in pairs(D.items) do
      for j, Step in ipairs(Row[LI] or {}) do
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
      IsThrottledMessageSystemReady = function() return true end,
      MakeItemKey = function(id) return { itemID = id } end,
      SendSearchQuery = function(key) LastQuery = key.itemID end,
      GetNumCommoditySearchResults = function(id) return #(Auctions[id] or ListingAuctions(id)) end,
      HasFullCommoditySearchResults = function() return true end,
      GetCommoditySearchResultInfo = function(id, j) return (Auctions[id] or ListingAuctions(id))[j] end,
    }
    Auctions = {}
    -- Items without hand-made auctions answer with their current listings (stable IDs per item and price).
    function ListingAuctions(id)
      local A = {}
      for _, E in ipairs(Listings) do if E[1] == id and E[2] > 0 then
        A[#A + 1] = { itemID = id, quantity = E[2], unitPrice = E[3] / E[2], auctionID = id * 1000 + #A, timeLeftSeconds = 40000 } end end
      return A
    end
    AuctionHouseFrame = CreateFrame("Frame", "AuctionHouseFrame")
    local Buy = CreateFrame("Button", nil, AuctionHouseFrame); Buy._top, Buy._left, Buy._right = 100, 20, 90
    local Sell = CreateFrame("Button", nil, AuctionHouseFrame); Sell._top, Sell._left, Sell._right = 100, 75, 150
    local Box = CreateFrame("Frame", nil, AuctionHouseFrame)
    AtorTab = CreateFrame("Button", nil, Box); AtorTab._top, AtorTab._left, AtorTab._right = 100, 600, 700
    AuctionHouseFrame.BuyTab, AuctionHouseFrame.SellTab = Buy, Sell
    AuctionHouseFrame.Tabs = { Buy, Sell }
    AuctionHouseFrame.selectedTab = 1
    function AuctionHouseFrame:SetDisplayMode(m) self.displayMode = m end
    RealTime = time
    time = function() return D.time + 2400 end
    FireEvent("AUCTION_HOUSE_SHOW")
    RunTimers()
    """)
    ok(L('AuctionForeverAHTab ~= nil') and L('#AuctionHouseFrame.Tabs') == 2, "AuctionForever tab created without joining Blizzard's tab list")
    pt = L('AuctionForeverAHTab._points[#AuctionForeverAHTab._points]')
    ok(pt is not None and pt[1] == 'LEFT' and pt[4] == 700 - 20 + 3, f'tab placed right of the last tab, Auctionator included (offset {pt and pt[4]})')
    ok(L('not AuctionForeverAHPanel:IsShown()'), 'panel hidden until the tab is clicked')
    X('Click(AuctionForeverAHTab)')
    ok(L('AuctionForeverAHPanel:IsShown() and AuctionForeverAHTab._selected and not AuctionHouseFrame.BuyTab._selected'), 'clicking the tab shows the panel and highlights it')
    X('Click(AuctionHouseFrame.SellTab)')
    ok(L('not AuctionForeverAHPanel:IsShown() and not AuctionForeverAHTab._selected'), "clicking Blizzard's Sell tab hides our panel")
    X('Click(AuctionForeverAHTab); Click(AtorTab)')
    ok(L('not AuctionForeverAHPanel:IsShown()'), "clicking Auctionator's tab hides our panel")
    X('Click(AuctionForeverAHTab); AuctionHouseFrame:SetDisplayMode("other")')
    ok(L('not AuctionForeverAHPanel:IsShown()'), 'any display mode change hides our panel')
    ok(L('AuctionHouseFrame.displayMode') == 'other', "Blizzard's own SetDisplayMode still runs")

    # Full scan from the panel, 40 min after the cloud data (55 counting the 15 min allowance).
    X('Click(AuctionForeverAHTab)')
    X('Click(AuctionForeverAHPanel.Full)')
    ok(L('ReplicateCalled == true'), 'Full Scan asks the server for every listing')
    X("""function Pump() for _ = 1, 1000 do if not AF_NS.Scan.Busy() then break end
          for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end end
        FireEvent("REPLICATE_ITEM_LIST_UPDATE"); Pump()""")
    ok(not L('AF_NS.Scan.Busy()'), 'full scan finished')
    expect = L('LinenBefore[1][2] + LinenBefore[2][2] + (LinenBefore[3][2] - math.floor(LinenBefore[3][2] / 2))')
    obs = L('AuctionForeverDB.obs[2589] and AuctionForeverDB.obs[2589][1]')
    ok(obs is not None and obs[3] == expect and abs(obs[2] - 3300 / 3600) < 1e-6, f'Linen: {obs and obs[3]} sold over 55 min (expected {expect})')
    others = L('(function() local n = 0 for id, O in pairs(AuctionForeverDB.obs) do if id ~= 2589 and O[1][3] > 0 then n = n + 1 end end return n end)()')
    ok(others == 0, f'unchanged items show no sales ({others} false sales)')
    ok(L('AuctionForeverDB.base[2589].t') == L('AuctionForeverData.time + 2400'), 'each item gets its own starting point')
    I = L('AF_NS.Core.Info(2589)')
    ok(I.fromScan and I.perHour > 0, f'Linen now {I.perHour:.0f}/h, status {L("AF_NS.Core.Status(AF_NS.Core.Info(2589))")}')
    ok('Sales measured' in str(L('AuctionForeverAHPanel.Result:GetText()')), 'panel shows the result: ' + str(L('AuctionForeverAHPanel.Result:GetText()')))

    # 5 min later another full scan, after buyers cleared Linen's cheapest level: prices refresh, starting point kept.
    X('for _, E in ipairs(Listings) do if E[1] == 2589 and E[2] > 0 then Bought2 = E[2]; E[2] = 0; break end end')
    X('time = function() return AuctionForeverData.time + 2700 end; Click(AuctionForeverAHPanel.Full); FireEvent("REPLICATE_ITEM_LIST_UPDATE"); Pump()')
    ok(len(list(L('AuctionForeverDB.obs[2589]').values())) == 1 and L('AuctionForeverDB.base[2589].t') == L('AuctionForeverData.time + 2400'),
       'scan 5 min later: no measurement, starting point kept')
    ok(L('AuctionForeverDB.fresh.items[2589][4]') == L('AuctionForeverData.time + 2700'), 'scan 5 min later: prices refreshed')

    # Quick scan 20 min after the starting point: Linen (in the bags) is looked up and measured against it.
    X("""function LinenAuctions(Secs)
      local A, n = {}, 0
      for _, E in ipairs(Listings) do if E[1] == 2589 and E[2] > 0 then n = n + 1
        A[#A + 1] = { itemID = 2589, quantity = E[2], unitPrice = E[3] / E[2], auctionID = 5000 + n, timeLeftSeconds = Secs and Secs[n] or 40000 } end end
      table.sort(A, function(a, b) return a.unitPrice < b.unitPrice end)
      return A
    end
    function PumpQuick() for _ = 1, 200 do if not AF_NS.Scan.Busy() then break end
      if LastQuery then local id = LastQuery; LastQuery = nil; FireEvent("COMMODITY_SEARCH_RESULTS_UPDATED", id) end end
      Timers = {} end""")
    ql = list(L('AF_NS.UI.QuickList()').values())
    ok(2589 in ql and 999999 not in ql and len(ql) <= 45, f'quick list: {len(ql)} items, includes Linen from the bags, skips soulbound')
    X('Auctions[2589] = LinenAuctions({ [1] = 40000, [2] = 600 })')
    X('time = function() return AuctionForeverData.time + 3600 end; Click(AuctionForeverAHPanel.Quick); PumpQuick()')
    o2 = L('AuctionForeverDB.obs[2589][2]')
    ok(o2 is not None and abs(o2[2] - 1200 / 3600) < 1e-6 and o2[3] == L('Bought2'), f'quick scan 20 min after the start: {o2 and o2[3]} sold over {o2 and round(o2[2]*60)} min')
    ok(L('AuctionForeverDB.base[2589].auc ~= nil'), 'quick scan keeps listing IDs for exact comparison next time')
    ok(L('AuctionForeverDB.obs[999999] == nil'), 'items not looked at are left alone')
    fake = L('(function() local n = 0 for id, O in pairs(AuctionForeverDB.obs) do if id ~= 2589 and #O >= 2 and O[#O][3] > 0 then n = n + 1 end end return n end)()')
    ok(fake == 0, f'quick scan: unchanged items show no sales ({fake} false sales)')
    X('Auctions[13] = {}')
    X('time = function() return AuctionForeverData.time + 3700 end; AF_NS.Scan.Quick({ 13 }); PumpQuick()')
    ok("didn't answer" in str(L('LastPrint')) and L('AuctionForeverDB.base[13] == nil or AuctionForeverDB.base[13].t ~= AuctionForeverData.time + 3700'),
       'an empty answer is treated as no answer, not a sell-out')
    X('Auctions[13] = nil')
    ok('Quick scan' in str(L('LastPrint')), 'chat summary: ' + str(L('LastPrint')))

    # Quick scan again 20 min later, compared listing by listing:
    #   cheapest listing 5 fewer -> 5 bought; 2nd listing gone with 10 min left -> expired; most expensive gone while a
    #   cheaper one sits untouched -> cancelled. Only the 5 count.
    X("""local A = Auctions[2589]
      local Changed = {}
      for i, R in ipairs(A) do Changed[i] = { itemID = 2589, quantity = R.quantity, unitPrice = R.unitPrice, auctionID = R.auctionID, timeLeftSeconds = R.timeLeftSeconds } end
      Changed[1].quantity = Changed[1].quantity - 5
      table.remove(Changed, #Changed)   -- most expensive: cancelled
      table.remove(Changed, 2)          -- had 10 min left: expired
      Auctions[2589] = Changed
      time = function() return AuctionForeverData.time + 4800 end; Click(AuctionForeverAHPanel.Quick); PumpQuick()""")
    o3 = L('AuctionForeverDB.obs[2589][3]')
    ok(o3 is not None and o3[3] == 5, f'exact comparison: {o3 and o3[3]} sold (partial buy counted; expired and cancelled ignored)')

    # An item that never answers is skipped after the timeout.
    X("""C_AuctionHouse.SendSearchQuery = function() end
      time = function() return AuctionForeverData.time + 9000 end
      AF_NS.Scan.Quick({ 2589 })
      RunTimers()""")
    ok(not L('AF_NS.Scan.Busy()') and "didn't answer" in str(L('LastPrint')), 'quick scan: an item that never answers is skipped: ' + str(L('LastPrint')))

    # Full scan the server never answers: after 60 s the panel resets with a message.
    X('local R = C_AuctionHouse.ReplicateItems; C_AuctionHouse.ReplicateItems = function() end; time = function() return AuctionForeverData.time + 9500 end; Click(AuctionForeverAHPanel.Full); C_AuctionHouse.ReplicateItems = R')
    ok(L('AF_NS.Scan.Busy()') and L('AuctionForeverAHPanel.Full._disabled'), 'waiting for the server: buttons disabled')
    X('RunTimers()')
    ok(not L('AF_NS.Scan.Busy()') and "didn't send" in str(L('LastPrint')) and not L('AuctionForeverAHPanel.Full._disabled'), 'no answer in 60 s: buttons back, message shown')

    # Incomplete full scan: only two listings come back -> prices kept, no fake sales.
    n_before = len(list(L('AuctionForeverDB.obs[2589]').values()))
    X('time = function() return AuctionForeverData.time + 12000 end; Listings = { Listings[1], Listings[2] }; Click(AuctionForeverAHPanel.Full); FireEvent("REPLICATE_ITEM_LIST_UPDATE"); Pump()')
    ok('incomplete' in str(L('LastPrint')) and len(list(L('AuctionForeverDB.obs[2589]').values())) == n_before, 'incomplete scan: prices kept, no fake sales')

    # Names: remembered, so a list shows them even before the server answers.
    X('AF_NS.UI.Toggle(1)')
    ok(L('AuctionForeverDB.names ~= nil and next(AuctionForeverDB.names) ~= nil'), 'names remembered when loaded')
    X('local G = C_Item.GetItemInfo; C_Item.GetItemInfo = function() return nil end; AF_NS.UI.Load(); C_Item.GetItemInfo = G')
    cells = L('(function() local t = {} for _, f in ipairs(AllFramesForTest) do if f._kind == "FontString" and type(f._text) == "string" and f._text:find("Item %d") then t[#t+1] = f._text end end return #t end)()')
    loading = L('(function() local n = 0 for _, f in ipairs(AllFramesForTest) do if f._kind == "FontString" and type(f._text) == "string" and f._text:find("loading") then n = n + 1 end end return n end)()')
    ok(cells > 0 and loading == 0, f'list shows remembered names while the server is slow ({cells} names, {loading} "loading")')
    X('time = RealTime')

# Flip tab explains itself when empty.
X('Money = 2000000; AuctionForeverDB = nil; AF_NS.UI.Toggle(2)')
reason = str(L('AF_NS.UI.FlipEmptyReason()'))
ok(('warming up' in reason) or ('steady sellers' in reason), 'empty Flip tab says why: ' + reason.replace('\n', ' '))

print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
