"""Offline test of UI.lua with a fake WoW API (wowmock.lua). Proves it loads and its flows run; not that it looks right in game.
Run: venv python -I test_ui.py [path to a real AuctionForeverData.lua]"""
import os, re, sys
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
    if Src:find("Core.lua") or Src:find("Scan.lua") or Src:find("UI.lua") or Src:find("SelfTest.lua") or Src:find("Mail.lua") or Src:find("Trade.lua") or Src:find("Farm.lua") then UndefinedReads[#UndefinedReads + 1] = Src .. ": " .. tostring(k) end
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


def plain(t): return re.sub(r'\|T[^|]*\|t ?|\|c[0-9a-fA-F]{8}|\|r', '', str(t))
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
    # The missed-flips log runs once when the scan finishes; an error in it must not break the scan.
    X("""LogFlipCalls, RealLogFlips = 0, AF_NS.UI.LogFlips
      AF_NS.UI.LogFlips = function(Now) LogFlipCalls = LogFlipCalls + 1; LogFlipNow = Now; error("log failed") end
      function Pump() for _ = 1, 1000 do if not AF_NS.Scan.Busy() then break end
          for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end end
        Pump()
      AF_NS.UI.LogFlips = RealLogFlips""")
    ok(not L('AF_NS.Scan.Busy()'), 'full scan finished')
    ok(L('LogFlipCalls') == 1 and L('LogFlipNow') == L('time()'), f"finished full scan logs the flips on offer once ({L('LogFlipCalls')} calls), at the scan's time")
    ok('Sales measured' in str(L('AF_NS.Scan.LastResult')), 'an error in the flip log does not break the scan: ' + str(L('AF_NS.Scan.LastResult')))
    X('AF_NS.UI.LogFlips(time())')
    ok(L('type(AuctionForeverDB.flipLog) == "table"'), f"flip log written from the real planner ({L('AuctionForeverDB.flipLog and #AuctionForeverDB.flipLog')} flips on offer)")
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
      QLogCalls, RealLogFlipsQ = 0, AF_NS.UI.LogFlips
      AF_NS.UI.LogFlips = function() QLogCalls = QLogCalls + 1 end
      Click(AuctionForeverAHPanel.Quick)""")
    ok(L('BrowseQ ~= nil and BrowseQ.searchString == ""'), 'quick scan sends one browse-everything query')
    X('AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)')
    ok('waiting' in str(L('AuctionForeverAHPanel.Bar.Text:GetText()')), 'progress while waiting: ' + str(L('AuctionForeverAHPanel.Bar.Text:GetText()')))
    X('FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED"); AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)')
    ok('items read' in str(L('AuctionForeverAHPanel.Bar.Text:GetText()')) and L('AuctionForeverAHPanel.Bar:GetValue()') <= 0.8, 'progress while reading pages (first 80% of one bar): ' + str(L('AuctionForeverAHPanel.Bar.Text:GetText()')))
    X('FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_ADDED", BrowsePages[2]); BrowseLinen = { AuctionForeverDB.fresh.items[2589][1], AuctionForeverDB.fresh.items[2589][3][1][1] }; Browse14047 = AuctionForeverDB.fresh.items[14047]; PumpQuick()')
    ok(not L('AF_NS.Scan.Busy()'), 'quick scan done after the last page (and its busy-item lookups)')
    ok(L('QLogCalls') == 1, f"finished quick scan logs the flips on offer once, after its busy-item lookups ({L('QLogCalls')})")
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
    ok(L('QLogCalls') == 1, f"quick scan that stopped early: flips not logged ({L('QLogCalls')})")

    # Quick scan phase 2: exact lookups of the busiest items (top by sales per hour), right after the browse.
    busy = list(L('AF_NS.Scan.BusyIds(20)').values()) if L('AF_NS.Scan.BusyIds') else []
    ok(0 < len(busy) <= 20, f'busy list: {len(busy)} items')
    X("""C_AuctionHouse.HasFullBrowseResults = function() return Page >= 2 end
      C_AuctionHouse.RequestMoreBrowseResults = function() Page = Page + 1 end
      Looked = {}
      C_AuctionHouse.SendSearchQuery = function(k) Looked[#Looked + 1] = k.itemID; LastQuery = k.itemID end
      -- 12 near misses (one of them also a busy item): the 10 closest are looked up first
      RealNear = AF_NS.UI.NearMisses
      NearIds = { AF_NS.Scan.BusyIds(20)[3], 990011, 990012, 990013, 990014, 990015, 990016, 990017, 990018, 990019, 990020, 990021 }
      AF_NS.UI.NearMisses = function() local t = {} for i, id in ipairs(NearIds) do t[i] = { id = id, gap = i / 100 } end return t end
      time = function() return AuctionForeverData.time + 5600 end
      Click(AuctionForeverAHPanel.Quick); FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED"); FireEvent("AUCTION_HOUSE_BROWSE_RESULTS_ADDED", BrowsePages[2])""")
    ok(L('AF_NS.Scan.Busy()'), 'quick scan keeps going after the browse: checking busy items')
    X('AuctionForeverAHPanel._scripts.OnUpdate(AuctionForeverAHPanel, 0.2)')
    bt = str(L('AuctionForeverAHPanel.Bar.Text:GetText()'))
    ok('busy' in bt and L('AuctionForeverAHPanel.Bar:GetValue()') >= 0.8, 'one bar: phase 2 continues past 80%: ' + bt)
    X('PumpQuick()')
    looked = [L(f'Looked[{i}]') for i in range(1, int(L('#Looked')) + 1)]
    near10 = [L(f'NearIds[{i}]') for i in range(1, 11)]
    ok(not L('AF_NS.Scan.Busy()') and looked[:10] == near10 and len(looked) == len(busy) + 9 and len(set(looked)) == len(looked),
       f"looked up the 10 closest near misses first, then the busy items, none twice ({len(looked)} = {len(busy)} busy + 9 new)")
    X('AF_NS.UI.NearMisses = RealNear')
    lp = str(L('LastPrint'))
    ok('Quick scan: prices and stock for' in lp and 'busy items' in lp.lower(), 'one chat line for both phases: ' + lp)
    ok(L('QLogCalls') == 2, f"quick scan with busy-item lookups: logged once more, not once per lookup ({L('QLogCalls')})")
    X('AF_NS.UI.LogFlips = RealLogFlipsQ')

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
    X('''RealFlipNeed = AF_NS.Core.FlipNeed
      AF_NS.Core.FlipNeed = function(C, M, Sp) NeedSpeed = Sp; return RealFlipNeed(C, M, Sp) end
      Click(AuctionForeverBuyPanel.Buy); FireEvent("COMMODITY_PRICE_UPDATED", 26, 260)
      AF_NS.Core.FlipNeed = RealFlipNeed''')
    ok(L('type(NeedSpeed) == "table" and NeedSpeed.id == 2589'), 'live price check: the return it needs is judged from the item (slow sellers need more)')
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
    # Forever: an item search row's buyoutAmount is ONE item's price, also when the auction holds several.
    X("""RealNISR, RealISRI, RealHFISR = C_AuctionHouse.GetNumItemSearchResults, C_AuctionHouse.GetItemSearchResultInfo, C_AuctionHouse.HasFullItemSearchResults
      C_AuctionHouse.GetNumItemSearchResults = function() return 2 end
      C_AuctionHouse.HasFullItemSearchResults = function() return true end
      C_AuctionHouse.GetItemSearchResultInfo = function(K, j)
        if j == 1 then return { auctionID = 501, quantity = 12, buyoutAmount = 3496, timeLeftSeconds = 86400 } end
        return { auctionID = 502, quantity = 6, buyoutAmount = 3498, timeLeftSeconds = 86400 } end
      AF_NS.Scan.ReadItemsForTest(15732, { itemID = 15732 })
      C_AuctionHouse.GetNumItemSearchResults, C_AuctionHouse.GetItemSearchResultInfo, C_AuctionHouse.HasFullItemSearchResults = RealNISR, RealISRI, RealHFISR""")
    fr = L('AuctionForeverDB.fresh.items[15732]')
    lst = L('AF_NS.Scan.Listings[15732]')
    ok(fr is not None and fr[1] == 3496 and lst[1].buyout == 3496 * 12 and lst[1].qty == 12,
       f'item search: buyoutAmount is per item (12 at 34s96 = 34s96 each, not 2s91): low {fr and fr[1]}, listing total {lst and lst[1].buyout}')
    # An auction of several items: AF doesn't bid on it (PlaceBid's amount for those isn't known on Forever).
    X('Calls = {}; AF_NS.Scan.Listings[14047] = { { auctionID = 90, qty = 12, buyout = 12 * 300 } }; AF_NS.Trade.SelectBuy(2); Click(AuctionForeverBuyPanel.Buy)')
    ok(L('LastCall("PlaceBid") == nil') and 'Blizzard window' in str(L('AuctionForeverBuyPanel.Status:GetText()')),
       'multi-item auction: no bid, says to buy it in the Blizzard window: ' + str(L('AuctionForeverBuyPanel.Status:GetText()')))
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
      -- 14047's vendor price pinned low: with the real data file its shipped vendor price (4s) is above the 4s fresh
      -- listing set up for AF Buy, which (rightly) made it a vendor item and dropped it from the queue. Linen (2589)
      -- the same: on a day its market is only a few times its vendor price, Rec is Vendor.
      C_Item.GetItemInfo = function(id) local r = { RealGI(id) }; if id == 10620 then r[11] = 100000000 elseif id == 14047 then r[11] = 10 elseif id == 2589 then r[11] = 3 end return unpack(r, 1, 11) end
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
      -- (in the queue whatever the hourly data says about AH vs vendor: this is about the price)
      AF_NS.Core.Recommend = function() return "Auction" end
      MQ = AF_NS.Trade.BuildQueue()
      AF_NS.Core.Status, AF_NS.Core.SellPrice, AF_NS.Core.Recommend = RealSt, RealSP, RealRec""")
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
    # ---- Craft plans in AF Buy ------------------------------------------------------------------------------------
    # One recipe (Tailoring 50): 2 x mat 990102 + 1 x mat 990103 from the AH, 1 Coarse Thread (2320) from a vendor.
    X("""local function Copy(t, seen) if type(t) ~= "table" then return t end seen = seen or {} if seen[t] then return seen[t] end
        local c = {}; seen[t] = c; for k, v in pairs(t) do c[k] = Copy(v, seen) end return c end
      CraftSavedDB = Copy(AuctionForeverDB); CraftSavedData = AuctionForeverData; CraftSavedRecipes = AF_Recipes
      CraftSavedChar = Copy(AuctionForeverChar)
      AuctionForeverDB.fresh = nil -- (a newer full scan would say these test items have nothing listed)
      local F = { "low", "qty", "med", "hi", "med24", "medAll", "perHour", "medHour", "hoursSeen", "hoursWithSales", "sales",
        "sellThrough", "qtyDayAgo", "newHour", "lows", "lowHi24", "ladder" }
      AuctionForeverData = { v = 1, time = os.time() + 7, hours = 72, fields = F, names = {},
        items = {
          [990101] = { 1400, 30, 1400, 1500, 1400, 1400, 40, 40, 72, 70, 500, 1, 30, nil, nil, nil, { { 1400, 30 } } },
          [990102] = { 100, 120, 150, 200, 150, 150, 10, 10, 72, 70, 500, 1, 120, nil, nil, nil, { { 100, 10 }, { 200, 10 }, { 500, 100 } } },
          [990103] = { 300, 50, 300, 300, 300, 300, 10, 10, 72, 70, 500, 1, 50, nil, nil, nil, { { 300, 50 } } } },
        info = { [990101] = { 1, 1, 1 }, [990102] = { 1, 1, 1 }, [990103] = { 1, 1, 1 } } }
      AF_Recipes = { [990101] = { { 7101, 197, 50, 1, { 990102, 2, 990103, 1, 2320, 1 }, 0, 60, 80 } } }
      KnownSpells = {}
      IsPlayerSpell = function(s) return KnownSpells[s] == true end
      AF_NS.UI.SetShowAllRecipes(false)
      AF_NS.Scan.Version = AF_NS.Scan.Version + 1""")
    ok(L('#AF_NS.UI.CraftTargets()') == 0, "a recipe you don't know (no spell, no profession info): no craft plan")
    X('AF_NS.UI.SetShowAllRecipes(true)')
    ok(L('#AF_NS.UI.CraftTargets()') == 1 and L('AF_NS.UI.CraftTargets()[1].known') == False, 'Show all recipes: the plan shows, marked not known')
    X('AF_NS.UI.SetShowAllRecipes(false); KnownSpells[7101] = true; AF_NS.Scan.Version = AF_NS.Scan.Version + 1')
    ok(L('#AF_NS.UI.CraftTargets()') == 1 and L('AF_NS.UI.CraftTargets()[1].knownHow') == 'spell', 'the game says you know the recipe spell: the plan shows')
    # Without the spell answer: your profession rank against the recipe's required rank; a profession window's answer wins.
    X("""KnownSpells[7101] = nil; C_SkillInfo = { GetSkillLineInfoByID = function(id) if id == 197 then return { rank = SkillRank } end end }
      SkillRank = 75; AF_NS.Scan.Version = AF_NS.Scan.Version + 1""")
    ok(L('#AF_NS.UI.CraftTargets()') == 1 and L('AF_NS.UI.CraftTargets()[1].knownHow') == 'rank', 'Tailoring 75, recipe needs 50: probably known')
    X('SkillRank = 40; AF_NS.Scan.Version = AF_NS.Scan.Version + 1')
    ok(L('#AF_NS.UI.CraftTargets()') == 0, 'Tailoring 40, recipe needs 50: not known')
    X("""SkillRank = 75; C_TradeSkillUI = { GetRecipeInfo = function(s) if s == 7101 then return { learned = false } end end }
      FireEvent("TRADE_SKILL_SHOW")""")
    ok(L('AuctionForeverChar.recipes[7101]') == False and L('#AF_NS.UI.CraftTargets()') == 0, 'your profession window says not learned: no plan (beats the rank guess)')
    X('C_TradeSkillUI.GetRecipeInfo = function(s) if s == 7101 then return { learned = true } end end; FireEvent("TRADE_SKILL_LIST_UPDATE")')
    ok(L('#AF_NS.UI.CraftTargets()') == 1 and L('AF_NS.UI.CraftTargets()[1].knownHow') == 'window', 'learned in the window: the plan shows')
    # The row in AF Buy (no flips right now): mats for N, the resale, the profit, "craft: Tailoring 50", the tier.
    X("""FlipTargets = {}; Click(AuctionForeverBuyTab); AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)
      CE = AF_NS.Trade.SelectedBuy(); CF = CE and CE.flip""")
    cells = [str(L(f'AuctionForeverBuyPanel.Rows[1].Cells[{c}]:GetText()')) for c in range(1, 8)]
    n = L('CF and CF.crafts')
    ok(L('CE ~= nil and CE.craft ~= nil') and n and n > 0 and cells[3].startswith('mats for ' + str(n) + ': ') and 'craft: Tailoring 50' in cells[6]
       and cells[4].startswith('AH ') and cells[4].endswith(' each') and '(c)' in cells[0], f'craft row: {cells}')
    tier = L('(AF_NS.Trade.Tier(CF))')
    ret = L('CF.profit / CF.cost')
    ok(tier in cells[1] and ret > 0 and ('Tier ' + tier) in str(L('AuctionForeverBuyPanel.Detail:GetText()')), f'tier by expected return (profit / mats cost): {tier}, {ret:.0%}')
    ok(L('CF.crafts <= 50 and CF.mats[1].qty == 2 * CF.crafts and CF.mats[2].qty == CF.crafts and CF.vendorGoods[1].qty == CF.crafts'),
       f"N within the mats listed (50 of mat 990103): {n}; each mat bought for N crafts")
    det = str(L('AuctionForeverBuyPanel.Detail:GetText()')).split('\n')
    ok(len(det) == 2 and det[0] == '|cffffffffItem 990101|r x' + str(n) + '   Tailoring 50 (known: seen in your Tailoring window)'
       and 'based on 500 sales in 70 h' in det[1], f'panel header: product x N, profession, how known; then the evidence: {det}')
    def money(x): return plain(L(f'AF_NS.Core.MoneyColor({x})'))
    def pane():
        out = []
        for i in range(1, 9):
            if not L(f'AuctionForeverBuyPanel.Lines[{i}]:IsShown()'):
                continue
            W = f'AuctionForeverBuyPanel.Lines[{i}]'
            out.append([plain(L(f'{W}.Cells[{c}]:GetText()')) for c in range(1, 7)]
                       + [bool(L(f'{W}.Btn:IsShown()')), bool(L(f'{W}.Btn:IsEnabled()')), str(L(f'{W}.Btn:GetText()')), plain(L(f'{W}.Note:GetText()'))])
        return out
    pl = pane()
    want = [[str(2 * n), 'Item 990102', 'AH', 'up to ' + money(L('CF.mats[1].upTo')), '120', money(L('CF.mats[1].cost')), True, True, 'Buy', ''],
            [str(n), 'Item 990103', 'AH', 'up to ' + money(L('CF.mats[2].upTo')), '50', money(L('CF.mats[2].cost')), True, True, 'Buy', ''],
            [str(n), 'Item 2320', 'Vendor', money(L('CF.list[3].each')), '-', money(L('CF.vendorCost')), False, True, 'Buy', 'buy from a vendor']]
    ok([r[:6] + r[8:] for r in pl if r[6]] == [r[:6] + r[8:] for r in want if r[6]] and [r[:6] + r[9:] for r in pl if not r[6]] == [r[:6] + r[9:] for r in want if not r[6]]
       and [r[6] for r in pl] == [True, True, False] and pl[0][7] and pl[1][7],
       f'panel lines: need, reagent, source, pay up to, listed now, cost, a Buy button on AH lines: {pl}')
    src = [str(L(f'AuctionForeverBuyPanel.Lines[{i}].Cells[3]:GetText()')) for i in (1, 3)]
    ok('|TInterface\\Icons\\INV_Misc_Coin_02:' in src[0] and '|TInterface\\Icons\\Inv_misc_bag_08:' in src[1] and '|c' not in src[0] + src[1]
       and all(ord(ch) < 128 for ch in src[0] + src[1]), f'source column: an icon and the plain word for AH and Vendor: {src}')
    ok([str(L(f'AuctionForeverBuyPanel.PaneHead[{c}]:GetText()')) for c in range(1, 7)] == ['Need', 'Reagent', 'Source', 'Pay up to', 'Listed now', 'Cost'],
       'panel column headers (Source, not Where)')
    sm = [plain(x) for x in str(L('AuctionForeverBuyPanel.Summary:GetText()')).split('\n')]
    after = money(L('math.floor(CF.resell * 0.95) * CF.units'))
    tierw = L('(AF_NS.Trade.Tier(CF))')
    ok(len(sm) == 3 and sm[0] == f'Craft {n}, then Auction at {money(L("CF.resell"))} each (after cut {after})'
       and sm[1].startswith(f'Mats {money(L("CF.cost"))}   Profit +') and f'({tierw}, ' in sm[1] and sm[1].endswith('% return)')
       and sm[2] == 'Leaves you ' + money(L('GetMoney() - CF.cost')), f'summary says what to do, the money, what it leaves you: {sm}')
    ok(L('GetMoney() - CF.cost') >= 5000 and L('CF.cost') == L('CF.mats[1].cost + CF.mats[2].cost + CF.vendorCost'),
       f'mats cost (AH and vendor) leaves at least 50s: {L("GetMoney() - CF.cost")}')
    ok(not L('AuctionForeverBuyPanel.Buy:IsShown()') and not L('AuctionForeverBuyPanel.Buy:IsEnabled()'), 'a craft row: no single Buy button (each mat has its own)')
    # The table shrinks to make room for the panel (never under 5 rows) and the selected row stays in view.
    vis = L('AF_NS.Trade.BuyVisible()')
    shown = sum(1 for r in range(1, 15) if L(f'AuctionForeverBuyPanel.Rows[{r}]:IsShown()'))
    pt = L('AuctionForeverBuyPanel.Pane._points[#AuctionForeverBuyPanel.Pane._points][5]')
    ok(5 <= vis < 14 and vis == L('AF_NS.Trade.PaneModel(CE).rows') and pt == -100 - vis * 22 - 4
       and L('AF_NS.Trade.PaneModel(CE).height') <= 316 - 4 - vis * 22, f'table shrinks to {vis} rows, panel under it at {pt} ({shown} rows shown)')
    # Each AH mat has its own Buy: exactly its quantity, its own price check and Confirm.
    X('Calls = {}; Click(AuctionForeverBuyPanel.Lines[1].Btn)')
    c = L('LastCall("StartCommoditiesPurchase")')
    ok(c is not None and c[2] == 990102 and c[3] == L('CF.mats[1].qty'), f'line 1 Buy: that mat, the planned quantity ({c and c[2]} x {c and c[3]})')
    X('FireEvent("COMMODITY_PRICE_UPDATED", CF.mats[1].upTo, CF.mats[1].cost)')
    ok(str(L('AuctionForeverBuyPanel.Lines[1].Btn:GetText()')) == 'Confirm' and not L('AuctionForeverBuyPanel.Lines[2].Btn:IsEnabled()'),
       'price at or under its pay up to: Confirm on that line, the other lines wait')
    X('Click(AuctionForeverBuyPanel.Lines[1].Btn); FireEvent("COMMODITY_PURCHASE_SUCCEEDED")')
    pl = pane()
    ok(L('LastCall("ConfirmCommoditiesPurchase")[2]') == 990102 and L('LastCall("ConfirmCommoditiesPurchase")[3]') == L('CF.mats[1].qty')
       and pl[0][9] == 'bought' and not pl[0][7] and pl[1][7] and pl[1][8] == 'Buy' and L('AF_NS.Trade.CraftRun().bought[1]') == L('CF.mats[1].qty'),
       f'bought: the line says "bought", its button is off, the next line can buy: {pl}')
    ok('|cff1eff00bought|r' in str(L('AuctionForeverBuyPanel.Lines[1].Note:GetText()')), 'bought is green')
    # Over its pay up to: cancelled, nothing bought, the line can try again.
    X('Calls = {}; Click(AuctionForeverBuyPanel.Lines[2].Btn); FireEvent("COMMODITY_PRICE_UPDATED", CF.mats[2].upTo + 1, (CF.mats[2].upTo + 1) * CF.mats[2].qty)')
    ok(L('LastCall("CancelCommoditiesPurchase") ~= nil') and L('LastCall("ConfirmCommoditiesPurchase") == nil') and L('AF_NS.Trade.CraftRun().bought[2] == nil')
       and 'went up' in str(L('AuctionForeverBuyPanel.Status:GetText()')),
       'live price over its pay up to: cancelled, not bought: ' + str(L('AuctionForeverBuyPanel.Status:GetText()')))
    # (the re-check after it reads the test items as sold out: back to the test data; the run keeps its plan)
    X('AuctionForeverDB.fresh = nil; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)')
    ok(L('AuctionForeverBuyPanel.Lines[2].Btn:IsEnabled()') and str(L('AuctionForeverBuyPanel.Lines[2].Btn:GetText()')) == 'Buy', 'the line can try again')
    X("""Click(AuctionForeverBuyPanel.Lines[2].Btn); FireEvent("COMMODITY_PRICE_UPDATED", CF.mats[2].upTo, CF.mats[2].cost)
      Click(AuctionForeverBuyPanel.Lines[2].Btn); FireEvent("COMMODITY_PURCHASE_SUCCEEDED")""")
    total = L('CF.mats[1].cost + CF.mats[2].cost + CF.vendorCost')
    ok(L('AF_NS.Trade.CraftRun() == nil') and L('#AuctionForeverDB.crafts') >= 1 and L('AuctionForeverDB.crafts[#AuctionForeverDB.crafts][2]') == 990101
       and L('AuctionForeverDB.crafts[#AuctionForeverDB.crafts][4]') == total, 'every AH mat bought: the craft is recorded (product, crafts, total cost)')
    held = L('(AF_NS.Core.Holding(AuctionForeverDB, 990101))')
    paid = L('select(2, AF_NS.Core.Holding(AuctionForeverDB, 990101))')
    ok(held == L('CF.units') and paid == -(-total // L('CF.units')), f'the product\'s cost basis is the mats (AF Sell\'s "You paid"): {held} at {paid} each')
    ok(L('(AF_NS.Core.Holding(AuctionForeverDB, 990102))') == 0, "mats used for the craft aren't left as purchases of their own")
    ok('All AH mats bought' in str(L('AuctionForeverBuyPanel.Status:GetText()')), 'all AH mats bought: says so')
    X('AuctionForeverDB.fresh = nil; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)')
    pl = pane()
    ok([r[9] for r in pl if r[6]] == ['bought', 'bought'] and not any(r[7] for r in pl if r[6]),
       f'all bought: the panel keeps the plan, every AH line "bought": {pl}')
    X('Calls = {}; Click(AuctionForeverBuyPanel.Lines[1].Btn)')
    ok(L('LastCall("StartCommoditiesPurchase") == nil'), 'a finished craft: no buying its mats again until you leave the auction house')
    # Bought part of a mat: "bought X of Y", and its Buy buys the rest. Leaving the auction house records what's bought.
    X("""FireEvent("AUCTION_HOUSE_CLOSED"); AuctionForeverDB.fresh = nil; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)
      CF = AF_NS.Trade.SelectedBuy().flip
      Click(AuctionForeverBuyPanel.Lines[1].Btn); FireEvent("COMMODITY_PRICE_UPDATED", CF.mats[1].upTo, CF.mats[1].cost)
      Click(AuctionForeverBuyPanel.Lines[1].Btn); FireEvent("COMMODITY_PURCHASE_SUCCEEDED")
      AF_NS.Trade.CraftRun().bought[2] = 5; AF_NS.Trade.DrawBuy(); Calls = {}""")
    pl = pane()
    X('Click(AuctionForeverBuyPanel.Lines[2].Btn)')
    c = L('LastCall("StartCommoditiesPurchase")')
    ok(pl[1][9] == 'bought 5 of ' + str(L('CF.mats[2].qty')) and pl[1][8] == 'Buy rest' and c and c[3] == L('CF.mats[2].qty') - 5,
       f'part bought: "bought 5 of N", Buy buys the rest ({pl[1]}, {c and c[3]})')
    X('FireEvent("AUCTION_HOUSE_CLOSED")')
    ok(L('AF_NS.Trade.CraftRun() == nil') and L('(AF_NS.Core.Holding(AuctionForeverDB, 990102))') == L('CF.mats[1].qty'),
       'left part way: the mats bought are recorded as yours (for AF Sell)')
    X('AuctionForeverDB.fresh = nil; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)')
    ok('based on 500 sales in 70 h' in str(L('AuctionForeverBuyPanel.Detail:GetText()')).split('\n')[1], 'evidence line says what the resale is based on: ' + str(L('AuctionForeverBuyPanel.Detail:GetText()')).split('\n')[1])
    # Bank: units in the bank count as held (after the bags), one line per source; Owned / Bank get a green check mark.
    X("""SaveContB, SaveGIC = C_Container, C_Item.GetItemCount
      C_Container = { GetContainerNumSlots = function(b) return b == 0 and 1 or 0 end,
        GetContainerItemInfo = function(b, s) if b == 0 and s == 1 then return { itemID = 990102, stackCount = 4 } end end }
      C_Item.GetItemCount = function(id, bank) local Bags = id == 990102 and 4 or 0 local Bank = (id == 990103 and 3 or 0) return Bags + (bank and Bank or 0) end
      AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1); KF = AF_NS.Trade.SelectedBuy().flip""")
    m = L('KF.crafts')
    kl = [(L(f'KF.list[{i}].source'), L(f'KF.list[{i}].id'), L(f'KF.list[{i}].qty')) for i in range(1, (L('#KF.list') or 0) + 1)]
    ok(kl == [('AH', 990102, 2 * m - 4), ('AH', 990103, m - 3), ('Vendor', 2320, m), ('Owned', 990102, 4), ('Bank', 990103, 3)]
       and L('KF.mats[2].qty') == m - 3, f'bank units held too (after the bags), grouped AH, Vendor, Owned, Bank: {kl}')
    pl = pane()
    raw = [str(L(f'AuctionForeverBuyPanel.Lines[{i}].Cells[3]:GetText()')) for i in (4, 5)]
    ok([r[2] for r in pl] == ['AH', 'AH', 'Vendor', 'Owned', 'Bank'] and pl[3][9] == 'you have 4' and pl[4][9] == 'you have 3' and pl[3][3] == '-' and pl[3][5] == '-'
       and all('UI-CheckBox-Check' in r and ':30:255:0|t' in r for r in raw) and raw[0].endswith('|cff1eff00Owned|r') and raw[1].endswith('|cff1eff00Bank|r'),
       f'panel: Owned / Bank lines with a green check mark, "you have N": {pl} {raw}')
    ok(plain(L('AF_NS.UI.MatsLine(KF.list, 9)')).endswith(', 4 Item 990102 (Owned), 3 Item 990103 (Bank)'), 'compact Mats line: (Owned) / (Bank)')
    X('C_Container, C_Item.GetItemCount = SaveContB, SaveGIC; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)')
    # More source lines than fit: Owned/Bank lines collapse into one line first, then "+N more".
    X("""SavePL = AF_NS.Trade.PaneLines
      local function L(k, id) return { kind = k, source = k, id = id, qty = 1, cost = 1, upTo = 1, bought = 0 } end
      AF_NS.Trade.PaneLines = function() return { L("AH", 1), L("AH", 2), L("AH", 3), L("AH", 4), L("Owned", 5), L("Bank", 6), L("Bank", 7) } end
      PM1 = AF_NS.Trade.PaneModel(AF_NS.Trade.SelectedBuy())
      AF_NS.Trade.PaneLines = function() local t = {} for i = 1, 8 do t[i] = L("AH", i) end t[9] = L("Owned", 9) return t end
      PM2 = AF_NS.Trade.PaneModel(AF_NS.Trade.SelectedBuy())
      AF_NS.Trade.PaneLines = SavePL""")
    k1 = [L(f'PM1.lines[{i}].kind') for i in range(1, L('#PM1.lines') + 1)]
    k2 = [L(f'PM2.lines[{i}].kind') for i in range(1, L('#PM2.lines') + 1)]
    ok(L('PM1.fit') == 5 and k1 == ['AH'] * 4 + ['held'] and L('#PM1.lines[5].parts') == 3 and L('PM1.rows') == 5
       and k2 == ['AH'] * 4 + ['more'] and L('PM2.lines[5].n') == 5 and L('PM2.rows') == 5,
       f'overflow: Owned/Bank collapse first ({k1}), then +N more ({k2}, {L("PM2.lines[5].n")})')
    # Mixed flips and craft rows: every column sorts them (high first, low first, back to the plan), craft rows by
    # their own numbers (none is nil, so they don't just fall to the end).
    X("""MixF = {
        { id = 2589, plan = true, info = { sellThrough = 0.9 }, flip = { buyQty = 10, buyUpTo = 30, cost = 250, resell = 200, hours = 2, profit = 320 } },
        { id = 14047, info = { sellThrough = 0.3 }, need = 500000, flip = { buyQty = 1, buyUpTo = 400, cost = 380, resell = 99999, hours = 8, profit = 570 } },
        { id = 4306, info = { sellThrough = 0.6 }, flip = { buyQty = 2, buyUpTo = 50, cost = 100, resell = 90, hours = 8, profit = 40 } } }
      MixF[2].now = {}; MixF[3].now = { [MixF[3].flip] = true }
      FlipTargets = MixF; AF_NS.Trade.SetBuyFilter("all"); AF_NS.Trade.SetBuySort("plan"); AF_NS.Trade.RefreshBuy()""")
    nrows = L('#AF_NS.Trade.Rows()')
    def keys(k): return [L(f'AF_NS.Trade.SortKey("{k}", AF_NS.Trade.Rows()[{i}])') for i in range(1, nrows + 1)]
    crafted = lambda: [bool(L(f'AF_NS.Trade.Rows()[{i}].craft ~= nil')) for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
    ok(nrows == 4 and sum(crafted()) == 1, f'mixed list: 3 flips and the craft plan ({nrows})')
    names = ['name', 'tier', 'rate', 'cost', 'resell', 'profit', 'status']
    for c, k in enumerate(names, 1):
        X(f'Click(AuctionForeverBuyPanel.Headers[{c}])')
        kd, hd = keys(k), str(L(f'AuctionForeverBuyPanel.Headers[{c}].Label:GetText()'))
        X(f'Click(AuctionForeverBuyPanel.Headers[{c}])')
        ka, ha = keys(k), str(L(f'AuctionForeverBuyPanel.Headers[{c}].Label:GetText()'))
        ci = crafted().index(True)
        X(f'Click(AuctionForeverBuyPanel.Headers[{c}])')
        back = L('(AF_NS.Trade.BuySort())')
        ok(None not in kd and kd == sorted(kd, reverse=True) and ka == sorted(ka) and hd.endswith(' v') and ha.endswith(' ^') and back == 'plan'
           and None not in ka,
           f'mixed rows, column {c} ({k}): high first {kd}, low first {ka}, then the plan order')
    X('Click(AuctionForeverBuyPanel.Headers[7]); Click(AuctionForeverBuyPanel.Headers[7])')
    st = [L(f'AF_NS.Trade.Rows()[{i}].id') for i in range(1, nrows + 1)]
    ok(st == [2589, 4306, 14047, 990101], f'Status low first: in the plan, fits now, needs gold, craft plans ({st})')
    X('Click(AuctionForeverBuyPanel.Headers[7]); Click(AuctionForeverBuyPanel.Headers[5])')
    rs = [L(f'AF_NS.Trade.Rows()[{i}].id') for i in range(1, nrows + 1)]
    ok(rs[0] == 14047 and rs.index(990101) < 3, f'Resell high first: the craft row sorts by its sale price, not last ({rs})')
    X('Click(AuctionForeverBuyPanel.Headers[5]); Click(AuctionForeverBuyPanel.Headers[5])')
    # Filter bar: All, Flips, one button per profession with rows now; remembered; "Showing N of M".
    fb = [(str(L(f'AuctionForeverBuyPanel.Filters[{i}]:GetText()')), bool(L(f'AuctionForeverBuyPanel.Filters[{i}]:IsShown()'))) for i in range(1, 5)]
    ok([t for t, sh in fb if sh] == ['All', 'Flips', 'Tailoring'] and not L('AuctionForeverBuyPanel.Filters[1]:IsEnabled()')
       and str(L('AuctionForeverBuyPanel.FilterNote:GetText()')) == 'Showing 4 of 4', f'filter bar: {fb}')
    X('Click(AuctionForeverBuyPanel.Filters[2])')
    ok(L('#AF_NS.Trade.Rows()') == 3 and not any(crafted()[:3]) and L('AuctionForeverDB.buyFilter') == 'flips' and str(L('AuctionForeverBuyPanel.FilterNote:GetText()')) == 'Showing 3 of 4'
       and not L('AuctionForeverBuyPanel.Filters[2]:IsEnabled()'), 'Flips: only flips, remembered')
    X('Click(AuctionForeverBuyPanel.Filters[3])')
    ok(L('#AF_NS.Trade.Rows()') == 1 and L('AF_NS.Trade.Rows()[1].craft ~= nil') and L('AuctionForeverDB.buyFilter') == 'Tailoring'
       and str(L('AuctionForeverBuyPanel.FilterNote:GetText()')) == 'Showing 1 of 4', 'a profession: only its craft plans')
    X('FlipTargets = {}; AF_NS.Trade.RefreshBuy()')
    ok(L('#AF_NS.Trade.Rows()') == 1 and L('AuctionForeverDB.buyFilter') == 'Tailoring', 'remembered filter still applies after a refresh')
    X('AF_Recipes[990101][1][2] = 171; AF_NS.UI.RecipeVersion = (AF_NS.UI.RecipeVersion or 0) + 1; FlipTargets = MixF; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy()')
    ok(L('#AF_NS.Trade.Rows()') == 3 + L('#AF_NS.UI.CraftTargets()') and str(L('AuctionForeverBuyPanel.FilterNote:GetText()')).startswith('Showing ' + str(L('#AF_NS.Trade.Rows()')))
       and L('AuctionForeverDB.buyFilter') == 'Tailoring', 'no Tailoring rows now: shows All (the choice is kept for later)')
    X('AF_Recipes[990101][1][2] = 197; AF_NS.UI.RecipeVersion = AF_NS.UI.RecipeVersion + 1; AF_NS.Trade.SetBuyFilter("all"); FlipTargets = {}; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)')
    ok(L('#AF_NS.Trade.Rows()') == 1, 'filter back to All')
    # A cooldown recipe on cooldown past the 8 h window: not listed; with Show all, listed as "on cooldown", Buy greyed.
    X("""AuctionForeverDB.fresh = nil; AF_Recipes[990101][1][9] = 86400; AF_Recipes[990101][1][10] = 0
      C_Spell = { GetSpellCooldown = function(s) if s == 7101 then return { startTime = GetTime(), duration = 82800 } end end }
      AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy()""")
    ok(L('#AF_NS.Trade.BuyRows()') == 0, 'transmute-style cooldown with 23 h left: not listed')
    X('AF_NS.UI.SetShowAllRecipes(true); AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)')
    ok(L('#AF_NS.Trade.BuyRows()') == 1 and 'on cooldown 23h' in str(L('AuctionForeverBuyPanel.Rows[1].Cells[7]:GetText()'))
       and not L('AuctionForeverBuyPanel.Buy:IsEnabled()') and L('AF_NS.Trade.SelectedBuy().flip.crafts') == 1,
       'Show all: listed as on cooldown (1 craft), Buy greyed: ' + str(L('AuctionForeverBuyPanel.Rows[1].Cells[7]:GetText()')))
    X("""C_Spell.GetSpellCooldown = function() return { startTime = 0, duration = 0 } end; AF_NS.UI.SetShowAllRecipes(false)
      AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)""")
    ok(L('#AF_NS.Trade.BuyRows()') == 1 and L('AF_NS.Trade.SelectedBuy().flip.crafts') == 1 and 'cooldown 24h' in str(L('AuctionForeverBuyPanel.Detail:GetText()')),
       'ready: listed, one craft (a 24 h cooldown allows one in the window)')
    X('C_Spell = nil; AF_Recipes[990101][1][9] = nil; AF_Recipes[990101][1][10] = nil')
    # A flooded product: no plan; with Show all, greyed as "flooded", no Buy.
    X("""AuctionForeverDB.fresh = nil; CraftRealStatus = AF_NS.Core.Status
      AF_NS.Core.Status = function(I) if I and I.id == 990101 then return "flooded" end return CraftRealStatus(I) end
      CraftRealNeed = AF_NS.Core.FlipNeed; AF_NS.Core.FlipNeed = function() return 0 end -- (only the status rule decides here)
      AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy()""")
    ok(L('#AF_NS.Trade.BuyRows()') == 0, 'flooded product: no craft plan')
    X('AF_NS.UI.SetShowAllRecipes(true); AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(1)')
    ok(L('#AF_NS.Trade.BuyRows()') == 1 and 'flooded' in str(L('AuctionForeverBuyPanel.Rows[1].Cells[7]:GetText()')) and not L('AuctionForeverBuyPanel.Buy:IsEnabled()')
       and 'Flooded' in str(L('AuctionForeverBuyPanel.Detail:GetText()')), 'Show all: shown greyed as flooded, Buy greyed: ' + str(L('AuctionForeverBuyPanel.Rows[1].Cells[7]:GetText()')))
    X('AF_NS.Core.Status = CraftRealStatus; AF_NS.Core.FlipNeed = CraftRealNeed; AF_NS.UI.SetShowAllRecipes(false); AF_NS.Scan.Version = AF_NS.Scan.Version + 1')
    # Show all recipes box on AF Buy
    X('AuctionForeverDB.fresh = nil; AF_NS.UI.SetShowAllRecipes(false); AuctionForeverChar.recipes[7101] = false; AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy()')
    ok(L('#AF_NS.Trade.BuyRows()') == 0, 'unknown recipe, box off: not listed')
    X('Click(AuctionForeverBuyPanel.AllRecipes)')
    ok(L('AF_NS.UI.ShowAllRecipes()') and L('#AF_NS.Trade.BuyRows()') == 1 and "don't know this recipe" in str(L('AuctionForeverBuyPanel.Detail:GetText()'))
       and 'Show all recipes' in str(L('AuctionForeverBuyPanel.AllRecipesLabel:GetText()')), 'ticking Show all recipes lists it, saying you don\'t know it')
    X('Click(AuctionForeverBuyPanel.AllRecipes)')
    ok(not L('AF_NS.UI.ShowAllRecipes()') and L('#AF_NS.Trade.BuyRows()') == 0, 'unticking hides it again')
    X("""for k in pairs(AuctionForeverDB) do AuctionForeverDB[k] = nil end; for k, v in pairs(CraftSavedDB) do AuctionForeverDB[k] = v end
      for k in pairs(AuctionForeverChar) do AuctionForeverChar[k] = nil end; for k, v in pairs(CraftSavedChar) do AuctionForeverChar[k] = v end
      AuctionForeverData = CraftSavedData; AF_Recipes = CraftSavedRecipes; IsPlayerSpell = nil; C_SkillInfo = nil; C_TradeSkillUI = nil; C_Spell = nil
      AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.Trade.RefreshBuy()""")

    # ---- A quick scan feeds AF Buy / AF Sell as it reads items (at most every 2 s); a full scan only at the end ----
    X("""local function Copy(t, seen) if type(t) ~= "table" then return t end seen = seen or {} if seen[t] then return seen[t] end
        local c = {}; seen[t] = c; for k, v in pairs(t) do c[k] = Copy(v, seen) end return c end
      LiveSavedDB = Copy(AuctionForeverDB) -- (the scans below change your data; later tests expect it as it was)
      Click(AuctionForeverBuyTab)
      LiveRows = {
        { id = 2589, info = AF_NS.Core.Info(2589), flip = { buyQty = 10, buyUpTo = 30, cost = 250, resell = 200, hours = 2, durationIndex = 1, profit = 320 } },
        { id = 14047, info = AF_NS.Core.Info(14047), flip = { buyQty = 1, buyUpTo = 400, cost = 380, resell = 1000, hours = 8, durationIndex = 2, profit = 570 } } }
      FlipTargets = LiveRows
      LiveCalls = 0; LiveInner = AF_NS.UI.FlipTargets
      AF_NS.UI.FlipTargets = function() LiveCalls = LiveCalls + 1 return LiveInner() end
      AF_NS.Trade.RefreshBuy(); AF_NS.Trade.SelectBuy(2); AdvanceTime(5)
      AF_NS.Scan.Lookup = RealLookup; LastQuery = nil
      LiveSend = C_AuctionHouse.SendSearchQuery
      C_AuctionHouse.SendSearchQuery = function(k) LastQuery = k.itemID end
      function LiveStep() local id = LastQuery; LastQuery = nil; if id then FireEvent("COMMODITY_SEARCH_RESULTS_UPDATED", id) end end
      LiveCalls = 0
      -- the next list has a new target at the top
      FlipTargets = { { id = 2592, info = AF_NS.Core.Info(2589), flip = { buyQty = 5, buyUpTo = 30, cost = 150, resell = 200, hours = 2, durationIndex = 1, profit = 600 } }, LiveRows[1], LiveRows[2] }
      AF_NS.Scan.Lookup({ 2589, 2589, 2589, 2589 }, true)
      LiveStep()""")
    rows = [L(f'AuctionForeverBuyPanel.Rows[{i}].Cells[1]:GetText()') for i in range(1, 4)]
    ok(L('AF_NS.Scan.Busy()') and L('LiveCalls') == 1 and L('#AF_NS.Trade.BuyRows()') == 3,
       f"quick scan: AF Buy rebuilt after the first item is read, before the scan ends ({L('LiveCalls')} rebuilds, {L('#AF_NS.Trade.BuyRows()')} rows)")
    ok(L('AF_NS.Trade.SelectedBuy().id') == 14047, f"the selected item stays selected ({L('AF_NS.Trade.SelectedBuy().id')})")
    X('LiveStep()')
    ok(L('AF_NS.Scan.Busy()') and L('LiveCalls') == 1, f"throttled: the next item 0 s later doesn't rebuild again ({L('LiveCalls')})")
    X('LiveGT = GetTime; GetTime = function() return LiveGT() + 2.5 end; LiveStep(); GetTime = LiveGT')
    ok(L('AF_NS.Scan.Busy()') and L('LiveCalls') == 2, f"2.5 s later: rebuilt again ({L('LiveCalls')})")
    X('for _ = 1, 10 do LiveStep() end; Timers = {}')
    ok(not L('AF_NS.Scan.Busy()') and L('LiveCalls') == 3, f"and once more when the scan finishes ({L('LiveCalls')})")
    # never under a purchase being priced or confirmed: waits, then applies
    X("""for i, E in ipairs(AF_NS.Trade.BuyRows()) do if E.id == 2589 then AF_NS.Trade.SelectBuy(i) end end
      Click(AuctionForeverBuyPanel.Buy); LiveCalls = 0; AF_NS.UI.ScanLive()""")
    ok(L('LastCall("StartCommoditiesPurchase") ~= nil') and L('LiveCalls') == 0, f"purchase being priced: no rebuild ({L('LiveCalls')})")
    X('LiveSel = AF_NS.Trade.SelectedBuy().id; FireEvent("COMMODITY_PRICE_UPDATED", 35, 350); LiveAfter = LiveCalls; AdvanceTime(1.1)')
    ok(L('LiveCalls') == L('LiveAfter') + 1 and L('AF_NS.Trade.SelectedBuy().id') == L('LiveSel'),
       f"once the purchase is done (here: cancelled, the price rose) the waiting update is applied ({L('LiveAfter')} -> {L('LiveCalls')})")
    # a full scan: no partial updates, progress shown in AF Buy's status line, the list rebuilt at the end
    X("""for _ = 1, 10 do LiveStep() end; Timers = {} -- (the re-check after the cancelled purchase)
      AuctionForeverDB.lastFull = nil; AuctionForeverDB.fresh.time = nil; LiveCalls = 0
      AF_NS.Scan.Start(); FireEvent("REPLICATE_ITEM_LIST_UPDATE")
      for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u and f ~= AuctionForeverBuyPanel then u(f, 0.016) end end
      AF_NS.UI.ScanProgress()""")
    ok(L('AF_NS.Scan.Busy()') and L('LiveCalls') == 0, f"full scan reading: AF Buy not rebuilt from a part of it ({L('LiveCalls')})")
    ok('reading' in str(L('AuctionForeverBuyPanel.Status:GetText()')), 'full scan progress in the AF Buy status: ' + str(L('AuctionForeverBuyPanel.Status:GetText()')))
    X('Pump()')
    ok(not L('AF_NS.Scan.Busy()') and L('LiveCalls') == 1 and 'reading' not in str(L('AuctionForeverBuyPanel.Status:GetText()')),
       f"full scan done: rebuilt once, progress text cleared ({L('LiveCalls')})")
    # AF Sell: rebuilt in place (selection and your typed price kept); never while a post waits for confirmation
    X("""Click(AuctionForeverSellTab); AF_NS.Trade.SelectSellId(2589); Timers = {}
      SellBuilds = 0; LiveBQ = AF_NS.Trade.BuildQueue
      AF_NS.Trade.BuildQueue = function() SellBuilds = SellBuilds + 1 return LiveBQ() end
      AuctionForeverSellPanel.Qty:SetText("3"); AF_NS.UI.ScanLive()""")
    ok(L('SellBuilds') == 1 and L('AF_NS.Trade.SelectedSell().id') == 2589 and L('AuctionForeverSellPanel.Qty:GetText()') == '3',
       f"AF Sell rebuilt with the new data, same item selected, your quantity kept ({L('SellBuilds')}, {L('AuctionForeverSellPanel.Qty:GetText()')})")
    X("""CallReturns = { PostCommodity = true }; AF_NS.Trade.SelectSellId(2589); Click(AuctionForeverSellPanel.Post); CallReturns = nil
      SellBuilds = 0; AF_NS.UI.ScanLive()""")
    ok('Confirm' in str(L('AuctionForeverSellPanel.Post:GetText()')) and L('SellBuilds') == 0, f"post waiting for confirmation: AF Sell not rebuilt ({L('SellBuilds')})")
    X('Click(AuctionForeverSellPanel.Post); AdvanceTime(1.1)')
    ok(L('SellBuilds') == 1, f"after the post: the waiting update is applied ({L('SellBuilds')})")
    X('AF_NS.Trade.BuildQueue = LiveBQ; for _ = 1, 10 do LiveStep() end; Timers = {}')
    ok(not L('AF_NS.Scan.Busy()'), 'no scan left running')
    X('for k in pairs(AuctionForeverDB) do AuctionForeverDB[k] = nil end; for k, v in pairs(LiveSavedDB) do AuctionForeverDB[k] = v end; AF_NS.Scan.Version = AF_NS.Scan.Version + 1')
    X('AF_NS.UI.FlipTargets = LiveInner; C_AuctionHouse.SendSearchQuery = LiveSend; AF_NS.Scan.Lookup = function(Ids, Silent, Done) LookupSpy[#LookupSpy + 1] = { ids = Ids, silent = Silent }; if Done then Done() end return true end')
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
X("time = function() return 1800000000 + 4 * 86400 end")
ok(L('AF_NS.Core.Info(2589).mySold') in (None, 0), 'own sales older than 3 days drop out of the Info count')

# Item tooltip: just Vendor, AH, Profit (AH after the 5% cut - vendor, green + / red -) and Source; no Shift details.
mc = L('AF_NS.Core.MoneyColor(10203)')
ok('|cffffd7001g|r' in mc and '|cffc7c7cf02s|r' in mc and '|cffeda55f03c|r' in mc, 'money in coin colors: ' + mc)
ok(L('AF_NS.Core.MoneyColor(5)') == '|cffeda55f5c|r' and L('AF_NS.Core.MoneyColor(nil)') == '-', 'copper only; no price shows "-"')
md = [L(f'AF_NS.Core.MoneyDelta({c})') for c in ('150', '-150', '0', 'nil')]
ok(md == ['|cff1eff00+|r|cffeda55f1s|r |cffeda55f50c|r'.replace('|cffeda55f1s|r', '|cffc7c7cf1s|r'), '|cffff4040-|r|cffc7c7cf1s|r |cffeda55f50c|r', '|cffeda55f0c|r', '-'],
   f'MoneyDelta: green + for a gain, red - for a loss: {md}')
tl = [list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()]
ok([r[0] for r in tl] == ['Vendor', 'AH', 'Profit', 'Source'], 'tooltip lines: exactly Vendor, AH, Profit, Source: ' + str([r[0] for r in tl]))
v = L('AF_NS.UI.Vendor(2589)'); ah = L('AF_NS.UI.TargetPrice(AF_NS.Core.Info(2589))')
exp = int(ah * 0.95) - v
ok(str(tl[2][1]) == L(f'AF_NS.Core.MoneyDelta({exp})') and str(tl[2][1]).startswith('|cff1eff00+|r'),
   f'Profit = AH after the 5% cut - vendor, green plus ({ah}c, vendor {v}c -> {tl[2][1]})')
ok(str(tl[3][1]) in ('Gather', 'Drop', 'Crafted'), 'Source line: ' + str(tl[3][1]))
X('IsShiftKeyDown = function() return true end; RealGIC = C_Item.GetItemCount; C_Item.GetItemCount = function(id) return id == 2589 and 24 or 0 end')
tl2 = [list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()]
ok([r[0] for r in tl2] == ['Vendor', 'AH', 'Profit', 'Source'] and not any('Shift' in str(r) for r in tl + tl2),
   'no Shift hint and nothing more with Shift held or the item in your bags')
X('C_Item.GetItemCount = RealGIC; IsShiftKeyDown = function() return false end')
# A vendor pays more than the AH after the cut: a red minus.
X('OldInfo = C_Item.GetItemInfo; C_Item.GetItemInfo = function(id) if id == 2589 then return "Linen Cloth", nil, 1, nil, nil, nil, nil, nil, nil, nil, 10^7 end return OldInfo(id) end')
tl3 = [list(v.values()) for v in L('AF_NS.UI.TooltipLines(2589)').values()]
ok(str(tl3[2][1]).startswith('|cffff4040-|r'), 'vendor pays more: Profit with a red minus: ' + str(tl3[2][1]))
X('C_Item.GetItemInfo = OldInfo')
# An item with no AH data still shows its vendor price; Profit "-".
tl4 = L('AF_NS.UI.TooltipLines(424242)')
ok(tl4 is not None and list(tl4[2].values())[1] == 'no data' and list(tl4[3].values())[1] == '-', 'no AH data: vendor price shown, AH no data, Profit -')
ok(L('AF_NS.UI.TooltipLines(2996)[4][2]') == 'Crafted', 'Source: Crafted for an item a recipe makes')

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
  -- An incomplete listing would make logged flips look gone: no missed-flips logging then.
  LogFlipCalls, RealLogFlips = 0, AF_NS.UI.LogFlips
  AF_NS.UI.LogFlips = function(Now) LogFlipCalls = LogFlipCalls + 1 end
  AF_NS.UI.ShowAHPanel(); Click(AuctionForeverAHPanel.Full); FireEvent("REPLICATE_ITEM_LIST_UPDATE")
  for k = 1, 5 do for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end
  GrowN = 300
  for k = 1, 300 do for _, f in ipairs(AllFramesForTest) do local u = f._scripts.OnUpdate; if u then u(f, 0.016) end end end''')
rd = L('AuctionForeverDB.scanlog[#AuctionForeverDB.scanlog].read')
ok(not L('AF_NS.Scan.Busy()') and rd is not None and rd[1] == 300 and rd[2] == 300,
   f"listing still arriving while read: all 300 read, not the first 100 ({rd and list(rd.values())})")
ok(L('LogFlipCalls') == 0 and 'incomplete' in str(L('AF_NS.Scan.LastResult')), f"full scan that looked incomplete: flips not logged ({L('LogFlipCalls')} calls)")
X('AF_NS.UI.LogFlips = RealLogFlips')
X('C_AuctionHouse.GetNumReplicateItems, C_AuctionHouse.GetReplicateItemInfo, C_AuctionHouse.ReplicateItems, C_AuctionHouse.GetReplicateItemTimeLeft = OldNum, OldInfo, OldRep, OldTL')
# Deposit from the game decides between durations (commodities).
X("""OldDep = C_AuctionHouse.CalculateCommodityDeposit
  C_AuctionHouse.CalculateCommodityDeposit = function(id, idx, q) return idx * 1000 * q end
  AuctionForeverData.info[777001] = AuctionForeverData.info[777001] or { 0, 1, 1 }""")
ok(L('AF_NS.Core.Deposit({ id = 777001 }, 8, 3)') == 6000, 'deposit for 8 h comes from the game')
dv = L('AF_NS.UI.Vendor(777002)')
ok(L('AF_NS.Core.Deposit({ id = 777002 }, 8, 3)') == (dv * 8 // 8) * 3, f'not a commodity: estimated, 3x vendor per 24 h (vendor {dv}c, 8 h x3: {L("AF_NS.Core.Deposit({ id = 777002 }, 8, 3)")})')
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
# (Vendor buys from the real data that need more gold can sort after it since the 2s vendor minimum.)
ok((4306, False) in tl2 and tl2.index((4306, False)) >= 2, f'AF Buy also lists targets your gold cannot reach yet, after the plan: {tl2}')
need = L('(function() for _, E in ipairs(AF_NS.UI.FlipTargets()) do if E.id == 4306 then return E.need end end end)()')
ok(need is not None and abs(need - L('AF_NS.Core.GoldFor(7500)')) <= 1, f'a target shows the gold it needs: {need}')
# An option that fits your budget counts as buyable even when it only came from the any-gold list.
X("""MinSeen = {}
  local Prev = AF_NS.Core.FlipOptions
  AF_NS.Core.FlipOptions = function(I, Cap, Min, Relax)
    if not Relax then MinSeen[#MinSeen + 1] = Min end -- (the near-miss check relaxes the rules on purpose)
    if I.id == 2592 then
      if Cap == math.huge then return { { qty = 20, buyQty = 20, buyUpTo = 60, cost = 1200, resell = 120, hours = 2, durationIndex = 1, profit = 1080 } } end
      return {}
    end
    return Prev(I, Cap, Min, Relax)
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
# AF Buy column headers sort: highest first, again lowest first, a third time back to the plan's order.
X('AF_NS.Trade.SetBuySort("plan")')
def buyheads(): return [L(f'AuctionForeverBuyPanel.Headers[{i}].Label:GetText()') for i in range(1, 9) if L(f'rawget(AuctionForeverBuyPanel.Headers, {i})')]
def buyrows(): return [L(f'AF_NS.Trade.Rows()[{i}]') for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
ok(L('rawget(AuctionForeverBuyPanel, "Sort") == nil') and buyheads() == ['Item', 'Tier', 'Sell rate', 'Buy', 'Resell at', 'Profit', 'Status'],
   f'AF Buy: no sort button, plain headers in plan order: {buyheads()}')
X('AF_NS.Trade.DrawBuy(); Click(AuctionForeverBuyPanel.Headers[6])')
pr = [(r.best or r.flip).profit for r in buyrows()]
ok(pr == sorted(pr, reverse=True) and buyheads()[5] == 'Profit v' and L('(AF_NS.Trade.BuySort())') == 'profit', f'click Profit: highest first, marked {pr}')
X('Click(AuctionForeverBuyPanel.Headers[6])')
pr = [(r.best or r.flip).profit for r in buyrows()]
ok(pr == sorted(pr) and buyheads()[5] == 'Profit ^', 'click Profit again: lowest first')
X('Click(AuctionForeverBuyPanel.Headers[6])')
ok(L('(AF_NS.Trade.BuySort())') == 'plan' and L('AF_NS.Trade.Rows()[1].plan') == True and buyheads()[5] == 'Profit', 'third click: back to the plan order')
X('Click(AuctionForeverBuyPanel.Headers[4])')
co = [r.flip.cost for r in buyrows()]
ok(co == sorted(co, reverse=True) and buyheads()[3] == 'Buy v', f'click Buy: by cost {co}')
# Sell rate column: the item's sell rate as a colored percent (as on the Farm tab), "?" when not measured; sorts by it
# (not measured last), third click back to the plan order.
X('Click(AuctionForeverBuyPanel.Headers[3])')
sr = [L(f'AF_NS.Trade.BuyRate(AF_NS.Trade.Rows()[{i}])') for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
known = [x for x in sr if x is not None]
ok(buyheads()[2] == 'Sell rate v' and known == sorted(known, reverse=True) and sr[:len(known)] == known and len(known) > 1,
   f'click Sell rate: highest first, not measured last {sr}')
r1, c1 = L('AF_NS.Trade.Rows()[1]'), str(L('AuctionForeverBuyPanel.Rows[1].Cells[3]:GetText()'))
ok(c1 == str(L(f'AF_NS.UI.RateText({sr[0]})')) and c1.endswith(f'{int(sr[0] * 100 + 0.5)}%|r'), f'Sell rate cell: colored percent ({c1})')
X('Click(AuctionForeverBuyPanel.Headers[3])')
ok(buyheads()[2] == 'Sell rate ^', 'Sell rate again: lowest first')
X('Click(AuctionForeverBuyPanel.Headers[3])')
ok(L('(AF_NS.Trade.BuySort())') == 'plan', 'Sell rate: third click back to the plan order')
X("""BuyE = AF_NS.Trade.Rows()[1]; SavedST = BuyE.info.sellThrough
  BuyE.info.sellThrough = 0.95; AF_NS.Trade.DrawBuy(); C95 = AuctionForeverBuyPanel.Rows[1].Cells[3]:GetText()
  BuyE.info.sellThrough = 0.5; AF_NS.Trade.DrawBuy(); C50 = AuctionForeverBuyPanel.Rows[1].Cells[3]:GetText()
  BuyE.info.sellThrough = 0.3; AF_NS.Trade.DrawBuy(); C30 = AuctionForeverBuyPanel.Rows[1].Cells[3]:GetText()
  BuyE.info.sellThrough = 0.1; AF_NS.Trade.DrawBuy(); C10 = AuctionForeverBuyPanel.Rows[1].Cells[3]:GetText()
  BuyE.info.sellThrough = nil; AF_NS.Trade.SelectBuy(1); CNil = AuctionForeverBuyPanel.Rows[1].Cells[3]:GetText()
  DNil = AuctionForeverBuyPanel.Detail:GetText()
  BuyE.info.sellThrough = 0.69; AF_NS.Trade.SelectBuy(1); D69 = AuctionForeverBuyPanel.Detail:GetText()
  BuyE.info.sellThrough = SavedST; AF_NS.Trade.DrawBuy()""")
cols = [str(L(v)) for v in ('C95', 'C50', 'C30', 'C10', 'CNil')]
ok(cols == ['|cff1eff0095%|r', '|cffffd10050%|r', '|cffff404030%|r', '|cff9d9d9d10%|r', '|cff9d9d9d?|r'],
   f'Sell rate colors: green 70+, yellow 40+, red 20+, gray below, "?" not measured: {cols}')
d69, dnil = str(L('D69')).split(chr(10))[1], str(L('DNil')).split(chr(10))[1]
ok('expected return, sells 69%' in d69 and 'sell rate not measured yet' in dnil, f'detail line: tier and sell rate ({d69} / {dnil})')
X('Click(AuctionForeverBuyPanel.Headers[2])')
rt = [L(f'AF_NS.Trade.Return(AF_NS.Trade.Rows()[{i}].flip)') or -1 for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
ok(rt == sorted(rt, reverse=True) and buyheads()[1] == 'Tier v', f'click Tier: by expected return {rt}')
X('Click(AuctionForeverBuyPanel.Headers[2]); Click(AuctionForeverBuyPanel.Headers[2])')
ok(L('(AF_NS.Trade.BuySort())') == 'plan', 'Tier: third click back to the plan order')
X('Click(AuctionForeverBuyPanel.Headers[1])')
nm = [str(L(f'AF_NS.UI.SortName({r.id})')) for r in buyrows()]
ok(nm == sorted(nm, reverse=True) and buyheads()[0] == 'Item v', 'click Item: by name')
X('Click(AuctionForeverBuyPanel.Headers[7])')
nd = [L(f'AF_NS.Trade.StatusRank(AF_NS.Trade.Rows()[{i}])') for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
ok(nd == sorted(nd, reverse=True) and buyheads()[6] == 'Status v', 'click Status: by status (plan, fits now, needs gold, craft)')
X('AF_NS.Trade.DrawBuy(); AuctionForeverBuyPanel:GetScript("OnMouseWheel")(AuctionForeverBuyPanel, -1); Click(AuctionForeverBuyPanel.Headers[5])')
ok(L('AuctionForeverBuyPanel.Bar:GetValue()') == 0, 'a re-sort scrolls back to the top')
# Tier bands on expected return (profit / cost): 35% = S, 34.9% = A, 25% = A, 24.9% = B, 15% = B, 10% = C, 9.9% = D;
# vendor buys graded the same way; no profit or no cost = D.
bands = [L(f'(AF_NS.Trade.Tier({{ cost = 1000, profit = {p} }}))') for p in (350, 349, 250, 249, 150, 149, 100, 99, 0, -50)]
ok(bands == ['S', 'A', 'A', 'B', 'B', 'C', 'C', 'D', 'D', 'D'], f'AF Buy tier bands: {bands}')
ok(L('(AF_NS.Trade.Tier({ cost = 1000, profit = 400, vendor = true }))') == 'S' and L('(AF_NS.Trade.Tier({ cost = 0, profit = 5 }))') == 'D'
   and L('(AF_NS.Trade.Tier(nil))') == 'D', 'vendor buys graded on profit / cost; no cost = D')
ok(L('AF_NS.Trade.TierLine({ cost = 1000, profit = 280 })') == '|cff1eff00Tier A|r: 28% expected return', 'tier line: "Tier A: 28% expected return"')
X('AF_NS.Trade.SetBuySort("plan"); AF_NS.Trade.SelectBuy(1)')
det = str(L('AuctionForeverBuyPanel.Detail:GetText()'))
tc = str(L('AuctionForeverBuyPanel.Rows[1].Cells[2]:GetText()'))
ok('expected return' in det.split(chr(10))[1] and tc.endswith('|r') and tc[10:11] in 'SABCD', f'AF Buy row shows its tier ({tc}) and the detail line says why: {det.split(chr(10))[1]}')
# AF Buy rows: short name in the row, the full name in the detail line.
X("""BuyId = AF_NS.Trade.Rows()[1].id; RealGII3 = C_Item.GetItemInfo
  C_Item.GetItemInfo = function(id) if id == BuyId then return "Pattern: Enchant Something Long", nil, 1 end return RealGII3(id) end
  AF_NS.UI.ItemName(BuyId); AF_NS.Trade.SelectBuy(1)""")
bc, bd = str(L('AuctionForeverBuyPanel.Rows[1].Cells[1]:GetText()')), str(L('AuctionForeverBuyPanel.Detail:GetText()'))
ok('Ench Something Long' in bc and 'Pattern' not in bc and 'Pattern: Enchant Something Long' in bd, f'AF Buy: short name in the row ({bc}), full in the detail')
X('RealRecipes = AF_Recipes; AF_Recipes = setmetatable({ [BuyId] = {} }, { __index = RealRecipes }); AF_NS.Trade.DrawBuy()')
bcc = str(L('AuctionForeverBuyPanel.Rows[1].Cells[1]:GetText()'))
X('AF_Recipes = RealRecipes; AF_NS.Trade.DrawBuy()')
ok(bcc.endswith(' |cff9d9d9d(c)|r') and not str(L('AuctionForeverBuyPanel.Rows[1].Cells[1]:GetText()')).endswith('(c)|r'), f'AF Buy rows: "(c)" after crafted items ({bcc})')
X('C_Item.GetItemInfo = RealGII3; AF_NS.UI.ItemName(BuyId); AF_NS.Trade.DrawBuy()')
X('AF_NS.Trade.SetBuySort("plan")')
tg = L('AF_NS.Trade.TargetGold()')
mins = [L(f'AF_NS.Trade.Rows()[{i}].minGold') for i in range(1, int(L('#AF_NS.Trade.Rows()')) + 1)]
ok(tg is not None and tg == -(-min(m for m in mins if m is not None) // 100) * 100, f'target budget = least gold any target needs, rounded up to the silver: {tg}')
X('AF_NS.Trade.DrawBuy()')
bt, tt = str(L('AuctionForeverBuyPanel.Budget:GetText()')), str(L('AuctionForeverBuyPanel.Target:GetText()'))
ok(bt.startswith('Flip Budget: |cff') and 'Target Budget: |cff' in tt, f'header rows: colored Flip Budget, then Target Budget ({bt!r} / {tt!r})')
ok(L('AF_NS.Trade.Rows()[1].plan') == True, 'back to plan order: plan first')
# A flip row: the same panel with one line (buy N, pay up to, listed now, cost, its Buy button) and what to do then.
X('AF_NS.Trade.SelectBuy(1); FE = AF_NS.Trade.SelectedBuy(); FF = FE.flip')
fl = [plain(L(f'AuctionForeverBuyPanel.Lines[1].Cells[{c}]:GetText()')) for c in range(1, 7)]
fs = [plain(x) for x in str(L('AuctionForeverBuyPanel.Summary:GetText()')).split(chr(10))]
fm = lambda x: plain(L(f'AF_NS.Core.MoneyColor({x})'))
fvis = L('AF_NS.Trade.BuyVisible()')
ok(fl[0] == str(L('FF.buyQty')) and fl[2] == 'AH' and fl[3] == 'up to ' + fm(L('FF.buyUpTo')) and fl[4] == str(L('AF_NS.Farm.Listed(FE.info)')) and fl[5] == fm(L('FF.cost'))
   and not L('AuctionForeverBuyPanel.Lines[2]:IsShown()') and L('AuctionForeverBuyPanel.Buy:IsShown()') and L('AuctionForeverBuyPanel.Buy._parent == AuctionForeverBuyPanel.Lines[1]') == True
   and str(L('AuctionForeverBuyPanel.PaneHead[2]:GetText()')) == 'Item'
   and fs[0].startswith('Then: Auction at ' + fm(L('FF.resell')) + ' each over ') and fs[1].startswith('Cost ' + fm(L('FF.cost')) + '   Profit +') and fs[2].startswith('Leaves you ')
   and fvis == 8, f'flip panel: one line {fl}, then: {fs}, table {fvis} rows')
sp = L('AuctionForeverBuyPanel.Status._points[#AuctionForeverBuyPanel.Status._points]')
ok(sp is not None and sp[1] == 'LEFT' and L('AuctionForeverBuyPanel.Status._points[#AuctionForeverBuyPanel.Status._points][2] == AuctionForeverBuyPanel.Skip') and sp[3] == 'RIGHT'
   and L('AuctionForeverBuyPanel.Status._width') == 350,
   'AF Buy status message sits beside the buttons, 350 wide (long messages no longer run down over the bid bar)')
# Roomier AF Buy table: below the summary lines with a gap, full window width, columns 10 apart.
rp = L('AuctionForeverBuyPanel.Rows[1]._points[1]')
c2 = L('AuctionForeverBuyPanel.Rows[1].Cells[2]._points[1]')
c7w = L('AuctionForeverBuyPanel.Rows[1].Cells[7]._width')
ok(rp[3] == -100 and L('AuctionForeverBuyPanel.Headers[1]._points[1][3]') == -80 and L('AuctionForeverBuyPanel.Filters[1]._points[#AuctionForeverBuyPanel.Filters[1]._points][5]') == -58 and c2[4] == 24 + 220 + 10 and c7w == 130 and L('AuctionForeverBuyPanel.Results._points[1][3]') == -38,
   f'AF Buy table: filter bar at -58, headers at -82, rows from -100, Item 220 wide, columns 10 apart, Status 130 wide ({list(rp.values())}, {list(c2.values())}, {c7w})')
# Amounts in the AF Buy table use the coin colors (also on rows you can't afford yet; only their name is greyed).
X('AF_NS.Trade.DrawBuy()')
cr = [(L(f'AuctionForeverBuyPanel.Rows[{i}].Cells[4]:GetText()'), L(f'AuctionForeverBuyPanel.Rows[{i}].Cells[6]:GetText()'), L(f'AF_NS.Trade.Rows()[{i}]'))
      for i in range(1, min(14, int(L('#AF_NS.Trade.Rows()'))) + 1)]
coin = str(L('AF_NS.Core.MoneyColor(1)')).split('1c')[0]
ok(len(cr) > 0 and all(coin in str(b) and coin in str(p) for b, p, _ in cr), f'AF Buy amounts in coin colors ({cr[0][0]!r} / {cr[0][1]!r})')
ok(all(str(p) == L(f'AF_NS.Core.MoneyDelta({(r.best or r.flip).profit if L("(AF_NS.Trade.BuySort())") == "profit" else r.flip.profit})') for _, p, r in cr)
   and any(str(p).startswith('|cff1eff00+|r') for _, p, _ in cr), f'AF Buy profit cells: green + (red - for a loss) ({cr[0][1]!r})')
# Scroll bars: shown when a list is longer than its 14 rows; dragging scrolls; "1-14 of N" under it.
X('''SB = AF_NS.Trade.Rows(); SBn = #SB
  for k = 1, 30 do SB[#SB + 1] = SB[((k - 1) % SBn) + 1] end
  AF_NS.Trade.DrawBuy()''')
BP = 'AuctionForeverBuyPanel'
SV = L('AF_NS.Trade.BuyVisible()')
ok(L('SBn') > 0 and L(f'{BP}.Bar:IsShown()') and L(f'{BP}.Bar.Count:GetText()') == f"1-{SV} of {L('#SB')}" and SV < 14, f'AF Buy: long list shows a scroll bar and 1-{SV} of N (rows above the panel): ' + str(L(f'{BP}.Bar.Count:GetText()')))
X(f'{BP}.Bar:SetValue(5)')
ok(L(f'{BP}.Rows[1].id') == L('SB[6].id') and L(f'{BP}.Bar.Count:GetText()') == f"{6}-{5 + SV} of {L('#SB')}", 'AF Buy: dragging the bar scrolls the list: ' + str(L(f'{BP}.Bar.Count:GetText()')))
X(f'{BP}._scripts.OnMouseWheel({BP}, -1); AF_NS.Trade.DrawBuy()')
ok(L(f'{BP}.Bar:GetValue()') == 8, 'AF Buy: the mouse wheel moves the bar too: ' + str(L(f'{BP}.Bar:GetValue()')))
X('for k = #SB, SBn + 1, -1 do SB[k] = nil end; AF_NS.Trade.DrawBuy()')
ok(not L(f'{BP}.Bar:IsShown()') and not L(f'{BP}.Bar.Count:IsShown()'), 'AF Buy: short list, no scroll bar')
X('''SQ = AF_NS.Trade.SellQueue(); SQn = #SQ
  -- (whether your bag items are worth the AH depends on the hourly data: make them so here)
  local Rec = AF_NS.Core.Recommend; AF_NS.Core.Recommend = function() return "Auction" end
  local Src = SQn > 0 and SQ or AF_NS.Trade.BuildQueue()
  AF_NS.Core.Recommend = Rec
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
cells = L('(function() local t = {} for _, f in ipairs(AllFramesForTest) do if f._kind == "FontString" and type(f._text) == "string" and (f._text:find("vendor it") or f._text:find("Then: Vendor for", 1, true) and f._text:find("bought in 1 purchase", 1, true)) then t[#t+1] = f._text end end return #t end)()')
ok(cells >= 2, f'row says "vendor it" and the panel says "Then: Vendor for ... bought in 1 purchase" ({cells})')
vd = plain(L('AuctionForeverBuyPanel.Summary:GetText()'))
ok(vd.startswith('Then: Vendor for 10s 00c each (30s 00c, no AH cut), bought in 1 purchase') and plain(L('AuctionForeverBuyPanel.Lines[1].Cells[1]:GetText()')) == '3',
   'vendor buy panel: buy 3, "Then: Vendor for ...": ' + vd.replace(chr(10), ' | '))
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
# Forever's minimum deposit is 1 copper: a cheap item's estimated deposit rounds to 1c, never 0 (and never 1 silver).
X("""RealGI2 = C_Item.GetItemInfo
  C_Item.GetItemInfo = function(id) local r = { RealGI2(id) }; if id == 777003 then r[1] = "Cheap"; r[11] = 1 elseif id == 777004 then r[1] = "Pricier"; r[11] = 100 end return unpack(r, 1, 11) end""")
ok(L('AF_NS.Core.Deposit({ id = 777003 }, 2, 1)') == 1 and L('AF_NS.Core.Deposit({ id = 777003 }, 24, 1)') == 3,
   f"estimated deposit: at least 1c (vendor 1c: 2 h {L('AF_NS.Core.Deposit({ id = 777003 }, 2, 1)')}c, 24 h {L('AF_NS.Core.Deposit({ id = 777003 }, 24, 1)')}c)")
ok(L('AF_NS.Core.Deposit({ id = 777004 }, 2, 1)') == 25 and L('AF_NS.Core.Deposit({ id = 777004 }, 24, 2)') == 600,
   'estimated deposit otherwise unchanged: 3/24 of the vendor price per hour (vendor 1s: 2 h 25c, 24 h x2 6s)')
X('C_Item.GetItemInfo = RealGI2')
# Empty Flip list names both returns.
X('RealFS = AF_NS.Core.FlipStatus; AF_NS.Core.FlipStatus = function() return "good" end; OldGM5 = GetMoney; GetMoney = function() return 200000 end')
er2 = str(L('AF_NS.UI.FlipEmptyReason()'))
X('AF_NS.Core.FlipStatus = RealFS; GetMoney = OldGM5')
ok('10%+ return, 20%+ for slow sellers' in er2, 'empty Flip list states the 10% / 20% returns: ' + er2.replace('\n', ' '))
# Missed flips: every finished scan logs the flips on offer; later scans mark them still there or gone.
X("""RealRows = AF_NS.UI.FlipRows
  Offer = {}
  AF_NS.UI.FlipRows = function() return Offer end
  function Fl(id, P, Q, Pr) return { id = id, flip = { buyUpTo = P, buyQty = Q, qty = Q, profit = Pr, cost = P * Q } } end
  AuctionForeverDB = AuctionForeverDB or {}
  AuctionForeverDB.flipLog = nil; AuctionForeverDB.buys = {}
  Offer = { Fl(880001, 50, 10, 900), Fl(880002, 70, 5, 600), Fl(880003, 30, 2, 500), { id = 880009, flip = { vendor = true, buyUpTo = 5, buyQty = 1, profit = 300 } } }
  AF_NS.UI.LogFlips(1000)""")
fl = L('AuctionForeverDB.flipLog')
first = [list(fl[i].values()) for i in range(1, len(fl) + 1)] if fl else []
ok(len(first) == 3 and all(e[4] == 1000 and e[5] == 1000 and len(e) == 6 for e in first) and sorted(e[0] for e in first) == [880001, 880002, 880003],
   f'first scan: the 3 flips on offer logged (vendor buys left out): {first}')
e1 = [e for e in first if e[0] == 880001][0]
ok(e1[1] == 50 and e1[2] == 10 and e1[3] == 900, f'logged as id, price, qty, profit, firstSeen, lastSeen: {e1}')
X("""AuctionForeverDB.buys = { { 1300, 880003, 2, 60, 250 } }
  Offer = { Fl(880001, 45, 10, 950) }
  AF_NS.UI.LogFlips(1600)""")
def Entry(id, nth=1):
    n = 0
    for i in range(1, int(L('#AuctionForeverDB.flipLog')) + 1):
        e = L(f'AuctionForeverDB.flipLog[{i}]')
        if e[1] == id:
            n += 1
            if n == nth: return {k: e[k] for k in range(1, 9)}
    return None
a, b, c = Entry(880001), Entry(880002), Entry(880003)
ok(a[6] == 1600 and a[7] is None and int(L('#AuctionForeverDB.flipLog')) == 3, f'still offered at the same or a lower price: lastSeen updated, no new entry ({a})')
ok(b[7] == 1600 and b[6] == 1000 and not b[8], f'no longer offered: goneAt set ({b})')
ok(c[7] == 1600 and c[8] is True, f'gone after you bought some: marked bought ({c})')
X('Offer = { Fl(880001, 60, 10, 900) }; AF_NS.UI.LogFlips(2200)')
a1, a2 = Entry(880001), Entry(880001, 2)
ok(a1[7] == 2200 and a2 is not None and a2[2] == 60 and a2[5] == 2200 and a2[7] is None, f'offered again only at a higher price: the old one is gone, a new one logged ({a1}, {a2})')
# /af missed: counts, median time seen, top items.
X('LastPrint = nil; Printed = {}; RealPrint = print; print = function(...) Printed[#Printed + 1] = table.concat({ tostring((...)) }, " ") end; SlashCmdList.AUCTIONFOREVER("missed"); print = RealPrint')
pr = [str(v) for v in L('Printed').values()]
ok(len(pr) >= 3 and '4 logged, 2 gone before you bought (1 you bought), 1 still open' in pr[0], f'/af missed summary: {pr}')
ok(any('5 min (median)' in p for p in pr), f'median time a gone flip was still seen: (600 s + 0 s) / 2 = 5 min: {pr}')
ok(any('880001' in p or 'Item 880001' in p for p in pr) and all(all(ord(ch) < 128 for ch in p) for p in pr), f'top items listed, ASCII only: {pr}')
# Capped: oldest entries dropped.
X("""Offer = {}; for k = 1, 310 do Offer[k] = Fl(881000 + k, 10, 1, 600) end
  AF_NS.UI.LogFlips(3000)""")
ok(int(L('#AuctionForeverDB.flipLog')) == 300 and L('AuctionForeverDB.flipLog[1][1]') != 880001, f"log capped at 300 entries, oldest dropped ({L('#AuctionForeverDB.flipLog')})")
X('AF_NS.UI.FlipRows = RealRows; AuctionForeverDB.flipLog = nil')
# ---- Farm tab: Gather and Craft views from Farm.lua (fixture data, independent of the real data file) -----------
toc = [l.strip() for l in open(os.path.join(ADDON, 'AuctionForever.toc'), encoding='utf-8') if l.strip() and not l.startswith('#')]
ok(toc[:3] == ['Core.lua', 'Recipes.lua', 'Farm.lua'], f'.toc loads Recipes.lua and Farm.lua right after Core.lua: {toc[:3]}')
ok(L('AF_NS.Farm ~= nil and type(AF_Recipes) == "table"'), 'Farm.lua and Recipes.lua loaded with the add-on')
X("""SavedData, SavedDB, SavedVer = AuctionForeverData, AuctionForeverDB, AF_NS.Scan.Version
  AuctionForeverDB = { names = {} }
  local F = { "low", "qty", "med", "hi", "med24", "medAll", "perHour", "medHour", "hoursSeen", "hoursWithSales", "sales",
    "sellThrough", "qtyDayAgo", "newHour", "lows", "lowHi24", "ladder" }
  local function Good(P, PerHour) return { P, 10, P, P, P, P, PerHour, PerHour, 24, 24, 400, 0.9, 10, PerHour, nil, nil, { { P, 10 } } } end
  local Items, Info = {}, {}
  Items[2589] = Good(100, 40)     -- Linen Cloth
  Items[2996] = Good(1000, 5)     -- Bolt of Linen Cloth (2 Linen): a paying craft
  Items[118] = Good(2000, 5)      -- Minor Healing Potion (First Aid in Forever): vial + spice from vendors, 1 Peacebloom
  Items[2447] = Good(50, 30)      -- Peacebloom
  Items[880100] = Good(900000, 5) -- gear (rare): Drop
  Items[880101] = Good(5000, 5)   -- gear (common): left out
  Items[880102] = Good(4000, 5)   -- junk (common, not a trade good): left out
  Items[880103] = Good(3000, 5)   -- cloth (common trade good): Drop
  Items[880104] = Good(2500, 5)   -- an Uncommon drop: Drop
  for k = 1, 20 do Items[880200 + k] = Good(1000 + k * 100, 2) end
  for id in pairs(Items) do Info[id] = { 10, 1, 1 } end
  Info[880100] = { 10, 3, 0 }; Info[880101] = { 10, 1, 0 }; Info[880104] = { 10, 2, 0 }
  -- Classes (GetItemInfoInstant): herbs for the gathered ones, cloth for Linen's craft, gear, junk.
  FixClass = { [2589] = { 7, 9 }, [2447] = { 7, 9 }, [880100] = { 4, 2 }, [880101] = { 4, 1 }, [880102] = { 15, 0 }, [880103] = { 7, 5 },
    [880104] = { 15, 0 } }
  for k = 1, 20 do FixClass[880200 + k] = { 7, 9 } end
  AuctionForeverData = { v = 1, time = os.time(), hours = 24, fields = F, items = Items, info = Info, names = {} }
  AF_NS.Scan.Version = (AF_NS.Scan.Version or 0) + 1
  RealInstant = C_Item.GetItemInfoInstant
  C_Item.GetItemInfoInstant = function(id) local c = FixClass[id] if c then return id, "", "", "", 134400, c[1], c[2] end return RealInstant(id) end
  -- Quality as the shipped data says (the mock's GetItemInfo says common for everything).
  BaseGII = C_Item.GetItemInfo
  C_Item.GetItemInfo = function(id) local r = { BaseGII(id) } local I = AuctionForeverData.info and AuctionForeverData.info[id]
    if I and r[1] then r[3] = I[2] end return unpack(r, 1, 11) end
  RealSkill = C_SkillInfo
  C_SkillInfo = nil
  RealGII = C_Item.GetItemInfo
  InfoCalls = 0
  C_Item.GetItemInfo = function(...) InfoCalls = InfoCalls + 1 return RealGII(...) end
  GatherRows = AF_NS.UI.GatherRows()
  CraftRows = AF_NS.UI.CraftRows()
  ComputeInfoCalls = InfoCalls
  C_Item.GetItemInfo = RealGII""")
gr = L('GatherRows')
gids = [gr[i].id for i in range(1, len(gr) + 1)]
ok(880100 not in gids and 880103 not in gids and 2589 in gids and 2447 in gids and len(gids) == 22, f'Gather: the gathered items only ({len(gids)} rows)')
ok(all(gr[i].source == 'Gather' for i in range(1, len(gr) + 1)), 'Gather rows all have source Gather')
dr = L('AF_NS.UI.DropRows()')
dids = sorted(dr[i].id for i in range(1, len(dr) + 1))
ok(dids == [880100, 880103, 880104], f'Drop: Uncommon+ (gear too) and trade goods at any quality; common gear and junk left out: {dids}')
ok(2996 not in gids and 118 not in gids and all(not gr[i].crafted for i in range(1, len(gr) + 1)),
   'Gather: crafted items (Bolt of Linen Cloth, the potion) left out: only what nobody crafts')
fr_ids = [L(f'AF_NS.UI.FarmRows()[{i}].id') for i in range(1, int(L('#AF_NS.UI.FarmRows()')) + 1)]
ok(2996 in fr_ids and 880100 not in fr_ids, 'the quick scan list still has crafted items, still no gear')
vals = [gr[i].expected for i in range(1, len(gr) + 1)]
ok(vals == sorted(vals, reverse=True), 'Gather: best expected each first')
ok(L('ComputeInfoCalls') == 0, f'working out both lists asks the game for no item info (no server flood): {L("ComputeInfoCalls")} calls')
r = [gr[i] for i in range(1, len(gr) + 1) if gr[i].id == 2589][0]
# Linen: AF Sell's price for one (cheapest listing 100c, nothing cheaper) after the cut; 90% sell rate; the market's
# 40 an hour = 960 a day.
ok(abs(r.salesDay - 960) < 0.01 and r.rate == 0.9 and r.net > 0 and r.expected < r.net, f'Gather row: net each, sell rate, expected each, market sales ({r.net:.2f}, {r.expected:.2f}, {r.salesDay:.0f}/day)')
cr = L('CraftRows')
cids = [(cr[i].id, cr[i].spell) for i in range(1, len(cr) + 1)]
ok((2996, 2963) in cids and (118, 1244431) in cids and all(cr[i].spell for i in range(1, len(cr) + 1)),
   f'Craft: only recipe rows, for items in the data (all professions while unknown): {cids}')
ok(L('AF_NS.UI.ProfessionsKnown') is False and not L('AF_NS.UI.CraftFiltered'), 'professions not known: all recipes shown')

# The window: Gather view, columns, scroll bar, controls, honest per-day label.
X('AF_NS.UI.Toggle(1); if not AuctionForeverFrame:IsShown() then AF_NS.UI.Toggle(1) end')
def heads(): return [L(f'AuctionForeverFrame.Headers[{i}].Label:GetText()') for i in range(1, 9)]
def shown(field):
    rows = L('AF_NS.UI.ShownRows()')
    return [rows[i][field] for i in range(1, len(rows) + 1)]
def py_tiers(scores):
    """The tier rule over a list already sorted highest first: S top 10%, A to 30%, B to 60%, C to 80%, D the rest or <= 0."""
    out, prev, pt, n = [], None, None, len(scores)
    for i, x in enumerate(scores):
        if x is None or x <= 0: t = 'D'
        elif x == prev: t = pt
        else:
            a = i / n
            t = 'S' if a < 0.1 else 'A' if a < 0.3 else 'B' if a < 0.6 else 'C' if a < 0.8 else 'D'
        out.append(t); prev, pt = x, t
    return out
# All view: the default; Gather and Craft rows together, no item twice, tiers over the combined list.
FB = 'AuctionForeverFrame.FarmBar'
ok(L('AF_NS.UI.FarmView') == 'all' and not L(f'{FB}.All:IsEnabled()') and L(f'{FB}.Gather:IsEnabled()') and L(f'{FB}.Craft:IsEnabled()') and L(f'{FB}.Drop:IsEnabled()')
   and L(f'{FB}.Prof:IsShown()'), 'default view All: its button greyed, professions button shown (craft rows in it)')
ok(heads() == ['Item', 'Tier', 'Kind', 'Gold each', 'Sell rate', 'Expected v', 'Sales/day', 'Your gold/hr'], f'All columns, sorted by expected: {heads()}')
n_all = int(L('#AF_NS.UI.ShownRows()'))
rows_all = [(L(f'AF_NS.UI.ShownRows()[{i}].id'), L(f'AF_NS.UI.ShownRows()[{i}].spell')) for i in range(1, n_all + 1)]
g_ids = {i for i, sp in rows_all if sp is None}
c_ids = {i for i, sp in rows_all if sp is not None}
ok(n_all == len(gr) + len(dr) + len(cr) and g_ids == set(gids) | set(dids) and {(i, sp) for i, sp in rows_all if sp} == set(cids) and not (g_ids & c_ids)
   and len(set(i for i, sp in rows_all)) == n_all, f'All = Gather + Drop + Craft rows, one row per item ({n_all} = {len(gr)} + {len(dr)} + {len(cr)})')
ok(2996 in c_ids and 118 in c_ids and 2996 not in g_ids and 118 not in g_ids, 'a crafted item shows in All as its craft row only')
sc = [L(f'(function(R) if R.spell then return not R.buyExcluded and R.expected or nil end return R.expected end)(AF_NS.UI.ShownRows()[{i}])')
      for i in range(1, n_all + 1)]
ok([x for x in sc if x is not None] == sorted([x for x in sc if x is not None], reverse=True), 'All: highest expected first (each / a craft)')
at = [L(f'AF_NS.UI.ShownRows()[{i}].tier') for i in range(1, n_all + 1)]
ok(at == py_tiers(sc), f'All: tiers by percentile over the combined list: {"".join(at)}')
gtier = {L(f'AF_NS.UI.GatherRows()[{i}].id'): L(f'AF_NS.UI.GatherRows()[{i}].tier') for i in range(1, len(gr) + 1)}
diff = [(rid, gtier[rid], at[k]) for k, (rid, sp) in enumerate(rows_all) if sp is None and rid in gtier and gtier[rid] != at[k]]
ok(len(diff) > 0, f'All rows carry their own tier (the Gather view keeps its own): {diff}')
cells = {}
for i in range(1, min(n_all, 14) + 1):
    rid, sp = L(f'AuctionForeverFrame.Rows[{i}].entry.id'), L(f'AuctionForeverFrame.Rows[{i}].entry.spell')
    cells[(rid, sp)] = [str(L(f'AuctionForeverFrame.Rows[{i}].Cells[{c}]:GetText()')) for c in (3, 8)]
kinds = {k: v[0] for k, v in cells.items()}
ok(all(v in ('Gather', 'Drop', 'Crafted') for k, v in kinds.items() if k[1] is None) and all(v not in ('Gather', 'Drop') for k, v in kinds.items() if k[1] is not None)
   and all(cells[k][1] == '-' for k in cells if k[1] is not None), f'All rows: Kind = Gather / Drop / the profession; gold/hr only for sell rows: {kinds}')
allnames = [str(L(f'AuctionForeverFrame.Rows[{i}].Cells[1]:GetText()')) for i in range(1, min(n_all, 14) + 1)]
mark = {L(f'AuctionForeverFrame.Rows[{i}].entry.id'): ('(c)' in allnames[i - 1]) for i in range(1, min(n_all, 14) + 1)}
ok(all(v == (k in (2996, 118)) for k, v in mark.items()), f'no "(c)" on items nobody crafts: {mark}')
ok(L('AF_NS.UI.CraftedMark(2996)') == ' |cff9d9d9d(c)|r' and L('AF_NS.UI.CraftedMark(2589)') == '', 'the "(c)" mark (gray, ASCII) for crafted items only')
X('Click(AuctionForeverFrame.Headers[4])')
go = [L(f'(function(R) if R.spell then return not R.buyExcluded and R.profit or nil end return R.net end)(AF_NS.UI.ShownRows()[{i}])') for i in range(1, n_all + 1)]
gk = [x for x in go if x is not None]
ok(heads()[3] == 'Gold each v' and gk == sorted(gk, reverse=True) and go[:len(gk)] == gk, 'All: Gold each sorts (net each / profit a craft)')
X('Click(AuctionForeverFrame.Headers[3])')
kd = [str(L(f'(function(R) if R.spell then return AF_RecipeSkills[R.skill] end return R.source end)(AF_NS.UI.ShownRows()[{i}])')) for i in range(1, n_all + 1)]
ok(heads()[2] == 'Kind v' and kd == sorted(kd, reverse=True), f'All: Kind sorts {sorted(set(kd))}')
X('Click(AuctionForeverFrame.Headers[2])')
ok(heads()[1] == 'Tier v' and L('AF_NS.UI.ShownRows()[1].tier') == 'S', 'All: Tier sorts')
X('Click(AuctionForeverFrame.Headers[6])')
ok(heads()[5] == 'Expected v', 'All: back to expected')
X(f'Click({FB}.Drop)')
ok(heads() == ['Item', 'Tier', 'Net each', 'Sell rate', 'Expected each v', 'Sales/day', 'Your gold/hr', 'Status'] and not L(f'{FB}.Drop:IsEnabled()')
   and sorted(shown('id')) == dids and not L(f'{FB}.Prof:IsShown()'), f'Drop view: the drop rows, sell columns: {sorted(shown("id"))}')
X('Click(AuctionForeverFrame.Headers[3])')
n = shown('net')
ok(n == sorted(n, reverse=True) and heads()[2] == 'Net each v', 'Drop view: headers sort')
X(f'Click({FB}.Gather)')
ok(heads() == ['Item', 'Tier', 'Net each', 'Sell rate', 'Expected each v', 'Sales/day', 'Your gold/hr', 'Status'], f'Gather columns, sorted by expected each (marked): {heads()}')
ok(L('AuctionForeverFrame.FarmBar:IsShown()') and 'sell rate' in str(L('AuctionForeverFrame.FarmBar.Note:GetText()')) and 'market room' not in str(L('AuctionForeverFrame.FarmBar.Note:GetText()')),
   'note explains expected: ' + str(L('AuctionForeverFrame.FarmBar.Note:GetText()')))
# Tiers in the list: 22 rows -> S = 3 (top 10%), A = 4, B = 7, C = 4, D = 4, in expected order.
tiers = [L(f'AF_NS.UI.ShownRows()[{i}].tier') for i in range(1, 23)]
ok(tiers == ['S'] * 3 + ['A'] * 4 + ['B'] * 7 + ['C'] * 4 + ['D'] * 4, f'tiers by percentile of expected each: {"".join(tiers)}')
ok(L('AuctionForeverFrame.List') and L('(function() for _, f in ipairs(AllFramesForTest) do if f._text == "|cffa335eeS|r" then return true end end end)()'),
   'tier S shown in purple')
ok(L('AuctionForeverFrame.Bar:IsShown()') and L('AuctionForeverFrame.Bar.Count:GetText()') == '1-14 of 22', 'scroll bar with "1-14 of 22"')
ok(not L('AuctionForeverFrame.FarmBar.Gather:IsEnabled()') and L('AuctionForeverFrame.FarmBar.Craft:IsEnabled()') and L('AuctionForeverFrame.FarmBar.All:IsEnabled()')
   and not L('AuctionForeverFrame.FarmBar.Prof:IsShown()'), 'Gather selected: its button greyed, no professions button')
X('AuctionForeverFrame.List:GetScript("OnMouseWheel")(AuctionForeverFrame.List, -1)')
ok(L('AuctionForeverFrame.Bar.Count:GetText()') == '4-17 of 22', 'mouse wheel scrolls and moves the bar: ' + str(L('AuctionForeverFrame.Bar.Count:GetText()')))
v = shown('expected')
ok(v == sorted(v, reverse=True), 'default order: expected each (net each x sell rate - deposit lost), highest first')
ok(L('rawget(AuctionForeverFrame.FarmBar, "Sort") == nil'), 'no sort button: the column headers sort')
# Click a header: that column, highest first, back to the top; again: lowest first.
X('Click(AuctionForeverFrame.Headers[3])')
n = shown('net')
ok(n == sorted(n, reverse=True) and heads()[2] == 'Net each v' and heads()[4] == 'Expected each' and L('AuctionForeverFrame.Bar.Count:GetText()') == '1-14 of 22',
   f'header click: net each, highest first, marked, scrolled to the top ({heads()[2]})')
X('Click(AuctionForeverFrame.Headers[3])')
n = shown('net')
ok(n == sorted(n) and heads()[2] == 'Net each ^', 'same header again: lowest first')
X('Click(AuctionForeverFrame.Headers[6])')
sd = shown('salesDay')
ok(sd == sorted(sd, reverse=True) and heads()[5] == 'Sales/day v', 'market sales a day column sorts')
X('Click(AuctionForeverFrame.Headers[2])')
sc = shown('score')
ok(sc == sorted(sc, reverse=True) and heads()[1] == 'Tier v' and L('AF_NS.UI.ShownRows()[1].tier') == 'S', 'Tier column sorts by the score (expected)')
X('Click(AuctionForeverFrame.Headers[2])')
ok(L('AF_NS.UI.ShownRows()[1].tier') == 'D' and heads()[1] == 'Tier ^', 'Tier again: lowest first')
X('Click(AuctionForeverFrame.Headers[1])')
names = [str(L(f'AF_NS.UI.SortName({i})')) for i in shown('id')]
ok(names == sorted(names, reverse=True), 'item name column sorts (by saved/shipped names, no server calls)')
ok(2589 in [L(f'AF_NS.UI.QuickList()')[i] for i in range(1, len(L('AF_NS.UI.QuickList()')) + 1)], 'the quick scan list is not affected by the shown order')
X('Click(AuctionForeverFrame.FarmBar.Craft); Click(AuctionForeverFrame.FarmBar.Gather)')
ok(heads()[0] == 'Item v', 'the sort is remembered per list for the session')
X('Click(AuctionForeverFrame.Headers[5])')
ok(heads()[4] == 'Expected each v', 'back to expected each')

# Craft view.
X('Click(AuctionForeverFrame.FarmBar.Craft)')
ok(heads() == ['Item', 'Tier', 'Profession', 'Profit/craft', 'Sell rate', 'Expected/craft v', 'Sales/day', 'Added each'],
   f'Craft columns, sorted by expected a craft: {heads()}')
ok(all(L(f'AF_NS.UI.ShownRows()[{i}].tier') in ('S', 'A', 'B', 'C', 'D') for i in range(1, int(L('#AF_NS.UI.ShownRows()')) + 1)), 'craft rows have tiers')
X('Click(AuctionForeverFrame.Headers[8])')
ad = [x for x in shown('added')]
ok(heads()[7] == 'Added each v' and ad == sorted(ad, reverse=True), 'craft header click: value added, highest first')
X('Click(AuctionForeverFrame.Headers[4])')
pc = [x for x in shown('profit') if x is not None]
ok(heads()[3] == 'Profit/craft v' and pc == sorted(pc, reverse=True), 'craft header click: profit a craft')
X('Click(AuctionForeverFrame.Headers[6])')
ok(L('AuctionForeverFrame.FarmBar.Prof:IsShown()') and 'not known' in str(L('AuctionForeverFrame.FarmBar.Note:GetText()')),
   'professions unknown: says all are shown')
X('''Tip = { lines = {} }
  function Tip:AddLine(T) self.lines[#self.lines + 1] = T end
  for _, R in ipairs(AF_NS.UI.CraftRows()) do if R.id == 118 then AF_NS.UI.FarmTooltip(R, Tip) end end''')
tip = [str(v) for v in L('Tip.lines').values()]
labels = [t.split(':')[0] for t in tip if ':' in t and not t.startswith('  ')]
ok(labels == ['Tier', 'Expected', 'Sell rate', 'Sales/day', 'Source', 'Profit/craft', 'Mats on AH'] and any(t.startswith('  ') and 'Inv_misc_bag_08' in t and t.split('|t ')[1].startswith('Vendor') for t in tip) and not any('(vendor)' in t for t in tip)
   and [('AH' if 'Coin_02' in t else 'V') for t in tip if t.startswith('  ')] == sorted([('AH' if 'Coin_02' in t else 'V') for t in tip if t.startswith('  ')])
   and any(t.startswith('  1x') for t in tip) and not any('Shift' in t for t in tip) and all(all(ord(c) < 128 for c in t) for t in tip)
   and all(len(plain(t)) < 80 for t in tip), f'craft row tooltip: short labels, reagents with prices, profit a craft, no Shift block: {tip}')
X('''Tip = { lines = {} }
  function Tip:AddLine(T) self.lines[#self.lines + 1] = T end
  AF_NS.UI.FarmTooltip(AF_NS.UI.GatherRows()[1], Tip)''')
tip = [str(v) for v in L('Tip.lines').values()]
ok([t.split(':')[0] for t in tip if ':' in t] == ['Tier', 'Expected', 'Sell rate', 'Sales/day', 'Source'] and 'Source: Gather' in tip,
   f'gather row tooltip: Tier, Expected, Sell rate, Sales/day, Source: {tip}')
# A craft whose product a vendor pays more for than the mats cost: route Vendor, shown as "V" and "vendor".
X('''AuctionForeverData.info[2996][1] = 5000; AuctionForeverDB.names[2996] = nil
  AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.UI.Load()''')
vr = L('(function() for _, R in ipairs(AF_NS.UI.CraftRows()) do if R.id == 2996 then return R end end end)()')
ok(vr is not None and vr.route == 'Vendor' and abs(vr.expected - (5000 - 200)) < 1 and vr.matCrafts == 5,
   f'Bolt of Linen Cloth vendors for 50s: route Vendor, +48s a craft, 10 Linen listed = 5 crafts ({vr and vr.route}, {vr and vr.expected}, {vr and vr.matCrafts})')
cellsv = None
for i in range(1, 15):
    if L(f'AuctionForeverFrame.Rows[{i}].entry and AuctionForeverFrame.Rows[{i}].entry.id') == 2996:
        cellsv = [str(L(f'AuctionForeverFrame.Rows[{i}].Cells[{c}]:GetText()')) for c in (3, 4, 5, 6, 1)]
ok(cellsv and cellsv[0].startswith('|cffffd100V|r ') and 'vendor' in cellsv[2] and cellsv[1].startswith('|cff1eff00+|r') and cellsv[4].endswith(' |cff9d9d9d(c)|r'),
   f'Craft row: "V" before the profession, sell rate "vendor", green + profit: {cellsv}')
X('''Tip = { lines = {} }
  function Tip:AddLine(T) self.lines[#self.lines + 1] = T end
  for _, R in ipairs(AF_NS.UI.CraftRows()) do if R.id == 2996 then AF_NS.UI.FarmTooltip(R, Tip) end end''')
tip = [str(v) for v in L('Tip.lines').values()]
ok(any(t.startswith('Sell to vendor: |cff1eff00+|r') and 'a craft' in t for t in tip) and 'Sell rate: |cff1eff00vendor|r' in tip
   and any(t.startswith('Profit/craft') and '(Vendor)' in t for t in tip), f'tooltip: Sell to vendor +X a craft: {tip}')
X('''AuctionForeverData.info[2996][1] = 10; AuctionForeverDB.names[2996] = nil
  AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.UI.Load()''')
# Short names in list rows: recipe prefix dropped (start only), "Enchant " -> "Ench "; Libram etc. kept.
sn = {n: L(f'AF_NS.UI.ShortName({n!r})') for n in ('Formula: Enchant Gloves - Greater Agility', 'Pattern: Wicked Leather Headband',
      'Plans: Thorium Belt', 'Recipe: Flask of the Titans', 'Schematic: Gnomish Cloaking Device', 'Blueprint: Spinning Wheel',
      'Manual: Heavy Silk Bandage', 'Libram of Voracity', 'Libram: Foo', 'Codex of Holy Word: Fortitude', 'Enchanted Leather',
      'Lesser Pattern: Test', 'Scroll of Enchant Recipe: X')}
ok(sn['Formula: Enchant Gloves - Greater Agility'] == 'Ench Gloves - Greater Agility' and sn['Pattern: Wicked Leather Headband'] == 'Wicked Leather Headband'
   and sn['Plans: Thorium Belt'] == 'Thorium Belt' and sn['Recipe: Flask of the Titans'] == 'Flask of the Titans'
   and sn['Schematic: Gnomish Cloaking Device'] == 'Gnomish Cloaking Device' and sn['Blueprint: Spinning Wheel'] == 'Spinning Wheel'
   and sn['Manual: Heavy Silk Bandage'] == 'Heavy Silk Bandage', f'recipe prefixes dropped, Enchant shortened: {sn}')
ok(sn['Libram of Voracity'] == 'Libram of Voracity' and sn['Libram: Foo'] == 'Libram: Foo' and sn['Codex of Holy Word: Fortitude'] == 'Codex of Holy Word: Fortitude'
   and sn['Enchanted Leather'] == 'Enchanted Leather' and sn['Lesser Pattern: Test'] == 'Lesser Pattern: Test'
   and sn['Scroll of Enchant Recipe: X'] == 'Scroll of Ench Recipe: X', f'only recipe prefixes at the start; Libram/Codex/Enchanted kept: {sn}')
# In the Gather list: a recipe item's row shows the short name, but the name sort uses the full name: "Recipe: Enchant
# Alpha" sorts after the "Item ..." names (highest first: row 1), where its short form "Ench Alpha" would sort last.
X("""RealGII2 = C_Item.GetItemInfo
  C_Item.GetItemInfo = function(id) if id == 2589 then return "Recipe: Enchant Alpha", nil, 1 end return RealGII2(id) end
  AF_NS.UI.ItemName(2589)
  Click(AuctionForeverFrame.FarmBar.Gather); Click(AuctionForeverFrame.Headers[1])""")
ok(L('AuctionForeverFrame.Rows[1].id') == 2589 and L('AF_NS.UI.SortName(2589)') == 'Recipe: Enchant Alpha',
   f'name sort uses the full name ("Recipe: ..." first, highest first): row 1 = {L("AuctionForeverFrame.Rows[1].id")}')
cell = str(L('AuctionForeverFrame.Rows[1].Cells[1]:GetText()'))
ok('Ench Alpha' in cell and 'Recipe' not in cell, f'Gather row shows the short name: {cell}')
X("""C_Item.GetItemInfo = RealGII2; AF_NS.UI.ItemName(2589)
  Click(AuctionForeverFrame.Headers[5]); Click(AuctionForeverFrame.FarmBar.Craft)""")
ok(L('AF_NS.UI.SortName(2589)') != 'Recipe: Enchant Alpha', 'real name back')
# Tier boundaries on hand-made scores: 10 rows -> S = top 10% (1), A = 10-30% (2), B = 30-60% (3), C = 60-80% (2), D = 2.
X('''TR = {} for k = 1, 10 do TR[k] = { id = k, s = 11 - k } end
  AF_NS.UI.MarkTiers(TR, function(R) return R.s end)''')
ok([L(f'TR[{k}].tier') for k in range(1, 11)] == ['S', 'A', 'A', 'B', 'B', 'B', 'C', 'C', 'D', 'D'], 'tier boundaries: 10 / 30 / 60 / 80 percent')
X('''TR = { { id = 1, s = 50 }, { id = 2, s = 50 }, { id = 3, s = 0 }, { id = 4, s = -5 }, { id = 5 } }
  AF_NS.UI.MarkTiers(TR, function(R) return R.s end)''')
ok([L(f'TR[{k}].tier') for k in range(1, 6)] == ['S', 'S', 'D', 'D', 'D'], 'equal scores share a tier; expected 0 or less (or none) is always D')
rates = [L(f'AF_NS.UI.RateText({r})') for r in ('0.95', '0.7', '0.69', '0.4', '0.39', '0.2', '0.19', 'nil')]
ok(rates == ['|cff1eff0095%|r', '|cff1eff0070%|r', '|cffffd10069%|r', '|cffffd10040%|r', '|cffff404039%|r', '|cffff404020%|r', '|cff9d9d9d19%|r', '|cff9d9d9d?|r'],
   f'sell rate colors: green 70+, yellow 40+, red 20+, gray below, "?" unknown (no purple): {rates}')
# Your professions from the game: Tailoring known (rank 75), First Aid known through its second skill line.
X('''C_SkillInfo = { GetSkillLineInfoByID = function(id)
    if id == 197 then return { skillID = 197, rank = 75 } end
    if id == 2942 then return { skillID = 2942, rank = 40 } end
    if id == 171 then return { skillID = 171, rank = 0 } end
    return nil end }
  AF_NS.UI.Load()''')
cr = L('AF_NS.UI.CraftRows()')
skills = sorted(set(cr[i].skill for i in range(1, len(cr) + 1)))
ok(L('AF_NS.UI.CraftFiltered') and skills == [129, 197], f'My professions: only Tailoring and First Aid recipes ({skills})')
ok(L('(function() for _, R in ipairs(AF_NS.UI.CraftRows()) do if R.skill == 197 then return R.myRank end end end)()') == 75, 'your rank kept for the tooltip')
X('''RealSkill2 = C_SkillInfo
  C_SkillInfo = { GetSkillLineInfoByID = function(id) if id == 197 then return { skillID = 197, rank = 75 } end return nil end }
  AF_NS.UI.SetFarmView("all")''')
ar = L('AF_NS.UI.ShownRows()')
r118 = [ar[i] for i in range(1, len(ar) + 1) if ar[i].id == 118]
ok(len(r118) == 1 and r118[0].spell is None and r118[0].source == 'Crafted',
   f'First Aid not yours: the potion stays in All as a sell row (Kind Crafted), once ({[(r.spell, r.source) for r in r118]})')
kc = [str(L(f'AuctionForeverFrame.Rows[{i}].Cells[3]:GetText()')) for i in range(1, 15) if L(f'AuctionForeverFrame.Rows[{i}].entry and AuctionForeverFrame.Rows[{i}].entry.id') == 118]
ok(kc == ['Crafted'], f'its Kind cell: {kc}')
X('C_SkillInfo = RealSkill2; AF_NS.UI.SetFarmView("craft")')
X('Click(AuctionForeverFrame.FarmBar.Prof)')
ok(L('AF_NS.UI.CraftAll') and L('AuctionForeverFrame.FarmBar.Prof:GetText()') == 'All professions' and not L('AF_NS.UI.CraftFiltered'), 'All professions button shows every recipe')
X('Click(AuctionForeverFrame.FarmBar.Prof)')
# Cached until the data changes: Farm.Crafts runs once per data version.
X('''RealCrafts = AF_NS.Farm.Crafts; CraftRuns = 0
  AF_NS.Farm.Crafts = function(...) CraftRuns = CraftRuns + 1 return RealCrafts(...) end
  AF_NS.UI.CraftRows(); AF_NS.UI.Load(); AF_NS.UI.Refresh(); AF_NS.UI.CraftRows()''')
ok(L('CraftRuns') == 0, 'redraws reuse the cached craft list')
X('AF_NS.Scan.Version = AF_NS.Scan.Version + 1; AF_NS.UI.CraftRows()')
ok(L('CraftRuns') == 1, 'a new scan works it out again')
X('AF_NS.Farm.Crafts = RealCrafts')
# Old Farm list users still work: the quick scan list and name preload take the top of Gather.
ql = L('AF_NS.UI.QuickList()')
ok(2589 in [ql[i] for i in range(1, len(ql) + 1)], 'quick scan list still includes good Gather items')
X('Click(AuctionForeverFrame.FarmBar.Gather); AuctionForeverFrame:Hide()')
# Quick scan near misses: steady sellers that aren't flips but came within 10 points of the return they need.
X("""NearData = AuctionForeverData
  local F = { "low", "qty", "med", "hi", "med24", "medAll", "perHour", "medHour", "hoursSeen", "hoursWithSales", "sales",
    "sellThrough", "qtyDayAgo", "newHour", "lows", "lowHi24", "ladder" }
  local function It(Next) return { 1000, 210, 1400, 1500, 1400, 1400, 40, 40, 72, 70, 500, 1, 280, nil, nil, nil, { { 1000, 10 }, { Next, 100 } } } end
  AuctionForeverData = { v = 1, time = os.time(), hours = 72, fields = F, names = {},
    items = { [990001] = It(1184), [990002] = It(1000), [990003] = It(1206) },
    info = { [990001] = { 1, 1, 1 }, [990002] = { 1, 1, 1 }, [990003] = { 1, 1, 1 } } }
  AF_NS.Scan.Version = AF_NS.Scan.Version + 1; Money = 2000000""")
nm = [(L(f'AF_NS.UI.NearMisses()[{i}].id'), L(f'AF_NS.UI.NearMisses()[{i}].gap')) for i in range(1, int(L('#AF_NS.UI.NearMisses()')) + 1)]
fl = [L(f'AF_NS.UI.FlipTargets()[{i}].id') for i in range(1, int(L('#AF_NS.UI.FlipTargets()')) + 1)]
ok([i for i, g in nm] == [990001] and abs(nm[0][1] - 0.0099) < 0.001, f'near misses: the 9% return item (needs 10%), 1 point short: {nm}')
ok(990003 in fl and 990003 not in [i for i, g in nm], f'a real flip is a flip target, not a near miss ({fl})')
X("""SaveFarm0, SaveCont0 = AF_NS.UI.FarmRows, C_Container
  AF_NS.UI.FarmRows = function() return {} end; C_Container = { GetContainerNumSlots = function() return 0 end } -- only the flip and near-miss groups
  QL0 = AF_NS.UI.QuickList()
  AF_NS.UI.FarmRows, C_Container = SaveFarm0, SaveCont0""")
ql = [L(f'QL0[{i}]') for i in range(1, int(L('#QL0')) + 1)]
ok(ql == [990003, 990001], f'quick list: the flip, then the near miss; the far miss left out, nothing twice: {ql}')
X("""AuctionForeverData = NearData; AF_NS.Scan.Version = AF_NS.Scan.Version + 1
  SaveFR, SaveFarm, SaveNM, SaveCont = AF_NS.UI.FlipRows, AF_NS.UI.FarmRows, AF_NS.UI.NearMisses, C_Container
  AF_NS.UI.FlipRows = function() local t = {} for i = 1, 20 do t[i] = { id = 700000 + i } end return t end
  AF_NS.UI.FarmRows = function() local t = {} for i = 1, 20 do t[i] = { id = 710000 + i, status = "good" } end return t end
  AF_NS.UI.NearMisses = function() local t = {} for i = 1, 20 do t[i] = { id = 720000 + i, gap = i / 100 } end return t end
  local Info = AF_NS.Core.Info
  SaveInfo = Info
  AF_NS.Core.Info = function(id) if id > 730000 and id < 730100 then return { id = id } end return Info(id) end
  SaveSt = AF_NS.Core.Status; AF_NS.Core.Status = function() return "warming up" end -- fill the warming-up group too
  C_Container = { GetContainerNumSlots = function(b) return b == 0 and 20 or 0 end, GetContainerItemInfo = function(b, s) return { itemID = 730000 + s } end }
  QL = AF_NS.UI.QuickList()
  AF_NS.UI.FlipRows, AF_NS.UI.FarmRows, AF_NS.UI.NearMisses, C_Container, AF_NS.Core.Info = SaveFR, SaveFarm, SaveNM, SaveCont, SaveInfo
  AF_NS.Core.Status = SaveSt""")
q = [L(f'QL[{i}]') for i in range(1, int(L('#QL')) + 1)]
near_q = [i for i in q if 720000 < i < 720100]
ok(len(q) == 55 and near_q == list(range(720001, 720011)) and len(q) - len(near_q) == 45 and q[:15] == list(range(700001, 700016)),
   f'quick list cap 55: the other groups keep their 45, the 10 closest near misses after them ({len(q)}, {len(near_q)})')
X("""AuctionForeverData, AuctionForeverDB, AF_NS.Scan.Version = SavedData, SavedDB, SavedVer + 100
  C_Item.GetItemInfoInstant = RealInstant; C_SkillInfo = RealSkill; C_Item.GetItemInfo = BaseGII""")
# Shopping list text: AH lines show the most to pay each and the total at listed prices, vendor lines the vendor
# price, bags lines "-"; the compact line names each source and stops at 3 entries with "+N more".
X("""SL = AF_NS.UI.ShoppingLine
  SL1 = SL({ id = 2320, qty = 20, source = "Vendor", each = 10, cost = 200 })
  SL2 = SL({ id = 4306, qty = 40, source = "AH", upTo = 281, cost = 10500 })
  SL3 = SL({ id = 4306, qty = 4, source = "Owned", cost = 0 })
  ML = AF_NS.UI.MatsLine({ { id = 4306, qty = 40, source = "AH", upTo = 281 }, { id = 2320, qty = 20, source = "Vendor", each = 10 } })
  ML5 = AF_NS.UI.MatsLine({ { id = 1, qty = 1, source = "Owned" }, { id = 2, qty = 1, source = "AH", upTo = 5 }, { id = 3, qty = 1, source = "Vendor" },
    { id = 4, qty = 1, source = "AH", upTo = 5 }, { id = 5, qty = 1, source = "AH", upTo = 5 } })""")
n2320, n4306 = plain(L('(AF_NS.UI.ShoppingLine({ id = 2320, qty = 1, source = "Owned" }))')).split(' x ')[1].split('  ')[0], None
sl1, sl2, sl3, ml, ml5 = (plain(L(v)) for v in ('SL1', 'SL2', 'SL3', 'ML', 'ML5'))
n4306 = sl3.split(' x ')[1].split('  ')[0]
ok(sl1 == f'20 x {n2320}  Vendor  10c  (2s 00c)' and sl2 == f'40 x {n4306}  AH  up to 2s 81c  (1g 05s 00c)' and sl3 == f'4 x {n4306}  Owned  -'
   and 'INV_Misc_Coin_02' in str(L('SL2')) and 'Inv_misc_bag_08' in str(L('SL1')) and 'UI-CheckBox-Check' in str(L('SL3')) and '|cff1eff00Owned|r' in str(L('SL3')),
   f'shopping lines: {sl1!r} / {sl2!r} / {sl3!r}')
ok(ml == f'Mats: 40 {n4306} (AH, up to 2s 81c), 20 {n2320} (Vendor)' and ml5 == 'Mats: 1 Item 2 (AH, up to 5c), 1 Item 4 (AH, up to 5c), 1 Item 5 (AH, up to 5c), +2 more',
   f'compact Mats line: {ml!r} / {ml5!r}')
undef = sorted(set(str(v) for v in L('UndefinedReads').values()))
ok(not undef, 'no reads of undefined globals from add-on code: ' + (', '.join(undef) or 'none'))
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
