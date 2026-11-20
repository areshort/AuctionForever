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
# Record reads of undefined globals made by add-on code (catches misplaced local declarations and typos).
lua.execute("""
UndefinedReads = {}
local Allowed = { AuctionForeverDB = true, AuctionForeverChar = true, AuctionForeverData = true }
setmetatable(_G, { __index = function(_, k)
  if not Allowed[k] then
    local Info = debug.getinfo(2, "S")
    local Src = Info and Info.source or "?"
    if Src:find("Core.lua") or Src:find("Scan.lua") or Src:find("UI.lua") or Src:find("SelfTest.lua") or Src:find("Trade.lua") then UndefinedReads[#UndefinedReads + 1] = Src .. ": " .. tostring(k) end
  end
end })
""")
lua.execute('AF_NS = {}')
ns = lua.eval('AF_NS')
# Load files in the .toc order, like the game does (a file missing from the .toc is never loaded, here or in game).
real = sys.argv[1] if len(sys.argv) > 1 else None
TOC = [l.strip() for l in open(os.path.join(ADDON, 'AuctionForever.toc'), encoding='utf-8') if l.strip() and not l.startswith('#')]
for f in TOC:
    if f == 'AuctionForeverData.lua':
        if real: lua.execute(open(real, encoding='utf-8').read())
    else:
        run(os.path.join(ADDON, f), 'AuctionForever', ns)
on_disk = sorted(f for f in os.listdir(ADDON) if f.endswith('.lua') and f != 'AuctionForeverData.lua')
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
      GetItemKeyInfo = function() return {} end, HasSearchResults = function() return true end,
      GetNumItemSearchResults = function() return 0 end, GetItemSearchResultInfo = function() return nil end, HasFullItemSearchResults = function() return true end,
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
    ok(L('AuctionForeverBuyTab ~= nil and AuctionForeverSellTab ~= nil and AuctionForeverAHTab ~= nil') and L('#AuctionHouseFrame.Tabs') == 2,
       "three tabs (AF Buy, AF Sell, AuctionForever) created without joining Blizzard's tab list")
    ok([L('AuctionForeverBuyTab:GetText()'), L('AuctionForeverSellTab:GetText()'), L('AuctionForeverAHTab:GetText()')] == ['AF Buy', 'AF Sell', 'AuctionForever'], 'tab names')
    pt = L('AuctionForeverBuyTab._points[#AuctionForeverBuyTab._points]')
    ok(pt is not None and pt[1] == 'LEFT' and pt[4] == 700 - 20 + 3, f'AF Buy placed right of the last tab, Auctionator included (offset {pt and pt[4]})')
    p2 = L('AuctionForeverSellTab._points[#AuctionForeverSellTab._points]')
    p3 = L('AuctionForeverAHTab._points[#AuctionForeverAHTab._points]')
    ok(p2 is not None and p2[1] == 'LEFT' and L('AuctionForeverSellTab._points[#AuctionForeverSellTab._points][2] == AuctionForeverBuyTab') and p2[3] == 'RIGHT' and p2[4] == 3
       and p3 is not None and L('AuctionForeverAHTab._points[#AuctionForeverAHTab._points][2] == AuctionForeverSellTab') and p3[3] == 'RIGHT' and p3[4] == 3,
       'tabs in order AF Buy, AF Sell, AuctionForever, 3 px apart (no overlap)')
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
    X('AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)')
    ok(L('AuctionForeverAHPanel.Bar:IsShown()') and 'waiting for the server' in str(L('AuctionForeverAHPanel.Bar.Text:GetText()')),
       'progress while waiting: ' + str(L('AuctionForeverAHPanel.Bar.Text:GetText()')))
    X("""FireEvent("REPLICATE_ITEM_LIST_UPDATE")
      for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u and f ~= AuctionForeverAHPanel then u(f, 0.016) end end
      AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)""")
    bt = str(L('AuctionForeverAHPanel.Bar.Text:GetText()'))
    ok('reading listings' in bt and ' of ' in bt and '%' in bt and not bt.startswith('Full scan: reading listings 100%'), 'progress while reading: ' + bt)
    X("""function Pump() for _ = 1, 1000 do if not AF_NS.Scan.Busy() then break end
          for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end end
        Pump()""")
    ok(not L('AF_NS.Scan.Busy()'), 'full scan finished')
    ok(not L('AuctionForeverAHPanel.Bar:IsShown()') and L('AuctionForeverAHPanel.QuickInfo:IsShown()'), 'progress bar goes away when done')
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

    # Item lookup 20 min after the starting point: Linen (in the bags) is looked up and measured against it.
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
    X('time = function() return AuctionForeverData.time + 3600 end; AF_NS.Scan.Lookup(AF_NS.UI.QuickList()); PumpQuick()')
    o2 = L('AuctionForeverDB.obs[2589][2]')
    ok(o2 is not None and abs(o2[2] - 1200 / 3600) < 1e-6 and o2[3] == L('Bought2'), f'quick scan 20 min after the start: {o2 and o2[3]} sold over {o2 and round(o2[2]*60)} min')
    ok(L('AuctionForeverDB.base[2589].auc ~= nil'), 'quick scan keeps listing IDs for exact comparison next time')
    ok(L('AuctionForeverDB.obs[999999] == nil'), 'items not looked at are left alone')
    fake = L('(function() local n = 0 for id, O in pairs(AuctionForeverDB.obs) do if id ~= 2589 and #O >= 2 and O[#O][3] > 0 then n = n + 1 end end return n end)()')
    ok(fake == 0, f'quick scan: unchanged items show no sales ({fake} false sales)')
    X('Auctions[13] = {}')
    X('time = function() return AuctionForeverData.time + 3700 end; AF_NS.Scan.Lookup({ 13 }); PumpQuick()')
    ok("didn't answer" in str(L('LastPrint')) and L('AuctionForeverDB.base[13] == nil or AuctionForeverDB.base[13].t ~= AuctionForeverData.time + 3700'),
       'an empty answer is treated as no answer, not a sell-out')
    X('Auctions[13] = nil')
    ok('Item lookup' in str(L('LastPrint')), 'chat summary: ' + str(L('LastPrint')))

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
      time = function() return AuctionForeverData.time + 4800 end; AF_NS.Scan.Lookup(AF_NS.UI.QuickList()); PumpQuick()""")
    o3 = L('AuctionForeverDB.obs[2589][3]')
    ok(o3 is not None and o3[3] == 5, f'exact comparison: {o3 and o3[3]} sold (partial buy counted; expired and cancelled ignored)')

    # Lookups use the server's own item key when a quick scan has learned it.
    X('AF_NS.Scan.Keys[2589] = { itemID = 2589, itemLevel = 5, marker = "server" }; SentKey = nil; local S = C_AuctionHouse.SendSearchQuery; C_AuctionHouse.SendSearchQuery = function(k) SentKey = k; LastQuery = k.itemID end')
    X('time = function() return AuctionForeverData.time + 5000 end; AF_NS.Scan.Lookup({ 2589 }); PumpQuick()')
    ok(L('SentKey and SentKey.marker') == 'server', "item lookup uses the server's item key from the quick scan")
    X('AF_NS.Scan.Keys[2589] = nil')

    # Quick scan = browse everything in pages (Auctionator's method): page 1 via UPDATED, page 2 via ADDED.
    X("""BrowsePages = { { { itemKey = { itemID = 2589 }, minPrice = 24, totalQuantity = 15000 }, { itemKey = { itemID = 14047 }, minPrice = 520, totalQuantity = 14000 } },
                       { { itemKey = { itemID = 14047, itemLevel = 1 }, minPrice = 515, totalQuantity = 100 } } }
      Page = 0
      C_AuctionHouse.SendBrowseQuery = function(q) BrowseQ = q; Page = 1 end
      C_AuctionHouse.GetBrowseResults = function() return BrowsePages[1] end
      C_AuctionHouse.RequestMoreBrowseResults = function() Page = Page + 1 end
      C_AuctionHouse.HasFullBrowseResults = function() return Page >= 2 end
      ObsBefore = #AuctionForeverDB.obs[2589]
      time = function() return AuctionForeverData.time + 5200 end
      Click(AuctionForeverAHPanel.Quick)""")
    ok(L('BrowseQ ~= nil and BrowseQ.searchString == ""'), 'quick scan sends one browse-everything query')
    X('AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)')
    ok('waiting' in str(L('AuctionForeverAHPanel.Bar.Text:GetText()')), 'progress while waiting: ' + str(L('AuctionForeverAHPanel.Bar.Text:GetText()')))
    X('FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED"); AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)')
    ok('items read' in str(L('AuctionForeverAHPanel.Bar.Text:GetText()')), 'progress while reading pages: ' + str(L('AuctionForeverAHPanel.Bar.Text:GetText()')))
    X('FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_ADDED", BrowsePages[2])')
    ok(not L('AF_NS.Scan.Busy()'), 'quick scan done after the last page')
    f = L('AuctionForeverDB.fresh.items[14047]')
    ok(f[1] == 515 and f[2] == 14100 and f[4] == L('AuctionForeverData.time + 5200'), f'pages combined: lowest {f[1]}c, {f[2]} listed')
    ok(L('AuctionForeverDB.fresh.items[2589][1]') == 24 and L('AuctionForeverDB.fresh.items[2589][3][1][1]') == 24, 'new lowest price becomes the first price level')
    ok(L('#AuctionForeverDB.obs[2589]') == L('ObsBefore'), 'quick scan refreshes prices only; sales history untouched')
    ok(L('AF_NS.Scan.Keys[14047] ~= nil'), "server item keys learned for later lookups")
    ok('Quick scan: prices and stock for 2 items' in str(L('LastPrint')), 'chat summary: ' + str(L('LastPrint')))
    I = L('AF_NS.Core.Info(14047)')
    ok(I.low == 515 and I.qty == 14100, 'lists and tooltips use the quick-scan price')
    # Server goes quiet mid-scan: stops after the timeout, keeps what it got.
    X("""C_AuctionHouse.HasFullBrowseResults = function() return false end
      C_AuctionHouse.RequestMoreBrowseResults = function() end
      time = function() return AuctionForeverData.time + 5400 end
      Click(AuctionForeverAHPanel.Quick); FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED"); RunTimers(); RunTimers()""")
    ok(not L('AF_NS.Scan.Busy()') and 'stopped answering' in str(L('LastPrint')), 'server goes quiet: stops and keeps what it got: ' + str(L('LastPrint')))

    # The client ignores searches for items it hasn't cached: wait for GetItemKeyInfo before searching.
    X("""Sent = 0; CacheAsks = 0
      C_AuctionHouse.SendSearchQuery = function(k) Sent = Sent + 1; LastQuery = k.itemID end
      C_AuctionHouse.GetItemKeyInfo = function() CacheAsks = CacheAsks + 1; if CacheAsks <= 3 then return nil end return { itemName = "Linen Cloth" } end
      time = function() return AuctionForeverData.time + 5100 end
      AF_NS.Scan.Lookup({ 2589 }, true)""")
    ok(L('Sent') == 0, 'no search sent while the item is not cached yet')
    X('AdvanceTime(0.1); AdvanceTime(0.1); AdvanceTime(0.1)')
    ok(L('Sent') == 1, f"search sent once the item is cached (after {L('CacheAsks')} checks)")
    X('FireEvent("COMMODITY_SEARCH_RESULTS_UPDATED", 2589)')
    ok(not L('AF_NS.Scan.Busy()') and "didn't answer" not in str(L('AF_NS.Scan.LastResult')), 'cached item answered: ' + str(L('AF_NS.Scan.LastResult')))
    # A bad empty answer ("no results" although there are listings) is asked again.
    X("""Sent = 0; Answers = 0
      C_AuctionHouse.GetItemKeyInfo = function() return {} end
      C_AuctionHouse.HasSearchResults = function() Answers = Answers + 1; return Answers > 1 end
      time = function() return AuctionForeverData.time + 5150 end
      AF_NS.Scan.Lookup({ 2589 }, true); FireEvent("COMMODITY_SEARCH_RESULTS_UPDATED", 2589)""")
    ok(L('Sent') == 2 and L('AF_NS.Scan.Busy()'), f"bad empty answer: searched again ({L('Sent')} searches)")
    X('FireEvent("COMMODITY_SEARCH_RESULTS_UPDATED", 2589)')
    ok(not L('AF_NS.Scan.Busy()') and "didn't answer" not in str(L('AF_NS.Scan.LastResult')), 'second answer accepted: ' + str(L('AF_NS.Scan.LastResult')))
    X('C_AuctionHouse.GetItemKeyInfo = function() return {} end; C_AuctionHouse.HasSearchResults = function() return true end; C_AuctionHouse.SendSearchQuery = function(k) LastQuery = k.itemID end')

    # An item that never answers is skipped after the timeout.
    X("""C_AuctionHouse.SendSearchQuery = function() end
      time = function() return AuctionForeverData.time + 9000 end
      AF_NS.Scan.Lookup({ 2589 })
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

    # ---- AF Buy / AF Sell -----------------------------------------------------------------------------------
    X("""Calls = {}
      local function Rec(name) return function(...) Calls[#Calls + 1] = { name, ... }; return CallReturns and CallReturns[name] end end
      for _, n in ipairs({ "StartCommoditiesPurchase", "ConfirmCommoditiesPurchase", "CancelCommoditiesPurchase", "PlaceBid", "PostCommodity", "PostItem", "ConfirmPostCommodity", "ConfirmPostItem" }) do C_AuctionHouse[n] = Rec(n) end
      C_AuctionHouse.CalculateCommodityDeposit = function(id, d, q) return 15 * q * d end
      C_AuctionHouse.CalculateItemDeposit = function(loc, d, q) return 30 * q * d end
      C_AuctionHouse.IsSellItemValid = function() return true end
      C_AuctionHouse.GetItemCommodityStatus = function(loc) return loc.itemID == 14047 and 1 or 2 end
      function LastCall(name) for i = #Calls, 1, -1 do if Calls[i][1] == name then return Calls[i] end end end
      LookupSpy = {}
      RealLookup = AF_NS.Scan.Lookup
      AF_NS.Scan.Lookup = function(Ids, Silent, Done) LookupSpy[#LookupSpy + 1] = { ids = Ids, silent = Silent }; if Done then Done() end return true end
      -- two flip targets with fresh data, so selecting them needs no re-check
      Now = AuctionForeverData.time + 20000
      time = function() return Now end
      AuctionForeverDB.fresh.items[2589] = { 20, 500, { { 20, 300 }, { 30, 200 } }, Now }
      AuctionForeverDB.fresh.items[14047] = { 400, 50, { { 400, 5 } }, Now }
      AF_NS.Scan.Kind[2589] = "commodity"; AF_NS.Scan.Kind[14047] = "item"
      AF_NS.Scan.Listings[14047] = { { auctionID = 78, qty = 1, buyout = 900 }, { auctionID = 77, qty = 1, buyout = 380 } }
      FlipTargets = {
        { id = 2589, info = AF_NS.Core.Info(2589), flip = { buyQty = 10, buyUpTo = 30, cost = 250, resell = 200, hours = 2, durationIndex = 1, profit = 320 } },
        { id = 14047, info = AF_NS.Core.Info(14047), flip = { buyQty = 1, buyUpTo = 400, cost = 380, resell = 1000, hours = 8, durationIndex = 2, profit = 570 } },
      }
      AF_NS.UI.FlipRows = function() return FlipTargets end
      Click(AuctionForeverBuyTab)""")
    ok(L('AuctionForeverBuyPanel:IsShown() and not AuctionForeverSellPanel:IsShown() and not AuctionForeverAHPanel:IsShown()'), 'AF Buy shows its panel only')
    ok(L('AuctionForeverBuyTab._selected and not AuctionForeverSellTab._selected and not AuctionForeverAHTab._selected and not AuctionHouseFrame.BuyTab._selected'), 'AF Buy highlighted, other tabs not')
    ok(L('AF_NS.Trade.SelectedBuy() and AF_NS.Trade.SelectedBuy().id') == 2589, 'first flip target selected')
    ok('Item 2589' in str(L('AuctionForeverBuyPanel.Rows[1].Cells[1]:GetText()')), 'row shows the item: ' + str(L('AuctionForeverBuyPanel.Rows[1].Cells[1]:GetText()')))
    ok(len(L('LookupSpy')) == 0, 'fresh data: no re-check on select')
    # commodity buy, price rose: cancelled, nothing confirmed
    X('Click(AuctionForeverBuyPanel.Buy)')
    c = L('LastCall("StartCommoditiesPurchase")')
    ok(c is not None and c[2] == 2589 and c[3] == 10, 'Buy starts a commodity purchase of the flip amount (10)')
    X('FireEvent("COMMODITY_PRICE_UPDATED", 35, 350)')
    ok(L('LastCall("CancelCommoditiesPurchase") ~= nil') and L('LastCall("ConfirmCommoditiesPurchase") == nil'), 'price rose above the max: purchase cancelled, nothing confirmed')
    ok('price' in str(L('AuctionForeverBuyPanel.Status:GetText()')).lower(), 'says the price changed: ' + str(L('AuctionForeverBuyPanel.Status:GetText()')))
    ok('Confirm' not in str(L('AuctionForeverBuyPanel.Buy:GetText()')), 'button back to Buy')
    # price fine: confirm with a second click
    X('Click(AuctionForeverBuyPanel.Buy); FireEvent("COMMODITY_PRICE_UPDATED", 26, 260)')
    ok('Confirm 10' in str(L('AuctionForeverBuyPanel.Buy:GetText()')), 'price fine: button asks to confirm: ' + str(L('AuctionForeverBuyPanel.Buy:GetText()')))
    ok(L('LastCall("ConfirmCommoditiesPurchase") == nil'), 'nothing bought before the second click')
    X('Click(AuctionForeverBuyPanel.Buy)')
    c = L('LastCall("ConfirmCommoditiesPurchase")')
    ok(c is not None and c[2] == 2589 and c[3] == 10, 'second click confirms 10')
    X('FireEvent("COMMODITY_PURCHASE_SUCCEEDED")')
    ok(L('AF_NS.Trade.SelectedBuy().id') == 14047, 'after buying: next target selected (Buy next)')
    # not a commodity: buys the cheapest listing within the max, one per click
    X('Click(AuctionForeverBuyPanel.Buy)')
    c = L('LastCall("PlaceBid")')
    ok(c is not None and c[2] == 77 and c[3] == 380, f'item flip: buys the cheapest listing within the max (auction {c and c[2]} for {c and c[3]})')
    # over budget: cancelled
    X('Money = 50000; Calls = {}; AF_NS.Trade.SelectBuy(1); Click(AuctionForeverBuyPanel.Buy); FireEvent("COMMODITY_PRICE_UPDATED", 26, 260000)')
    ok(L('LastCall("CancelCommoditiesPurchase") ~= nil') and L('LastCall("ConfirmCommoditiesPurchase") == nil'), 'total over the flip budget: cancelled')
    X('Money = 2000000')
    # stale data: selecting re-checks the item quietly
    X('AuctionForeverDB.fresh.items[14047][4] = Now - 600; LookupSpy = {}; AF_NS.Trade.SelectBuy(2)')
    ok(L('LookupSpy[1] ~= nil and LookupSpy[1].ids[1] == 14047 and LookupSpy[1].silent == true'), 'data older than 2 min: selected item re-checked silently')
    # empty list explains why
    X('FlipTargets = {}; AF_NS.Trade.RefreshBuy()')
    ok(L('AuctionForeverBuyPanel.Empty:IsShown()'), 'no targets: shows the reason')

    # ---- AF Sell ----
    X("""Bag = { { itemID = 2589, stackCount = 20, isBound = false }, { itemID = 999999, stackCount = 1, isBound = true },
              { itemID = 2589, stackCount = 5, isBound = false }, { itemID = 424242424, stackCount = 3, isBound = false },
              { itemID = 14047, stackCount = 4, isBound = false }, { itemID = 10620, stackCount = 7, isBound = false } }
      RealContainer = C_Container
      C_Container = { GetContainerNumSlots = function(b) return b == 0 and #Bag or 0 end, GetContainerItemInfo = function(b, s) return b == 0 and Bag[s] or nil end }
      ItemLocation = { CreateFromBagAndSlot = function(self, b, s) return { bag = b, slot = s, itemID = Bag[s] and Bag[s].itemID } end }
      RealGI = C_Item.GetItemInfo
      C_Item.GetItemInfo = function(id) local r = { RealGI(id) }; if id == 10620 then r[11] = 100000000 end return unpack(r, 1, 11) end
      LookupSpy = {}
      Click(AuctionForeverSellTab)""")
    ok(L('AuctionForeverSellPanel:IsShown() and not AuctionForeverBuyPanel:IsShown() and AuctionForeverSellTab._selected and not AuctionForeverBuyTab._selected'), 'AF Sell shows its panel only')
    q = L('AF_NS.Trade.SellQueue()')
    ids = [q[i].id for i in range(1, len(q) + 1)] if q else []
    ok(2589 in ids and 14047 in ids, f'sell queue has the AH items from the bags: {ids}')
    ok(999999 not in ids and 424242424 not in ids, 'bound items and items with no auction data left out')
    ok(10620 not in ids, 'items worth more at the vendor left out')
    lin = [q[i] for i in range(1, len(q) + 1) if q[i].id == 2589]
    ok(lin and lin[0].count == 25, f'stacks of the same item grouped: {lin and lin[0].count}')
    ok(L('LookupSpy[1] ~= nil and LookupSpy[1].silent == true') and sorted(L('LookupSpy[1].ids').values()) == sorted(ids), 'opening AF Sell re-checks the queue items quietly')
    ok(L('AF_NS.Trade.SelectedSell() ~= nil') and ids and L('AF_NS.Trade.SelectedSell().id') == ids[0], 'first queue item selected')
    X('AF_NS.Trade.SelectSellId(2589)')
    price = L('AF_NS.Trade.SellPrice()')
    qty = L('tonumber(AuctionForeverSellPanel.Qty:GetText())')
    ok(price is not None and price >= 6 and price == int(price), f'price prefilled, whole copper, not below vendor (5c + cut): {price}')
    ok(qty is not None and 1 <= qty <= 25, f'quantity prefilled: {qty}')
    ok(L('AF_NS.Trade.SellDuration()') in (1, 2, 3), 'duration chosen')
    ok('Deposit' in str(L('AuctionForeverSellPanel.Deposit:GetText()')), 'deposit shown: ' + str(L('AuctionForeverSellPanel.Deposit:GetText()')))
    # Post (commodity, no confirmation needed): PostCommodity(location, duration, qty, unit price)
    X('Calls = {}; AF_NS.Trade.SetSellPrice(47); AuctionForeverSellPanel.Qty:SetText("12"); AF_NS.Trade.SetSellDuration(2); Click(AuctionForeverSellPanel.Post)')
    c = L('LastCall("PostCommodity")')
    ok(c is not None and L('LastCall("PostCommodity")[2].bag') == 0 and L('LastCall("PostCommodity")[2].slot') == 1 and c[3] == 2 and c[4] == 12 and c[5] == 47,
       f'Post calls PostCommodity(bag 0 slot 1, 8 h, 12, 47c): {c and [c[3], c[4], c[5]]}')
    ok(L('AF_NS.Trade.SelectedSell().id') != 2589, 'after posting: next item')
    # the server asks for confirmation
    X('CallReturns = { PostCommodity = true }; Calls = {}; AF_NS.Trade.SelectSellId(2589); AF_NS.Trade.SetSellPrice(47); AuctionForeverSellPanel.Qty:SetText("3"); Click(AuctionForeverSellPanel.Post)')
    ok('Confirm' in str(L('AuctionForeverSellPanel.Post:GetText()')) and L('LastCall("ConfirmPostCommodity") == nil'), 'server asks for confirmation: Post becomes Confirm')
    X('Click(AuctionForeverSellPanel.Post)')
    c = L('LastCall("ConfirmPostCommodity")')
    ok(c is not None and c[4] == 3 and c[5] == 47, 'second click confirms the same post')
    X('CallReturns = nil')
    # not a commodity: PostItem(location, duration, qty, no bid, buyout per item), like Blizzard's item sell frame
    X('Calls = {}; AF_NS.Trade.SelectSellId(14047); AF_NS.Trade.SetSellPrice(900); AuctionForeverSellPanel.Qty:SetText("2"); AF_NS.Trade.SetSellDuration(1); Click(AuctionForeverSellPanel.Post)')
    c = L('LastCall("PostItem")')
    ok(c is not None and L('LastCall("PostItem")[2].slot') == 5 and c[3] == 1 and c[4] == 2 and c[5] is None and c[6] == 900, f'item posts with PostItem: {c and [c[3], c[4], c[5], c[6]]}')
    # never below vendor
    X('Calls = {}; AF_NS.Trade.SelectSellId(2589); AF_NS.Trade.SetSellPrice(2); Click(AuctionForeverSellPanel.Post)')
    ok(L('LastCall("PostCommodity") == nil') and 'vendor' in str(L('AuctionForeverSellPanel.Status:GetText()')).lower(), 'price below vendor: not posted, says why')
    # Skip walks the queue and wraps
    n = len(q)
    X('AF_NS.Trade.SelectSell(1)')
    for _ in range(n):
        X('Click(AuctionForeverSellPanel.Skip)')
    ok(L('AF_NS.Trade.SellIndex()') == 1, f'Skip walks the queue and wraps back to the start ({n} items)')
    X('Click(AuctionForeverSellPanel.QueueRows[2])')
    ok(n < 2 or L('AF_NS.Trade.SellIndex()') == 2, 'clicking a queue row selects it')
    # Blizzard's tab hides all our panels
    X('Click(AuctionHouseFrame.SellTab)')
    ok(L('not AuctionForeverSellPanel:IsShown() and not AuctionForeverBuyPanel:IsShown() and not AuctionForeverAHPanel:IsShown()'), "Blizzard's tab hides all our panels")
    X('AF_NS.Scan.Lookup = RealLookup; C_Container = RealContainer; C_Item.GetItemInfo = RealGI')
    X('time = RealTime')

# Flip tab explains itself when empty.
X('Money = 2000000; AuctionForeverDB = nil; AF_NS.UI.Toggle(2)')
reason = str(L('AF_NS.UI.FlipEmptyReason()'))
ok(('warming up' in reason) or ('steady sellers' in reason), 'empty Flip tab says why: ' + reason.replace('\n', ' '))

# /af selftest runs end to end in the mock (auction house open), saves results, and finds no problems.
X('AuctionHouseFrame:Show(); AuctionForeverDB = AuctionForeverDB or {}; AuctionForeverDB.selftest = nil')
X('STok, STerr = pcall(function() SlashCmdList.AUCTIONFOREVER("selftest"); for i = 1, 10 do RunTimers() end end)')
okr, err = L('STok'), L('STerr')
st = L('AuctionForeverDB.selftest')
lines = [str(v) for v in st.lines.values()] if st else []
ok(okr and st is not None, f'selftest runs and saves results ({err})')
ok(st is not None and not [l for l in lines if l.startswith('FAIL') and 'cloud data' not in l and 'lookup' not in l and 'minimap' not in l],
   'selftest in the mock: ' + '; '.join(l for l in lines if l.startswith('FAIL')))
ok(all(f in TOC for f in on_disk), 'every add-on .lua file is listed in the .toc: ' + ', '.join(f for f in on_disk if f not in TOC))
undef = sorted(set(str(v) for v in L('UndefinedReads').values()))
ok(not undef, 'no reads of undefined globals from add-on code: ' + (', '.join(undef) or 'none'))
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
