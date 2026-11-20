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
    if Src:find("Core.lua") or Src:find("Scan.lua") or Src:find("UI.lua") or Src:find("SelfTest.lua") or Src:find("Mail.lua") or Src:find("Trade.lua") then UndefinedReads[#UndefinedReads + 1] = Src .. ": " .. tostring(k) end
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
    ok(L('AuctionForeverAHPanel.Bar:IsShown()') and 'waiting for the server' in str(L('AuctionForeverAHPanel.Bar.Text:GetText()'))
       and 's left' in str(L('AuctionForeverAHPanel.Bar.Text:GetText()')),
       'progress while waiting: ' + str(L('AuctionForeverAHPanel.Bar.Text:GetText()')))
    X("""FireEvent("REPLICATE_ITEM_LIST_UPDATE")
      for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u and f ~= AuctionForeverAHPanel then u(f, 0.016) end end
      AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)""")
    bt = str(L('AuctionForeverAHPanel.Bar.Text:GetText()'))
    ok('reading' in bt and ' of ' in bt and '%' in bt and L('AuctionForeverAHPanel.Bar:GetValue()') >= 0.3, 'progress while reading (bar past the waiting part): ' + bt)
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
       'full scan 5 min later: nothing measured, starting point kept')
    ok('available in 10 min' in str(L('AF_NS.Scan.LastResult')) and not L('AF_NS.Scan.Busy()'), 'full scan 5 min later: refused with the wait time: ' + str(L('AF_NS.Scan.LastResult')))
    X('AF_NS.UI.RefreshAHPanel()')
    ok(L('AuctionForeverAHPanel.Full:GetText()') == 'Full Scan (10 min)' and not L('AuctionForeverAHPanel.Full:IsEnabled()'), 'Full Scan button shows the countdown and is disabled')
    X('AuctionForeverDB.lastFull = AuctionForeverDB.lastFull - 600; AF_NS.UI.RefreshAHPanel()')
    ok(L('AuctionForeverAHPanel.Full:GetText()') == 'Full Scan' and L('AuctionForeverAHPanel.Full:IsEnabled()'), 'button back to normal after 15 min')
    X('AuctionForeverDB.lastFull = AuctionForeverDB.lastFull + 600')

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
    ok('items read' in str(L('AuctionForeverAHPanel.Bar.Text:GetText()')) and L('AuctionForeverAHPanel.Bar:GetValue()') <= 0.8, 'progress while reading pages (first 80% of one bar): ' + str(L('AuctionForeverAHPanel.Bar.Text:GetText()')))
    X('FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_ADDED", BrowsePages[2]); BrowseLinen = { AuctionForeverDB.fresh.items[2589][1], AuctionForeverDB.fresh.items[2589][3][1][1] }; Browse14047 = AuctionForeverDB.fresh.items[14047]; PumpQuick()')
    ok(not L('AF_NS.Scan.Busy()'), 'quick scan done after the last page (and its busy-item lookups)')
    f = L('Browse14047')
    ok(f[1] == 515 and f[2] == 14100 and f[4] == L('AuctionForeverData.time + 5200'), f'pages combined: lowest {f[1]}c, {f[2]} listed')
    ok(L('BrowseLinen[1]') == 24 and L('BrowseLinen[2]') == 24, 'new lowest price becomes the first price level')
    ok(L('#AuctionForeverDB.obs[2589]') == L('ObsBefore'), 'quick scan refreshes prices only; sales history untouched')
    ok(L('AF_NS.Scan.Keys[14047] ~= nil'), "server item keys learned for later lookups")
    ok('Quick scan: prices and stock for 2 items' in str(L('LastPrint')), 'chat summary: ' + str(L('LastPrint')))
    I = L('AF_NS.Core.Info(14047)')
    # (A busy item may get a detailed lookup right after the quick scan; then that newer look is what counts.)
    Fr = L('AuctionForeverDB.fresh.items[14047]')
    ok(I.low == Fr[1] and I.qty == Fr[2] and Fr[4] > L('AuctionForeverData.time'), f"lists and tooltips use the newest scan, not the cloud ({I.low}, {I.qty})")
    # Server goes quiet mid-scan: stops after the timeout, keeps what it got.
    X("""C_AuctionHouse.HasFullBrowseResults = function() return false end
      C_AuctionHouse.RequestMoreBrowseResults = function() end
      time = function() return AuctionForeverData.time + 5400 end
      Click(AuctionForeverAHPanel.Quick); FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED"); RunTimers(); RunTimers()""")
    ok(not L('AF_NS.Scan.Busy()') and 'stopped answering' in str(L('LastPrint')), 'server goes quiet: stops and keeps what it got: ' + str(L('LastPrint')))

    # Quick scan phase 2: exact lookups of the busiest items (top by sales per hour), right after the browse.
    busy = list(L('AF_NS.Scan.BusyIds(20)').values()) if L('AF_NS.Scan.BusyIds') else []
    ok(0 < len(busy) <= 20, f'busy list: {len(busy)} items')
    X("""C_AuctionHouse.HasFullBrowseResults = function() return Page >= 2 end
      C_AuctionHouse.RequestMoreBrowseResults = function() Page = Page + 1 end
      Looked = {}
      C_AuctionHouse.SendSearchQuery = function(k) Looked[#Looked + 1] = k.itemID; LastQuery = k.itemID end
      time = function() return AuctionForeverData.time + 5600 end
      Click(AuctionForeverAHPanel.Quick); FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED"); FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_ADDED", BrowsePages[2])""")
    ok(L('AF_NS.Scan.Busy()'), 'quick scan keeps going after the browse: checking busy items')
    X('AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)')
    bt = str(L('AuctionForeverAHPanel.Bar.Text:GetText()'))
    ok('busy' in bt and L('AuctionForeverAHPanel.Bar:GetValue()') >= 0.8, 'one bar: phase 2 continues past 80%: ' + bt)
    X('PumpQuick()')
    ok(not L('AF_NS.Scan.Busy()') and L('#Looked') == len(busy), f"looked up {L('#Looked')} busy items")
    lp = str(L('LastPrint'))
    ok('Quick scan: prices and stock for' in lp and 'busy items' in lp.lower(), 'one chat line for both phases: ' + lp)

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
      RealFlipRows = RealFlipRows or AF_NS.UI.FlipRows
      AF_NS.UI.FlipRows = function() return FlipTargets end
      RealFlipTargets = RealFlipTargets or AF_NS.UI.FlipTargets
      AF_NS.UI.FlipTargets = function() return FlipTargets end
      -- The live price check recomputes the resale from current data; here the data backs a 2s resale.
      RealResale = RealResale or AF_NS.Core.Resale
      AF_NS.Core.Resale = function(I, Q, Cost) if ResaleNil then return nil end return { resell = 200, profit = math.floor(200 * Q * 0.95) - Cost } end
      Click(AuctionForeverBuyTab)""")
    ok(L('AuctionForeverBuyPanel:IsShown() and not AuctionForeverSellPanel:IsShown() and not AuctionForeverAHPanel:IsShown()'), 'AF Buy shows its panel only')
    ok(L('AuctionForeverBuyTab._selected and not AuctionForeverSellTab._selected and not AuctionForeverAHTab._selected and not AuctionHouseFrame.BuyTab._selected'), 'AF Buy highlighted, other tabs not')
    ok(L('AF_NS.Trade.SelectedBuy() and AF_NS.Trade.SelectedBuy().id') == 2589, 'first flip target selected')
    # The list is kept until you refresh: switching tabs or sorting doesn't rebuild it.
    X('TargetCalls = 0; local F = AF_NS.UI.FlipTargets; AF_NS.UI.FlipTargets = function() TargetCalls = TargetCalls + 1 return F() end')
    X('Click(AuctionForeverSellTab); Click(AuctionForeverBuyTab); AF_NS.Trade.SetBuySort("profit"); AF_NS.Trade.SetBuySort("plan")')
    ok(L('TargetCalls') == 0, f"switching back to AF Buy and sorting reuse the loaded list ({L('TargetCalls')} rebuilds)")
    ok(L('AF_NS.Trade.SelectedBuy() and AF_NS.Trade.SelectedBuy().id') == 2589, 'same list after switching tabs')
    X('AF_NS.UI.ScanDone(); AdvanceTime(0.2)')
    ok(L('TargetCalls') == 1, f"a finished scan rebuilds the list while AF Buy is open ({L('TargetCalls')})")
    X('Click(AuctionForeverSellTab); AF_NS.UI.ScanDone(); AdvanceTime(0.2)')
    ok(L('TargetCalls') == 1, 'AF Buy closed: no rebuild yet')
    X('Click(AuctionForeverBuyTab)')
    ok(L('TargetCalls') == 2, 'opening AF Buy after a scan rebuilds it once')
    X('Click(AuctionForeverSellTab); OldGM = GetMoney; local G = GetMoney() + 5000; GetMoney = function() return G end; Click(AuctionForeverBuyTab)')
    ok(L('TargetCalls') == 3, 'your gold changed: opening AF Buy rebuilds the list')
    X('Click(AuctionForeverSellTab); Click(AuctionForeverBuyTab); GetMoney = OldGM')
    ok(L('TargetCalls') == 3, 'same gold: reopening reuses it')
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
    b = L('AuctionForeverDB.buys and AuctionForeverDB.buys[#AuctionForeverDB.buys]')
    ok(b is not None and b[2] == 2589 and b[3] == 10 and b[4] == 260 and b[5] == 164, f'purchase remembered: 10 for 2s 60c, plan expected 1s 64c each ({b and list(b.values())})')
    # not a commodity: buys the cheapest listing within the max, one per click
    X('Click(AuctionForeverBuyPanel.Buy)')
    c = L('LastCall("PlaceBid")')
    ok(c is not None and c[2] == 77 and c[3] == 380, f'item flip: buys the cheapest listing within the max (auction {c and c[2]} for {c and c[3]})')
    # the resale no longer works on current data (price fell, item not a flip any more): cancelled
    X('ResaleNil = true; Calls = {}; AF_NS.Trade.SelectBuy(1); Click(AuctionForeverBuyPanel.Buy); FireEvent("COMMODITY_PRICE_UPDATED", 26, 260); ResaleNil = nil')
    ok(L('LastCall("CancelCommoditiesPurchase") ~= nil') and L('LastCall("ConfirmCommoditiesPurchase") == nil') and 'resale' in str(L('AuctionForeverBuyPanel.Status:GetText()')).lower(),
       'resale rechecked at the live price: no longer a flip, cancelled: ' + str(L('AuctionForeverBuyPanel.Status:GetText()')))
    # over budget: cancelled
    X('Money = 50000; Calls = {}; AF_NS.Trade.SelectBuy(1); Click(AuctionForeverBuyPanel.Buy); FireEvent("COMMODITY_PRICE_UPDATED", 26, 260000)')
    ok(L('LastCall("CancelCommoditiesPurchase") ~= nil') and L('LastCall("ConfirmCommoditiesPurchase") == nil'), 'total over the flip budget: cancelled')
    X('Money = 2000000')
    # stale data: selecting re-checks the item quietly
    X('AuctionForeverDB.fresh.items[14047][4] = Now - 600; LookupSpy = {}; AF_NS.Trade.SelectBuy(2)')
    ok(L('LookupSpy[1] == nil'), 'selecting a flip target does not start a price check (the purchase gets the live price)')
    # Refresh prices: re-checks the listed targets on purpose
    ok(L('AuctionForeverBuyPanel.Cover ~= nil and AuctionForeverSellPanel.Cover ~= nil'), "AF pages cover Blizzard's tab strip at the top")
    ok(L('AuctionForeverBuyPanel.Refresh:GetText()') in (None, ''), 'refresh is the round button at the top right (no text)')
    X('TargetCalls = 0; LookupSpy = {}; Click(AuctionForeverBuyPanel.Refresh)')
    ok(L('LookupSpy[1] ~= nil and #LookupSpy[1].ids >= 1 and #LookupSpy[1].ids <= 20'), 'Refresh prices re-checks the listed targets')
    # another lookup running: the refresh waits and runs right after it, not dropped
    X('LookupSpy = {}; RealBusy = AF_NS.Scan.Busy; AF_NS.Scan.Busy = function() return true end; Click(AuctionForeverBuyPanel.Refresh)')
    ok(L('LookupSpy[1] == nil'), 'while another scan runs: no lookup started yet')
    X('AF_NS.Scan.Busy = RealBusy; AF_NS.UI.ScanDone(); AdvanceTime(0.2)')
    ok(L('LookupSpy[1] ~= nil'), 'when it finishes: the waiting refresh runs')
    # empty list explains why
    X('FlipTargets = {}; AF_NS.Trade.RefreshBuy()')
    ok(L('AuctionForeverBuyPanel.Empty:IsShown()') and L('AuctionForeverBuyPanel.Empty:GetText()') == 'No flip targets right now.',
       'no targets: one line in the table says so: ' + str(L('AuctionForeverBuyPanel.Empty:GetText()')))
    ok(not L('AuctionForeverBuyPanel.Skip:IsEnabled()'), 'no targets: Next is greyed out')
    ok(L('AuctionForeverBuyPanel.Refresh._template') == 'RefreshButtonTemplate' and L('AuctionForeverSellPanel.Refresh._template') == 'RefreshButtonTemplate',
       "both AF pages use Blizzard's sharp refresh button")
    ok(L('AuctionForeverBuyPanel.Refresh:GetFrameLevel() > AuctionForeverBuyPanel.Cover:GetFrameLevel()'), 'refresh button sits above the cover strip')
    ok(L('AuctionForeverSellPanel:GetFrameLevel()') > 350 and L('AuctionForeverSellPanel:GetFrameLevel()') < 1000,
       "AF pages sit above Blizzard's sell item box and Post button (level 350), below its dialogs (1000)")

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
    # AF Sell agrees with the tooltip: an item whose Rec is Vendor isn't in the queue.
    X('RealRec = AF_NS.Core.Recommend; AF_NS.Core.Recommend = function(I, V, P) if I and I.id == 2589 then return "Vendor" end return RealRec(I, V, P) end')
    vq = L('AF_NS.Trade.BuildQueue()')
    ok(not any(vq[i].id == 2589 for i in range(1, len(vq) + 1)), 'Rec says Vendor: not in the AF Sell list (same advice as the tooltip)')
    X('AF_NS.Core.Recommend = RealRec')
    # Not a steady seller with the cheapest listing far above what buyers paid: priced at what buyers paid.
    X("""RealSt, RealSP = AF_NS.Core.Status, AF_NS.Core.SellPrice
      AF_NS.Core.Status = function() return "slow" end
      AF_NS.Core.SellPrice = function(I, Q, Lo) return 3519, 24, 3, Q, "flooding" end
      MQ = AF_NS.Trade.BuildQueue()
      AF_NS.Core.Status, AF_NS.Core.SellPrice = RealSt, RealSP""")
    mg = [L(f'MQ[{i}]') for i in range(1, int(L('#MQ')) + 1)]
    lg = [g for g in mg if g.id == 2589]
    mk = L('AF_NS.Core.Market(AF_NS.Core.Info(2589))')
    ok(lg and lg[0].price == int(max(mk, L('math.ceil(AF_NS.UI.Vendor(2589) / 0.95)'))) and lg[0].flag == 'market',
       f"slow seller, cheapest listing far above sales: priced at what buyers paid ({lg and lg[0].price} vs market {mk})")
    q = L('AF_NS.Trade.SellQueue()')
    ids = [q[i].id for i in range(1, len(q) + 1)] if q else []
    ok(2589 in ids and 14047 in ids, f'sell queue has the AH items from the bags: {ids}')
    ok(999999 not in ids and 424242424 not in ids, 'bound items and items with no auction data left out')
    ok(10620 not in ids, 'items worth more at the vendor left out')
    lin = [q[i] for i in range(1, len(q) + 1) if q[i].id == 2589]
    ok(lin and lin[0].count == 25, f'stacks of the same item grouped: {lin and lin[0].count}')
    ok(L('LookupSpy[1] == nil or #LookupSpy[1].ids == 1'), 'opening AF Sell checks at most the selected item, not the whole queue')
    X('LookupSpy = {}; Click(AuctionForeverSellPanel.Refresh)')
    ok(L('LookupSpy[1] ~= nil') and sorted(L('LookupSpy[1].ids').values()) == sorted(ids), 'Refresh prices re-checks the whole queue')
    ok(L('AF_NS.Trade.SelectedSell() ~= nil') and ids and L('AF_NS.Trade.SelectedSell().id') == ids[0], 'first queue item selected')
    X('AF_NS.Trade.SelectSellId(2589)')
    price = L('AF_NS.Trade.SellPrice()')
    qty = L('tonumber(AuctionForeverSellPanel.Qty:GetText())')
    ok(price is not None and price >= 6 and price == int(price), f'price prefilled, whole copper, not below vendor (5c + cut): {price}')
    ok(qty is not None and 1 <= qty <= 25, f'quantity prefilled: {qty}')
    ok(L('AF_NS.Trade.SellDuration()') in (1, 2, 3), 'duration chosen')
    ok('Deposit' in str(L('AuctionForeverSellPanel.Deposit:GetText()')), 'deposit shown: ' + str(L('AuctionForeverSellPanel.Deposit:GetText()')))
    X('SavedCost = AF_NS.Trade.SelectedSell().cost; AF_NS.Trade.SelectedSell().cost = nil; AF_NS.Trade.UpdateDeposit()')
    ok('Expected earnings' in str(L('AuctionForeverSellPanel.Deposit:GetText()')), 'not bought: expected earnings shown: ' + str(L('AuctionForeverSellPanel.Deposit:GetText()')))
    # Expected profit: 10 at 1s, paid 50c each, 80% sell, 20c deposit: 0.8 x (950 - 500) - 0.2 x 20 = 356
    # 10 at 1s, paid 97c, 50% sell, 1s deposit: 0.5 x (950 - 970) - 0.5 x 100 = -60
    e = L('(AF_NS.Core.ExpectedPost({ sellThrough = 0.8 }, 100, 10, 20, 50))')
    ok(e == 356, f'expected profit = chance x (after cut - paid) - deposit lost when unsold: {e}')
    e2 = L('(AF_NS.Core.ExpectedPost({ sellThrough = 0.5 }, 100, 10, 100, 97))')
    ok(e2 == -60, f'a thin margin with a big deposit is an expected loss: {e2}')
    X('AF_NS.Trade.SelectedSell().cost = 3; AF_NS.Trade.UpdateDeposit()')
    ok('Expected profit' in str(L('AuctionForeverSellPanel.Deposit:GetText()')), 'bought items: expected profit shown')
    X('AF_NS.Trade.SelectedSell().cost = SavedCost; AF_NS.Trade.UpdateDeposit()')
    # Post (commodity, no confirmation needed): PostCommodity(location, duration, qty, unit price)
    X('Calls = {}; AF_NS.Trade.SetSellPrice(47); AuctionForeverSellPanel.Qty:SetText("12"); AF_NS.Trade.SetSellDuration(2); Click(AuctionForeverSellPanel.Post)')
    c = L('LastCall("PostCommodity")')
    ok(c is not None and L('LastCall("PostCommodity")[2].bag') == 0 and L('LastCall("PostCommodity")[2].slot') == 1 and c[3] == 2 and c[4] == 12 and c[5] == 47,
       f'Post calls PostCommodity(bag 0 slot 1, 8 h, 12, 47c): {c and [c[3], c[4], c[5]]}')
    ok(L('AF_NS.Trade.SelectedSell().id') != 2589, 'after posting: next item')
    mp = L('AuctionForeverDB.myposts and AuctionForeverDB.myposts[#AuctionForeverDB.myposts]')
    ok(mp is not None and mp[2] == 2589 and mp[3] == 12 and mp[4] == 47, f'your post is remembered (so it is not counted as other sellers posting): {mp and list(mp.values())}')
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
    # bought with AF Buy at 26c each: AF Sell shows it and asks before selling at a loss
    X('AF_NS.Trade.SelectSellId(2589)')
    info = str(L('AuctionForeverSellPanel.Info:GetText()'))
    ok('You paid' in info and '26c' in info, 'AF Sell shows what you paid: ' + info.split(chr(10))[-1])
    X('Calls = {}; AF_NS.Trade.SetSellPrice(20); Click(AuctionForeverSellPanel.Post)')
    ok(L('LastCall("PostCommodity") == nil') and 'what you paid' in str(L('AuctionForeverSellPanel.Status:GetText()')), 'below what you paid: not posted on the first click')
    X('Click(AuctionForeverSellPanel.Post)')
    ok(L('LastCall("PostCommodity") ~= nil'), 'second click posts at a loss on purpose')
    # Expired twice since you bought it: stop reposting at your cost; suggest the market price and say so.
    X("""AuctionForeverDB.mysales = AuctionForeverDB.mysales or {}
      NSales = #AuctionForeverDB.mysales
      table.insert(AuctionForeverDB.mysales, { time() + 10, 2589, 5, 0, "expired" })
      table.insert(AuctionForeverDB.mysales, { time() + 20, 2589, 5, 0, "expired" })
      Click(AuctionForeverBuyTab); Click(AuctionForeverSellTab); AF_NS.Trade.SelectSellId(2589)""")
    hint = str(L('AuctionForeverSellPanel.Hint:GetText()'))
    ok(L('AF_NS.Trade.SelectedSell().flag') == 'cutloss' and 'cut the loss' in hint.lower(), 'expired twice: suggests cutting the loss: ' + hint)
    X('for i = #AuctionForeverDB.mysales, NSales + 1, -1 do table.remove(AuctionForeverDB.mysales, i) end')
    # Your own auctions (once the game lists them) aren't stock in front of you.
    X("""C_AuctionHouse.GetOwnedAuctions = function() return {
        { itemKey = { itemID = 2589 }, buyoutAmount = 47, quantity = 12, status = 0 },
        { itemKey = { itemID = 2589 }, buyoutAmount = 47, quantity = 3, status = 0 },
        { itemKey = { itemID = 14047 }, buyoutAmount = 900, quantity = 1, status = 1 } } end
      FireEvent("OWNED_AUCTIONS_UPDATED")""")
    ok(L('AF_NS.Core.MyListings and AF_NS.Core.MyListings[2589] and AF_NS.Core.MyListings[2589][47]') == 15 and L('AF_NS.Core.MyListings[14047] == nil'),
       'own active listings known per item and price (sold ones left out)')
    X('C_AuctionHouse.GetOwnedAuctions = nil; AF_NS.Core.MyListings = nil')
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

# Item names: client cache first, then names learned before, then names shipped in the cloud data, then "loading...".
X("""RealGetItemInfo = C_Item.GetItemInfo
  C_Item.GetItemInfo = function(id) if id == 880001 or id == 880002 then return nil end return RealGetItemInfo(id) end
  AuctionForeverData.names = AuctionForeverData.names or {}
  AuctionForeverData.names[880001] = "Cloud Name"
  AuctionForeverDB = AuctionForeverDB or {}; AuctionForeverDB.names = AuctionForeverDB.names or {}
  AuctionForeverDB.names[880001] = nil; AuctionForeverDB.names[880002] = nil""")
ok(L('(AF_NS.UI.ItemName(880001))') == 'Cloud Name', 'name from the cloud data shows instantly, with nothing cached in the client')
ok('loading' in str(L('(AF_NS.UI.ItemName(880002))')), 'unknown name: "loading..."')
# A name that arrives in the background (preload) is saved, even if no list row ever showed it.
X("""C_Item.GetItemInfo = function(id) if id == 880002 then return "Learned Name", nil, 3 end return RealGetItemInfo(id) end
  FireEvent("GET_ITEM_INFO_RECEIVED", 880002, true)""")
n = L('AuctionForeverDB.names[880002]')
ok(n is not None and n[1] == 'Learned Name', 'names that arrive in the background are saved for next time')
X("""C_Item.GetItemInfo = function(id) if id == 880002 then return nil end return RealGetItemInfo(id) end""")
ok(L('(AF_NS.UI.ItemName(880002))') == 'Learned Name', 'saved name used when the client has forgotten it (next login)')
X('C_Item.GetItemInfo = RealGetItemInfo')
# AF Sell / AF Buy redraw when a name arrives (no more "loading..." until you click around).
X("""Redrawn = 0; local Orig = AF_NS.Trade.RedrawNames; AF_NS.Trade.RedrawNames = function() Redrawn = Redrawn + 1; Orig() end
  FireEvent("GET_ITEM_INFO_RECEIVED", 880003, true); FireEvent("GET_ITEM_INFO_RECEIVED", 880004, true); AdvanceTime(0.5)
  AF_NS.Trade.RedrawNames = Orig""")
ok(L('Redrawn') == 1, f"AF Buy/Sell redraw once when names arrive ({L('Redrawn')} redraws for 2 names)")

# Adaptive sales windows: a short window counts when it holds enough separate purchases (events, not units).
X("""function MkAuc(N, Q) local A = {} for i = 1, N do A[9000 + i] = { Q or 10, 100 + i, 40000 } end return A end
  function MkMap(A) local M = {} for _, R in pairs(A) do M[R[2]] = (M[R[2]] or 0) + R[1] end return M end
  function Bought(A, K) local B = {} local n = 0 for id, R in pairs(A) do n = n + 1; B[id] = { n <= K and R[1] - 1 or R[1], R[2], R[3] } end return B end
  T0 = 1800000000
  function Window(id, Mins, Events)
    AuctionForeverDB = AuctionForeverDB or {}; AuctionForeverDB.obs = AuctionForeverDB.obs or {}; AuctionForeverDB.base = AuctionForeverDB.base or {}; AuctionForeverDB.fresh = AuctionForeverDB.fresh or { items = {} }
    AuctionForeverDB.obs[id] = nil
    local A = MkAuc(20)
    AuctionForeverDB.base[id] = { t = T0, ladder = {}, auc = A, cov = 1000 }
    local After = Bought(A, Events)
    return AF_NS.Scan.Observe(id, MkMap(After), nil, After, 1000, T0 + Mins * 60, true)
  end""")
ok(L('(Window(777001, 4, 12))') == 'measured', 'busy item: 4 min window with 12 separate purchases is measured')
ok(L('(Window(777002, 4, 3))') == 'soon' and L('AuctionForeverDB.base[777002].t') == L('T0'), 'quiet item: 4 min with 3 purchases only refreshes prices, starting point kept')
ok(L('(Window(777003, 1, 20))') == 'soon', 'any window under 2 min only refreshes prices, even with many purchases')
ok(L('(Window(777004, 16, 0))') == 'measured', 'slow item: 15+ min counts even with no purchases (it had its fair chance)')
ok(L('(Window(777005, 6, 1))') == 'soon', 'one buyer taking a lot is one purchase: 6 min window not enough')
# New listings in a window (other sellers posting): listings that weren't there at the starting point.
X("""AuctionForeverDB.obs[777010] = nil
  local A = MkAuc(20)
  AuctionForeverDB.base[777010] = { t = T0, ladder = {}, auc = A, cov = 1000 }
  local After = Bought(A, 12)
  After[99901] = { 7, 95, 40000 }; After[99902] = { 3, 200, 40000 }
  AF_NS.Scan.Observe(777010, MkMap(After), nil, After, 1000, T0 + 240, true)""")
o = L('AuctionForeverDB.obs[777010] and AuctionForeverDB.obs[777010][#AuctionForeverDB.obs[777010]]')
ok(o is not None and o[8] == 7, f'new listings counted from listing IDs: the 7 at 95c; the 3 at 2s (far above) are no competition ({o and o[8]})')
# Ladders only (full scan): stock now - stock before + sold, at the cheap end. 10 listed, 6 sold, 6 new at 105c.
X("""AuctionForeverDB.obs[777011] = nil
  AuctionForeverDB.base[777011] = { t = T0, ladder = { { 100, 10, 0 } }, qty = 10 }
  AF_NS.Scan.Observe(777011, { [100] = 4, [105] = 6 }, nil, nil, nil, T0 + 1200, true)""")
o = L('AuctionForeverDB.obs[777011] and AuctionForeverDB.obs[777011][#AuctionForeverDB.obs[777011]]')
ok(o is not None and o[3] == 6 and o[8] == 6, f'ladder window: 6 sold, 6 new ({o and o[3]}, {o and o[8]})')
X("""AuctionForeverDB.obs[777012] = nil
  AuctionForeverDB.base[777012] = { t = T0, ladder = { { 100, 10, 0 } }, qty = 10 }
  AF_NS.Scan.Observe(777012, { [100] = 4, [150] = 6 }, nil, nil, nil, T0 + 1200, true)""")
o = L('AuctionForeverDB.obs[777012] and AuctionForeverDB.obs[777012][#AuctionForeverDB.obs[777012]]')
ok(o is not None and o[8] == 0, f'6 new at 150c with 100c lowest: far above, not counted ({o and o[8]})')
# Full scan (no auction IDs) then lookups minutes later: the first lookup keeps its IDs as an exact starting point,
# the next compares listing by listing and measures the busy item.
X("""AuctionForeverDB.obs[777010] = nil
  A = MkAuc(20)
  AuctionForeverDB.base[777010] = { t = T0, ladder = { { 101, 10, 0 } }, cov = 1000 }  -- from a full scan: ladder only
  St1 = AF_NS.Scan.Observe(777010, MkMap(A), nil, A, 1000, T0 + 180, true)
  B2 = Bought(A, 12)
  St2 = AF_NS.Scan.Observe(777010, MkMap(B2), nil, B2, 1000, T0 + 360, true)""")
o = L('AuctionForeverDB.obs[777010] and AuctionForeverDB.obs[777010][1]')
ok(L('St1') == 'soon' and L('St2') == 'measured' and o is not None and o[3] == 12 and abs(o[2] - 180 / 3600) < 1e-9,
   f"full scan then two lookups 3 min apart: exact window measured ({o and o[3]} sold over {o and round(o[2]*60)} min)")

# Mail: "Auction successful" invoices and "Auction expired" mail are recorded once each as your own exact results.
# Nothing is taken from the mailbox.
X("""AUCTION_SOLD_MAIL_SUBJECT = "Auction successful: %s"; AUCTION_EXPIRED_MAIL_SUBJECT = "Auction expired: %s"
  AuctionForeverDB = AuctionForeverDB or {}; AuctionForeverDB.names = AuctionForeverDB.names or {}
  AuctionForeverDB.names[2589] = { "Linen Cloth", 1 }; AuctionForeverDB.mysales = nil
  Took = false
  TakeInboxMoney = function() Took = true end; TakeInboxItem = function() Took = true end; AutoLootMailItem = function() Took = true end
  Inbox = {
    { sender = "Stormwind Auction House", subject = "Auction successful: Linen Cloth", money = 950, days = 29.5,
      invoice = { "seller", "Linen Cloth", "Buyer", 1000, 1000, 0, 50, 0, 0, 0, 40 } },
    { sender = "Stormwind Auction House", subject = "Auction expired: Item 4306", money = 0, days = 29.9, item = { "Item 4306", 4306, 0, 15 } },
    { sender = "Friend", subject = "hello", money = 500, days = 2 },
  }
  GetInboxNumItems = function() return #Inbox, #Inbox end
  GetInboxHeaderInfo = function(i) local M = Inbox[i]; return nil, nil, M.sender, M.subject, M.money, 0, M.days, M.item and 1 or 0, false end
  GetInboxInvoiceInfo = function(i) local M = Inbox[i]; if M.invoice then return unpack(M.invoice) end end
  GetInboxItem = function(i, j) local M = Inbox[i]; if M.item then return unpack(M.item) end end
  time = function() return 1800000000 end
  FireEvent("MAIL_SHOW"); FireEvent("MAIL_INBOX_UPDATE"); FireEvent("MAIL_INBOX_UPDATE")""")
ms = L('AuctionForeverDB.mysales')
rows = [list(r.values()) for r in ms.values()] if ms else []
sold = [r for r in rows if r[4] == 'sold']; expd = [r for r in rows if r[4] == 'expired']
ok(len(rows) == 2, f'mail: 2 auction results recorded once each ({len(rows)} rows)')
ok(sold and sold[0][1] == 2589 and sold[0][2] == 40 and sold[0][3] == 1000, f'sold invoice: Linen x40 for 1000c ({sold})')
ok(expd and expd[0][1] == 4306 and expd[0][2] == 15, f'expired mail: item 4306 x15 ({expd})')
ok(not L('Took'), 'nothing taken from the mailbox')
# You take the gold from the sale mail (its money drops to 0) and the inbox updates: still recorded once.
X('Inbox[1].money = 0; FireEvent("MAIL_INBOX_UPDATE"); FireEvent("MAIL_SHOW"); FireEvent("MAIL_INBOX_UPDATE")')
ok(int(L('#AuctionForeverDB.mysales')) == 2, f"taking the gold doesn't record the sale again ({L('#AuctionForeverDB.mysales')} rows)")
# Sales already recorded twice by the old key are cleaned up once; two real sales read together are kept.
X('''SavedSales = AuctionForeverDB.mysales; local T = time()
  AuctionForeverDB.mailfix1 = nil
  AuctionForeverDB.mysales = { { T, 4234, 22, 5214, "sold" }, { T, 4306, 20, 4000, "sold" }, { T, 4306, 20, 4000, "sold" },
    { T + 1, 4306, 20, 4000, "sold" }, { T + 4, 4234, 22, 5214, "sold" }, { T, 4235, 4, 0, "expired" } }
  FireEvent("MAIL_INBOX_UPDATE")''')
ok(int(L('#AuctionForeverDB.mysales')) == 4 and L('AuctionForeverDB.mailfix1'), f"old double-counted sales removed once, same-time sales kept ({L('#AuctionForeverDB.mysales')} rows)")
X('AuctionForeverDB.mysales = SavedSales')
I = L('AF_NS.Core.Info(2589)')
ok(I.mySold == 40 and I.mySoldValue == 1000, f'Info: you sold {I.mySold} for {I.mySoldValue}c in the last 3 days')
tl = ' | '.join(' '.join(str(x) for x in v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values())
ok('You sold 40' in tl, 'tooltip shows your own sales: ' + tl)
X("time = function() return 1800000000 + 4 * 86400 end")
ok(L('AF_NS.Core.Info(2589).mySold') in (None, 0), 'own sales older than 3 days drop out of the tooltip count')

# Tooltip: Vendor, AH and Rec first, money in gold/silver/copper colors; details only with Shift.
mc = L('AF_NS.Core.MoneyColor(10203)')
ok('|cffffd7001g|r' in mc and '|cffc7c7cf02s|r' in mc and '|cffeda55f03c|r' in mc, 'money in coin colors: ' + mc)
ok(L('AF_NS.Core.MoneyColor(5)') == '|cffeda55f5c|r' and L('AF_NS.Core.MoneyColor(nil)') == '-', 'copper only; no price shows "-"')
tl = [list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()]
ok([r[0] for r in tl[:3]] == ['Vendor', 'AH', 'Rec'], 'first three lines: Vendor, AH, Rec: ' + str([r[0] for r in tl[:3]]))
ok('Auction' in str(tl[2][1]), 'Linen (sells for far more than 5c vendor): Rec Auction: ' + str(tl[2][1]))
ok('+' in str(tl[2][1]) and ' each' in str(tl[2][1]), 'Rec Auction shows the profit per item over the vendor: ' + str(tl[2][1]))
# The AH price after the 5% cut, minus the vendor price (e.g. 30c -> 28c - 13c = +15c).
v = L('AF_NS.UI.Vendor(2589)'); ah = L('AF_NS.UI.TargetPrice(AF_NS.Core.Info(2589))')
exp = int(ah * 0.95) - v
ok(L(f'AF_NS.Core.MoneyColor({exp})') in str(tl[2][1]), f'profit = AH price after the 5% cut - vendor price ({ah}c, vendor {v}c -> +{exp}c)')
ok(len(tl) == 4 and 'Shift' in str(tl[3][0]), 'without Shift: just the three lines and a Shift hint')
X('IsShiftKeyDown = function() return true end')
tl2 = [list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()]
ok(len(tl2) > 4 and any('Sells' == r[0] for r in tl2), 'with Shift: details shown too')
X('IsShiftKeyDown = function() return false end')
# Vendor wins when the AH, after the 5% cut, pays no more than the vendor.
X('OldInfo = C_Item.GetItemInfo; C_Item.GetItemInfo = function(id) if id == 2589 then return "Linen Cloth", nil, 1, nil, nil, nil, nil, nil, nil, nil, 10^7 end return OldInfo(id) end')
tl3 = [list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()]
ok('Vendor' in str(tl3[2][1]), 'vendor pays more: Rec Vendor: ' + str(tl3[2][1]))
X('C_Item.GetItemInfo = OldInfo')
# An item with no AH data at all still shows its vendor price and Rec Vendor.
tl4 = L('AF_NS.UI.TooltipLines(424242)')
ok(tl4 is not None and 'Vendor' in str(list(tl4[3].values())[1]), 'no AH data: vendor price shown, Rec Vendor')

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
# Full scan bar: fills with a percentage while waiting (estimate from the last wait), resends, logs, times out.
X("""AuctionHouseFrame:Show(); AuctionForeverDB.lastFull = nil; AuctionForeverDB.fullWait = 10; AuctionForeverDB.scanlog = nil
  Replicates = 0; local Old = C_AuctionHouse.ReplicateItems
  C_AuctionHouse.ReplicateItems = function() Replicates = Replicates + 1 end
  AF_NS.UI.ShowAHPanel(); Click(AuctionForeverAHPanel.Full)""")
ok(L('Replicates') == 1, 'full scan asks the server once')
X('AdvanceTime(5); AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)')
bt, bv = str(L('AuctionForeverAHPanel.Bar.Text:GetText()')), L('AuctionForeverAHPanel.Bar:GetValue()')
ok('%' in bt and 0.1 < bv < 0.3, f'waiting: bar fills with a percentage ({bt}, {bv:.2f})')
ok('85 s left' in bt, 'waiting: shows the seconds left: ' + bt)
X('AdvanceTime(16)')
ok(L('Replicates') == 2, 'no answer after 20 s: asked again')
X('AdvanceTime(40)')
ok(L('Replicates') == 4, 'asks every 20 s (20, 40, 60): ' + str(L('Replicates')))
X('AdvanceTime(35)')
ok(not L('AF_NS.Scan.Busy()') and 'asked 4 times' in str(L('AF_NS.Scan.LastResult')), 'gives up after 90 s: ' + str(L('AF_NS.Scan.LastResult')))
log = L('AuctionForeverDB.scanlog[#AuctionForeverDB.scanlog]')
ok(log is not None and log[2] == 'no answer' and log[4] == 4, 'scan log records the failed try')
# The server may still answer after we stopped waiting: that answer is used, not dropped.
X('C_AuctionHouse.GetNumReplicateItems = C_AuctionHouse.GetNumReplicateItems or function() return 0 end; FireEvent("REPLICATE_ITEM_LIST_UPDATE")')
log = L('AuctionForeverDB.scanlog[#AuctionForeverDB.scanlog]')
ok(log is not None and log[2] == 'answered late', 'a late answer is still read: ' + str(log and log[2]))
X('for k = 1, 300 do for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end')
ok(not L('AF_NS.Scan.Busy()'), 'the late listing is read to the end')
# A late answer while a price check runs: kept and read right after the check, not dropped.
X('AF_NS.Scan.WaitGaveUp = true; LateLogN = #AuctionForeverDB.scanlog; LookupStarted = AF_NS.Scan.Lookup({ 2589 }, true)')
ok(L('LookupStarted') == True and L('AF_NS.Scan.Busy()'), 'a price check is running')
X('FireEvent("REPLICATE_ITEM_LIST_UPDATE")')
ok(L('#AuctionForeverDB.scanlog') == L('LateLogN') and L('AF_NS.Scan.LatePending') == True, 'late answer during the check: remembered, not read yet')
X('for k = 1, 40 do AdvanceTime(0.5); for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end')
log = L('AuctionForeverDB.scanlog[#AuctionForeverDB.scanlog]')
ok(log is not None and log[2] == 'answered late' and L('#AuctionForeverDB.scanlog') == L('LateLogN') + 1, 'read after the check finished: ' + str(log and log[2]))
X('for k = 1, 300 do for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end')
ok(not L('AF_NS.Scan.Busy()') and not L('AF_NS.Scan.LatePending'), 'and read to the end')
# The server is still sending when it first says the listing is ready: the scan keeps reading what arrives.
X('''OldNum, OldInfo, OldRep, OldTL = C_AuctionHouse.GetNumReplicateItems, C_AuctionHouse.GetReplicateItemInfo, C_AuctionHouse.ReplicateItems, C_AuctionHouse.GetReplicateItemTimeLeft
  C_AuctionHouse.GetReplicateItemTimeLeft = function() return 3 end
  GrowN = 100
  C_AuctionHouse.ReplicateItems = function() end
  C_AuctionHouse.GetNumReplicateItems = function() return GrowN end
  C_AuctionHouse.GetReplicateItemInfo = function(i) if i <= GrowN then return "x", 1, 1, 1, true, 1, "", 0, 0, 100, 0, false, nil, "o", "o", 0, 600000 + (i % 50), true end end
  AuctionForeverDB.lastFull = nil; AF_NS.Scan.WaitGaveUp = nil
  AF_NS.UI.ShowAHPanel(); Click(AuctionForeverAHPanel.Full); FireEvent("REPLICATE_ITEM_LIST_UPDATE")
  for k = 1, 5 do for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end
  GrowN = 300
  for k = 1, 300 do for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end''')
rd = L('AuctionForeverDB.scanlog[#AuctionForeverDB.scanlog].read')
ok(not L('AF_NS.Scan.Busy()') and rd is not None and rd[1] == 300 and rd[2] == 300,
   f"listing still arriving while read: all 300 read, not the first 100 ({rd and list(rd.values())})")
X('C_AuctionHouse.GetNumReplicateItems, C_AuctionHouse.GetReplicateItemInfo, C_AuctionHouse.ReplicateItems, C_AuctionHouse.GetReplicateItemTimeLeft = OldNum, OldInfo, OldRep, OldTL')
# Deposit from the game decides between durations (commodities).
X("""OldDep = C_AuctionHouse.CalculateCommodityDeposit
  C_AuctionHouse.CalculateCommodityDeposit = function(id, idx, q) return idx * 1000 * q end
  AuctionForeverData.info[777001] = AuctionForeverData.info[777001] or { 0, 1, 1 }""")
ok(L('AF_NS.Core.Deposit({ id = 777001 }, 8, 3)') == 6000, 'deposit for 8 h comes from the game')
ok(L('AF_NS.Core.Deposit({ id = 777002 }, 8, 3)') == 0, 'not a commodity: deposit not known, 0')
X('DepCalls = 0; local F = C_AuctionHouse.CalculateCommodityDeposit; C_AuctionHouse.CalculateCommodityDeposit = function(...) DepCalls = DepCalls + 1 return F(...) end')
ok(L('AF_NS.Core.Deposit({ id = 777001 }, 8, 50)') == 100000 and L('AF_NS.Core.Deposit({ id = 777001 }, 8, 7)') == 14000 and L('DepCalls') == 0,
   'deposit scales with quantity: one game call per item and duration (other stack sizes reuse it)')
X('C_AuctionHouse.CalculateCommodityDeposit = OldDep')
# Stack check: an item whose stack size isn't loaded yet is judged by its type (gear doesn't stack), not hidden.
X("""OldMax, OldInst = C_Item.GetItemMaxStackSizeByID, C_Item.GetItemInfoInstant
  C_Item.GetItemMaxStackSizeByID = function() return nil end""")
ok(L('AF_NS.UI.Stacks(2589)'), 'stack size not loaded, trade good: counts as stackable')
X('C_Item.GetItemInfoInstant = function(id) return id, "Weapon", "", "", 1, 2, 0 end')
ok(not L('AF_NS.UI.Stacks(727)'), 'stack size not loaded, weapon: not stackable')
X('C_Item.GetItemMaxStackSizeByID = function() return 1 end; C_Item.GetItemInfoInstant = OldInst')
ok(not L('AF_NS.UI.Stacks(2589)'), 'loaded stack size of 1 wins')
X('C_Item.GetItemMaxStackSizeByID = OldMax')
# Item details come from caches when the game hasn't loaded the item: saved first, then the cloud file.
X("""AF_NS.UI.ItemName(2589)
  OldGI2 = C_Item.GetItemInfo; C_Item.GetItemInfo = function() return nil end""")
ok(L('AF_NS.UI.Vendor(2589)') == L('AuctionForeverData.info[2589][1]'), 'vendor price from the saved cache when the game has nothing loaded')
nm = L('(AF_NS.UI.ItemName(2589))'); ok(nm == 'Item 2589', 'name from the saved cache: ' + str(nm))
X('AuctionForeverData.info = AuctionForeverData.info or {}; AuctionForeverData.info[777001] = { 123, 3, 1 }; AuctionForeverData.names = AuctionForeverData.names or {}; AuctionForeverData.names[777001] = "Shipped Thing"')
n, q = L('AF_NS.UI.ItemName(777001)')
ok(L('AF_NS.UI.Vendor(777001)') == 123 and n == 'Shipped Thing' and q == 3, f'cloud file details: vendor 123c, name, quality {q}')
X('C_Item.GetItemInfo = OldGI2')
# What can be flipped comes from the commodity flag in the data, not the game's stack size.
X('AuctionForeverData.info[777002] = { 0, 2, 0 }; C_Item.GetItemMaxStackSizeByID = function() return nil end')
ok(L('AF_NS.UI.Flippable(777001)') and not L('AF_NS.UI.Flippable(777002)'), 'commodity flag decides: commodity flips, non-commodity does not')
ok(L('AF_NS.UI.Kind(777001)') == 'commodity' and L('AF_NS.UI.Kind(777002)') == 'item', 'kind from the data file')
X('C_Item.GetItemMaxStackSizeByID = OldMax')
# Tooltip AH line = the target (post) price from your latest data, with how long ago it was checked.
X("""OldCD, OldStatus2, OldNow = AF_NS.Core.SellPrice, AF_NS.Core.Status, time
  AF_NS.Core.Status = function() return "good" end
  AF_NS.Core.SellPrice = function() return 4321, 2, 1, 1 end
  AuctionForeverDB.fresh.items[2589] = { 20, 500, { { 20, 300 } }, 1800000000 }
  time = function() return 1800000000 + 720 end""")
tl = [list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()]
ah = str(tl[1][1])
ok('43s' in ah and '21c' in ah and '|T' not in ah and 'ago' not in ah, 'AH line: target price, fresh data: no icon, no timestamp: ' + ah)
X('time = function() return 1800000000 + 7200 end')
ah2 = str([list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()][1][1])
ok('43s' in ah2 and 'UI-Dialog-Icon-AlertNew' in ah2, 'data over an hour old: warning icon: ' + ah2)
X('AF_NS.Core.Status = function() return "warming up" end')
tl = [list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()]
ok('43s' not in str(tl[1][1]), 'not rated yet: falls back to the recent selling price: ' + str(tl[1][1]))
X('AF_NS.Core.SellPrice, AF_NS.Core.Status, time = OldCD, OldStatus2, OldNow')
# Empty flip list says what the budget is.
X('OldMoney = GetMoney; GetMoney = function() return 15000 end')
er = str(L('AF_NS.UI.FlipEmptyReason()'))
X('GetMoney = OldMoney')
ok('50s' in er or 'budget' in er.lower(), 'empty flip message states the budget: ' + er)
# Budget plan in AF Buy: best combination for your budget first (buying order), the rest greyed out below.
X("""AF_NS.UI.FlipRows, AF_NS.UI.FlipTargets = RealFlipRows, RealFlipTargets
  OldOpts, OldFlippable, OldMoney3, OldStatus = AF_NS.Core.FlipOptions, AF_NS.UI.Flippable, GetMoney, AF_NS.Core.Status
  Gold = 19981
  GetMoney = function() return Gold end
  local Opts = {
    [2589] = { { qty = 150, buyQty = 150, buyUpTo = 20, cost = 3000, resell = 30, hours = 2, durationIndex = 1, profit = 1275 },
               { qty = 300, buyQty = 300, buyUpTo = 20, cost = 6000, resell = 30, hours = 2, durationIndex = 1, profit = 2550 } },
    [2592] = { { qty = 20, buyQty = 20, buyUpTo = 60, cost = 1200, resell = 120, hours = 2, durationIndex = 1, profit = 1080 } },
    [4306] = { { qty = 5, buyQty = 5, buyUpTo = 1500, cost = 7500, resell = 2000, hours = 8, durationIndex = 2, profit = 1600 } },
  }
  AF_NS.Core.FlipOptions = function(I, Cap) local O = Opts[I.id] or {} local T = {} for _, o in ipairs(O) do if o.cost <= Cap then T[#T+1] = o end end return T end
  AF_NS.UI.ResetBudget()""")
rows = L('AF_NS.UI.FlipRows()')
lst = [(rows[i].id, rows[i].plan, rows[i].flip.qty) for i in range(1, int(L('#AF_NS.UI.FlipRows()')) + 1)] if rows else []
lp = L('AF_NS.UI.LastPlan')
ok(lp is not None and lp.budget == 14981 or (lp and abs(lp.budget - 14981.5) < 1), f'budget = 1g 99s 81c minus the 50s kept ({lp and lp.budget})')
ok(lst[:2] == [(2592, True, 20), (2589, True, 150)] if len(lst) >= 2 else False, f'plan: Wool first (best return), then Linen within the 40% item cap: {lst}')
ok(not any(r[0] == 4306 for r in lst), 'the Flips list keeps only what you can do now')
tg = L('AF_NS.UI.FlipTargets()')
tl2 = [(tg[i].id, tg[i].plan) for i in range(1, int(L('#AF_NS.UI.FlipTargets()')) + 1)]
ok(tl2[-1] == (4306, False), f'AF Buy also lists targets your gold cannot reach yet, last: {tl2}')
need = L('(function() for _, E in ipairs(AF_NS.UI.FlipTargets()) do if E.id == 4306 then return E.need end end end)()')
ok(need is not None and abs(need - L('AF_NS.Core.GoldFor(7500)')) <= 1, f'a target shows the gold it needs: {need}')
# An option that fits your budget counts as buyable even when it only came from the any-gold list.
X("""MinSeen = {}
  local Prev = AF_NS.Core.FlipOptions
  AF_NS.Core.FlipOptions = function(I, Cap, Min)
    MinSeen[#MinSeen + 1] = Min
    if I.id == 2592 then
      if Cap == math.huge then return { { qty = 20, buyQty = 20, buyUpTo = 60, cost = 1200, resell = 120, hours = 2, durationIndex = 1, profit = 1080 } } end
      return {}
    end
    return Prev(I, Cap, Min)
  end
  AF_NS.UI.ResetBudget(); AF_NS.Scan.Version = AF_NS.Scan.Version + 1 -- not the cached list
  for _, E in ipairs(AF_NS.UI.FlipTargets()) do if E.id == 2592 then Row2592 = E end end
  AF_NS.Scan.Version = AF_NS.Scan.Version + 1
  AF_NS.Core.FlipOptions = Prev""")
ok(L('Row2592 ~= nil and Row2592.now[Row2592.best] == true'), 'an any-gold option within your budget is buyable now (no "at X gold")')
ok(len(L('MinSeen')) > 0 and all(m == L('AF_NS.Core.MinFlipProfitFor(AF_NS.UI.FlipBudget())') for m in L('MinSeen').values()), f"every option search uses your budget's minimum profit ({set(L('MinSeen').values())})")
X("""AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SetBuySort("gold")""")
order = [L(f'AF_NS.Trade.Rows()[{i}].need') for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
ok(order == sorted(order), f'sort by gold needed: lowest first {order}')
X('AF_NS.Trade.SetBuySort("profit")')
pr = [L(f'AF_NS.Trade.Rows()[{i}].best.profit') for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
ok(pr == sorted(pr, reverse=True), f'sort by profit: highest first {pr}')
X('AF_NS.Trade.SetBuySort("plan")')
tg = L('AF_NS.Trade.TargetGold()')
mins = [L(f'AF_NS.Trade.Rows()[{i}].minGold') for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
ok(tg is not None and tg == -(-min(m for m in mins if m is not None) // 100) * 100, f'target budget = least gold any target needs, rounded up to the silver: {tg}')
X('AF_NS.Trade.DrawBuy()')
bt, tt = str(L('AuctionForeverBuyPanel.Budget:GetText()')), str(L('AuctionForeverBuyPanel.Target:GetText()'))
ok(bt.startswith('Flip Budget: |cff') and 'Target Budget: |cff' in tt, f'header rows: colored Flip Budget, then Target Budget ({bt!r} / {tt!r})')
ok(L('AF_NS.Trade.Rows()[1].plan') == True, 'back to plan order: plan first')
# Scroll bars: shown when a list is longer than its 14 rows; dragging scrolls; "1-14 of N" under it.
X('''SB = AF_NS.Trade.Rows(); SBn = #SB
  for k = 1, 30 do SB[#SB + 1] = SB[((k - 1) % SBn) + 1] end
  AF_NS.Trade.DrawBuy()''')
BP = 'AuctionForeverBuyPanel'
ok(L('SBn') > 0 and L(f'{BP}.Bar:IsShown()') and L(f'{BP}.Bar.Count:GetText()') == f"1-14 of {L('#SB')}", 'AF Buy: long list shows a scroll bar and 1-14 of N: ' + str(L(f'{BP}.Bar.Count:GetText()')))
X(f'{BP}.Bar:SetValue(5)')
ok(L(f'{BP}.Rows[1].id') == L('SB[6].id') and L(f'{BP}.Bar.Count:GetText()') == f"6-19 of {L('#SB')}", 'AF Buy: dragging the bar scrolls the list: ' + str(L(f'{BP}.Bar.Count:GetText()')))
X(f'{BP}._scripts.OnMouseWheel({BP}, -1); AF_NS.Trade.DrawBuy()')
ok(L(f'{BP}.Bar:GetValue()') == 8, 'AF Buy: the mouse wheel moves the bar too: ' + str(L(f'{BP}.Bar:GetValue()')))
X('for k = #SB, SBn + 1, -1 do SB[k] = nil end; AF_NS.Trade.DrawBuy()')
ok(not L(f'{BP}.Bar:IsShown()') and not L(f'{BP}.Bar.Count:IsShown()'), 'AF Buy: short list, no scroll bar')
X('''SQ = AF_NS.Trade.SellQueue(); SQn = #SQ
  local Src = SQn > 0 and SQ or AF_NS.Trade.BuildQueue()
  for k = 1, 20 do SQ[#SQ + 1] = Src[((k - 1) % #Src) + 1] end
  AF_NS.Trade.DrawSell()''')
SP = 'AuctionForeverSellPanel'
ok(L(f'{SP}.Bar:IsShown()') and L(f'{SP}.Bar.Count:GetText()') == f"1-14 of {L('#SQ')}", 'AF Sell: long list shows a scroll bar: ' + str(L(f'{SP}.Bar.Count:GetText()')))
X(f'{SP}.Bar:SetValue(3)')
ok(L(f'{SP}.QueueRows[1].id') == L('SQ[4].id'), 'AF Sell: dragging the bar scrolls the list')
X('for k = #SQ, SQn + 1, -1 do SQ[k] = nil end; AF_NS.Trade.DrawSell()')
# A listing under the vendor price (any item): an AF Buy row with "vendor it", no sales data needed.
X('''local Row = {}
  for i, N in ipairs(AuctionForeverData.fields) do
    if N == "low" then Row[i] = 500 elseif N == "qty" then Row[i] = 4 elseif N == "ladder" then Row[i] = { { 500, 3 }, { 2000, 1 } } end
  end
  AuctionForeverData.items[990001] = Row
  AuctionForeverData.info[990001] = { 1000, 1, 1 }
  AF_NS.Scan.Version = AF_NS.Scan.Version + 1
  AF_NS.Trade.RefreshBuy()
  for i, E in ipairs(AF_NS.Trade.Rows()) do if E.id == 990001 then VRow, VIdx = E, i end end''')
ok(L('VRow and VRow.flip.vendor and VRow.flip.profit == 1500 and VRow.flip.buyQty == 3'), f"listings under the vendor price are a buy target: 3 at 5s, vendor 10s -> 15s ({L('VRow and VRow.flip.profit')})")
X('AF_NS.Trade.SelectBuy(VIdx); AF_NS.Trade.DrawBuy()')
cells = L('(function() local t = {} for _, f in ipairs(AllFramesForTest) do if f._kind == "FontString" and type(f._text) == "string" and (f._text:find("vendor it") or f._text:find("sell them to a vendor")) then t[#t+1] = f._text end end return #t end)()')
ok(cells >= 2, f'row says "vendor it" and the detail says to sell to a vendor ({cells})')
if L('LastCall') is not None:
    X('AF_NS.Scan.Kind[990001] = "commodity"; Calls = {}; AF_NS.Trade.SelectBuy(VIdx); AF_NS.Trade.BuyClick(); FireEvent("COMMODITY_PRICE_UPDATED", 500, 1500)')
    ok('Confirm' in str(L('AuctionForeverBuyPanel.Buy:GetText()')), 'vendor buy at the planned price: asks to confirm (no sales data needed)')
    X('Click(AuctionForeverBuyPanel.Buy)')
    X('AF_NS.Trade.RefreshBuy(); for i, E in ipairs(AF_NS.Trade.Rows()) do if E.id == 990001 then VIdx = i end end')
    X('Calls = {}; AuctionForeverBuyPanel.Buy:SetText("Buy"); AF_NS.Trade.SelectBuy(VIdx)')
X('AuctionForeverData.items[990001] = nil; AuctionForeverData.info[990001] = nil; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy()')
# Buying uses the budget for this visit: after spending 12s, the budget drops by 12s.
X('Gold = Gold - 1200')
b2 = L('AF_NS.UI.FlipBudget()')
ok(abs(b2 - (14981.5 - 1200)) < 1, f'after spending 12s: budget {b2} (was 14981)')
X('Gold = Gold + 50000')
ok(L('AF_NS.UI.FlipBudget()') > 30000, 'gold went up (a sale): budget grows')
Calls2 = 0
X("""local Inner = AF_NS.Core.FlipOptions; AF_NS.Core.FlipOptions = function(...) Calls2 = (Calls2 or 0) + 1; return Inner(...) end
  Calls2 = 0; AF_NS.UI.FlipRows(); First = Calls2; AF_NS.UI.FlipRows(); Second = Calls2 - First""")
ok(L('First') > 0 and L('Second') == 0, f"plan reused when nothing changed (worked out {L('First')} items, then {L('Second')})")
X('Gold = Gold - 100; Calls2 = 0; AF_NS.UI.FlipRows()')
ok(L('Calls2') > 0, 'gold changed: plan worked out again on the next open')
X('Calls2 = 0; AF_NS.Scan.Consume(2589, 1); AF_NS.UI.FlipRows()')
ok(L('Calls2') > 0, 'after a purchase: plan worked out again')
X('AF_NS.Core.FlipOptions, GetMoney = OldOpts, OldMoney3')
# After a purchase, the bought units leave your data and the sales starting point.
X("""AuctionForeverDB.fresh.items[2589] = { 20, 500, { { 20, 300 }, { 30, 200 } }, time() }
  AuctionForeverDB.base[2589] = { t = time() - 60, ladder = { { 20, 300 }, { 30, 200 } }, qty = 500 }
  AF_NS.Scan.Consume(2589, 350)""")
f = L('AuctionForeverDB.fresh.items[2589]')
ok(f[1] == 30 and f[2] == 150 and f[3][1][2] == 150, f'after buying 350: cheapest level gone, 150 left at 30c ({f[1]}, {f[2]})')
ok(L('AuctionForeverDB.base[2589].ladder[1][1]') == 30 and L('AuctionForeverDB.base[2589].ladder[1][2]') == 150, 'sales starting point adjusted too (your purchase is not counted as sales)')
undef = sorted(set(str(v) for v in L('UndefinedReads').values()))
ok(not undef, 'no reads of undefined globals from add-on code: ' + (', '.join(undef) or 'none'))
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
