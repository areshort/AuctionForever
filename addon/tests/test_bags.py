"""Offline test of Bags.lua (Baganator bag icons and junk source) with a fake WoW API (wowmock.lua) and a fake
Baganator. Proves the decisions and the one-coin rule; not that it looks right in game.
Run: venv python -I test_bags.py"""
import os, re, sys
from lupa.luajit21 import LuaRuntime

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HERE), 'AuctionForever')
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute('function __Load(src, name, ...) local f = assert(loadstring(src, name)); return f(...) end')


def run(path, *args):
    lua.globals().__Load(open(path, encoding='utf-8').read(), os.path.basename(path), *args)


run(os.path.join(HERE, 'wowmock.lua'))
lua.execute("""
-- Items: { name, quality, vendor price, class }. Auction data: 9001/9004/9005 sell for 1g on the AH.
ITEMS = {
  [9001] = { "Silk Thing", 1, 5, 7 },      -- AH pays far more than the vendor: Auction
  [9002] = { "Plain Thing", 1, 50, 7 },    -- no AH data, vendor pays: Vendor
  [9004] = { "Quest Thing", 1, 5, 12 },    -- quest item: never marked
  [9005] = { "Bound Thing", 1, 5, 4 },     -- soulbound copies: never marked
  [9006] = { "Grey Thing", 0, 50, 15 },    -- poor quality, vendor pays: Vendor
  [9007] = { "Free Thing", 1, 0, 7 },      -- no price anywhere: nothing
}
C_Item.GetItemInfo = function(id)
  if type(id) == "string" then id = tonumber(id:match("item:(%d+)")) end
  local I = ITEMS[id]
  if not I then return nil end
  return I[1], "item:" .. id, I[2], nil, nil, nil, nil, nil, nil, nil, I[3]
end
C_Item.GetItemInfoInstant = function(id)
  if type(id) == "string" then id = tonumber(id:match("item:(%d+)")) end
  local I = ITEMS[id]
  return id, "Thing", "", "", 134400, I and I[4] or 7, 0
end
AuctionForeverData = { v = 1, house = 110, time = os.time(), hours = 5, fields = { "low", "qty", "med" }, info = {},
  items = { [9001] = { 10000, 1, 10000 }, [9004] = { 10000, 1, 10000 }, [9005] = { 10000, 1, 10000 } } }
PRECISE, PRECISE_STEP = 0, 0
function GetTimePreciseSec() PRECISE = PRECISE + PRECISE_STEP return PRECISE end
-- Fake Baganator: records the widget, junk source and refresh requests.
WIDGETS, JUNK, REFRESHES, JUNK_SOURCE = {}, {}, 0, "poor_quality"
Baganator = { API = {
  RegisterCornerWidget = function(label, id, onUpdate, onInit, pos) assert(not WIDGETS[id]) WIDGETS[id] = { label = label, onUpdate = onUpdate, onInit = onInit, pos = pos } end,
  RegisterJunkPlugin = function(label, id, cb) JUNK[id] = { label = label, cb = cb } end,
  IsJunkPluginActive = function(id) return JUNK_SOURCE == id end,
  IsCornerWidgetActive = function(id) return id ~= "junk" or JUNK_ICON_ON ~= false end,
  RequestItemButtonsRefresh = function() REFRESHES = REFRESHES + 1 end,
} }
-- What Baganator's item button does: onUpdate(icon, details). Returns "auction", "coin", nil (hidden) or "?".
function Icon(id, extra)
  local icon = {}
  function icon:SetTexture(p) self.path = p end
  function icon:SetTexCoord(...) self.coords = { ... } end
  function icon:SetAtlas(a) self.path = "atlas:" .. a end
  local d = { itemID = id, itemLink = "|cffffffff|Hitem:" .. id .. "::::|h[x]|h|r", quality = ITEMS[id] and ITEMS[id][2] or 1 }
  for k, v in pairs(extra or {}) do d[k] = v end
  if not AF_NS.Bags.UpdateIcon(icon, d) then return nil end
  local function Is(C) if type(C) == "table" and C.atlas then return icon.path == "atlas:" .. C.atlas end
    if type(C) == "table" then return icon.path == C[1] and icon.coords[2] == C[3] end
    return icon.path == C end
  local Pick = function(K) local n = AuctionForeverDB.icons and AuctionForeverDB.icons[K] or AF_NS.Bags.DEFAULT[K] return AF_NS.Bags.ICONS[K][n] end
  if Is(Pick("auction")) then return "auction" end
  if Is(Pick("vendor")) then return "coin" end
  return "?"
end
function Junk(id, slot) return JUNK.auctionforever.cb(0, slot or 1, id, id and ("|cffffffff|Hitem:" .. id .. "::::|h[x]|h|r") or nil) end
function Tick() for _, f in ipairs(AllFramesForTest) do local s = f._scripts.OnUpdate if s then s(f, 0.016) end end end
""")
lua.execute("""
UndefinedReads = {}
local Allowed = { AuctionForeverDB = true, AuctionForeverChar = true, AuctionForeverData = true }
setmetatable(_G, { __index = function(_, k)
  if not Allowed[k] then
    local Info = debug.getinfo(2, "S")
    local Src = Info and Info.source or "?"
    if Src:find("Bags.lua") or Src:find("UI.lua") then UndefinedReads[#UndefinedReads + 1] = Src .. ": " .. tostring(k) end
  end
end })
AF_NS = {}
""")
ns = lua.eval('AF_NS')
TOC = [l.strip() for l in open(os.path.join(ADDON, 'AuctionForever.toc'), encoding='utf-8') if l.strip() and not l.startswith('#')]
for f in TOC:
    if f != 'AuctionForeverData.lua':
        run(os.path.join(ADDON, f), 'AuctionForever', ns)

fails = 0


def ok(c, m):
    global fails
    print(('PASS ' if c else 'FAIL ') + m)
    fails += 0 if c else 1


L, X = lua.eval, lua.execute
X('FireEvent("PLAYER_LOGIN")')
has_widget = L('WIDGETS.auctionforever ~= nil')
ok(has_widget and L('JUNK.auctionforever ~= nil'), 'Bags.lua in the .toc: widget and junk source registered at login')
if not has_widget:
    print('FAILED: %d (nothing more to test without the widget)' % (fails))
    sys.exit(1)

w = 'WIDGETS.auctionforever'
ok(L(f'{w}.label') == 'AuctionForever' and L(f'{w}.pos.corner') == 'top_right' and L(f'{w}.pos.priority') == 1, 'own widget "AuctionForever", top right (where the old GUF sell icon was)')
X(f'INIT = {w}.onInit({{ CreateTexture = function() return {{ SetSize = function(self, a, b) self.w, self.h = a, b end }} end }})')
ok(L('INIT.w == 15 and INIT.h == 15'), 'icon is 15x15')
ok(L('JUNK.auctionforever.label') == 'AuctionForever', 'Baganator junk source named "AuctionForever"')

# Same recommendation as the tooltip's "Rec" line.
ok(L('(AF_NS.UI.BagAdvice(9001))') == 'Auction' and L('(AF_NS.UI.BagAdvice(9002))') == 'Vendor' and L('(AF_NS.UI.BagAdvice(9007))') is None, 'BagAdvice: Auction / Vendor / nil')
for i in (9001, 9002, 9006):
    tip = ' '.join(str(v) for v in L(f'(function() local t = {{}} for _, l in ipairs(AF_NS.UI.TooltipLines({i})) do if l[1] == "Rec" then t[1] = l[2] end end return t[1] end)()') .split())
    ok(L(f'(AF_NS.UI.BagAdvice({i}))') in tip, f'item {i}: bag advice matches the tooltip Rec line ({tip})')

# AF draws both icons itself: the chosen purse for vendor items, the chosen auction icon.
ok(L('Icon(9001)') == 'auction', 'Rec Auction: auction icon')
ok(L('Icon(9002)') == 'coin', 'Rec Vendor: the vendor (purse) icon')
ok(L('Icon(9006)') is None, "grey vendor item: no second icon (Baganator's junk icon, now the purse, shows it)")
ok(L('Icon(9007)') is None, 'no recommendation: no icon')
ok(L('Icon(9004)') is None, 'quest item: no icon even with an AH price')
ok(L('Icon(9005, { isBound = true })') is None and L('Icon(9005)') == 'auction', 'soulbound copy: no icon (unbound copy: auction)')

# AF is Baganator's junk source: vendor items get Baganator's junk icon (the purse), not a second one from AF.
X('JUNK_SOURCE = "auctionforever"')
ok(L('Icon(9002)') is None and L('Icon(9001)') == 'auction', 'AF is the junk source: no second vendor icon; auction icon still drawn')
X('JUNK_SOURCE = "poor_quality"')
# Baganator's junk coin is replaced with the chosen vendor icon, and follows a new choice.
X('''JB = CreateFrame("Button"); JB.JunkIcon = { SetTexture = function(s, p) s.path = p end, SetTexCoord = function() end,
    SetAtlas = function(s, a) s.path = "atlas:" .. a end, SetSize = function() end }
  WIDGETS.auctionforever.onInit(JB)''')
ok(L('JB.JunkIcon.path') == 'atlas:' + L('AF_NS.Bags.ICONS.vendor[6].atlas'), "Baganator's junk coin shows the vendor icon instead (default 6)")
X('AF_NS.Bags.IconCommand("icon vendor 2")')
ok(L('JB.JunkIcon.path') == L('AF_NS.Bags.ICONS.vendor[2]'), 'picking another vendor icon updates the junk icon too')
X('AuctionForeverDB.icons = nil')
# Two widgets: vendor top left, auction top right; each draws only its own kind.
v = 'WIDGETS.auctionforever_vendor'
ok(L(f'{v} ~= nil') and L(f'{v}.pos.corner') == 'top_left' and L(f'{v}.pos.priority') == 1, 'vendor icon: its own widget, top left')
X('function W(id, item, extra) local icon = { SetTexture = function(s, p) s.path = p end, SetTexCoord = function() end, SetAtlas = function(s, a) s.path = "atlas:" .. a end } local d = { itemID = item, itemLink = "|cffffffff|Hitem:" .. item .. "::::|h[x]|h|r", quality = ITEMS[item] and ITEMS[item][2] or 1 } for k, x in pairs(extra or {}) do d[k] = x end return WIDGETS[id].onUpdate(icon, d) and icon.path or nil end')
ok(L('W("auctionforever", 9001)') is not None and L('W("auctionforever_vendor", 9001)') is None, 'auction item: icon only in the top right')
ok(L('W("auctionforever", 9002)') is None and L('W("auctionforever_vendor", 9002)') is not None, 'vendor item: icon only in the top left')
X('JUNK_SOURCE = "auctionforever"')
ok(L('W("auctionforever_vendor", 9002)') is None, "AF is the junk source and Baganator's junk icon is on: it shows the vendor icon, no second one")
X('JUNK_ICON_ON = false')
ok(L('W("auctionforever_vendor", 9002)') is not None and L('W("auctionforever_vendor", 9006)') is not None, "Baganator's junk icon turned off: AF draws the vendor icon itself")
X('JUNK_ICON_ON = nil; JUNK_SOURCE = "poor_quality"')
ok(L('AF_NS.Bags.DEFAULT.vendor') == 6 and L('AF_NS.Bags.DEFAULT.auction') == 2, 'defaults: vendor 6, auction 2 (your picks)')
X('AuctionForeverDB.icons = { vendor = 2 }; AuctionForeverDB.iconsVersion = nil')
ok(L('W("auctionforever_vendor", 9002)') == 'atlas:' + L('AF_NS.Bags.ICONS.vendor[6].atlas') and L('AuctionForeverDB.icons') is None,
   'a pick saved before the new defaults is dropped once: vendor 6 shows')
X('AF_NS.Bags.IconCommand("icon vendor 3")')
ok(L('W("auctionforever_vendor", 9002)') == L('AF_NS.Bags.ICONS.vendor[3]'), 'a pick made now is kept')
X('AuctionForeverDB.icons = nil')
# Picking icons: /af icon vendor 3 saves the choice and redraws the bags.
X('AF_NS.Bags.IconCommand("icon vendor 3"); AF_NS.Bags.IconCommand("icon auction 2")')
ok(L('AuctionForeverDB.icons.vendor') == 3 and L('AuctionForeverDB.icons.auction') == 2 and L('Icon(9002)') == 'coin' and L('Icon(9001)') == 'auction',
   'picked icons are drawn (vendor 3, auction 2 = an atlas)')
X('AF_NS.Bags.IconCommand("icon vendor 99"); AF_NS.Bags.IconCommand("icons")')
ok(L('AuctionForeverDB.icons.vendor') == 3, 'a number that is not a choice: ignored (lists the choices)')
X('AuctionForeverDB.icons = nil')
ok(L('Icon(9002)') == 'coin' and L('Icon(9001)') == 'auction', 'defaults: first choice of each')

# Junk callback.
ok(L('Junk(9002)') is True and L('Junk(9006)') is True, 'junk source: vendor items are junk (greys too)')
ok(L('Junk(9001)') is False, 'auction item: not junk (the sell button must not vendor it)')
ok(L('Junk(9004)') is False and L('Junk(9007)') is False, 'quest item / no price: not junk')
X('ItemLocation = { CreateFromBagAndSlot = function(_, b, s) return { b = b, s = s } end }; C_Item.IsBound = function(loc) return loc.s == 3 end')
X('ITEMS[9008] = { "Bound Plain", 1, 50, 4 }')
ok(L('Junk(9008, 3)') is False and L('Junk(9008, 4)') is True, 'soulbound bag slot: not junk; unbound: junk')
ok(L('Junk(nil)') is False, 'empty slot: not junk')
X('C_Item.IsBound = nil; ItemLocation = nil')

# Keep list.
X('SlashCmdList.AUCTIONFOREVER("keep |cffffffff|Hitem:9002::::|h[Plain Thing]|h|r")')
ok(L('AuctionForeverDB.keep[9002] == true') and L('Icon(9002)') is None and L('Junk(9002)') is False, '/af keep [link]: no icon, not junk')
ok('never be marked' in (L('LastPrint') or ''), 'said so: ' + str(L('LastPrint')))
X('SlashCmdList.AUCTIONFOREVER("keep")')
ok('Plain Thing' in (L('LastPrint') or ''), '/af keep alone lists it: ' + str(L('LastPrint')))
X('SlashCmdList.AUCTIONFOREVER("keep item:9002")')
ok(L('AuctionForeverDB.keep[9002] == nil') and L('Icon(9002)') == 'coin', 'again: undone, coin back')

# New auction data: cache dropped and bags redrawn.
X('AuctionForeverData.items[9002] = { 100000, 1, 100000 }')
ok(L('Icon(9002)') == 'coin', 'cached until the data changes')
X('BEFORE = REFRESHES; AF_NS.UI.ScanDone()')
ok(L('REFRESHES > BEFORE') and L('Icon(9002)') == 'auction', 'scan done: bags refreshed, new advice (auction)')
X('AuctionForeverData.items[9002] = nil; AF_NS.Scan.Version = AF_NS.Scan.Version + 1')
ok(L('Icon(9002)') == 'coin', 'auction data version changed (e.g. a purchase): worked out again')

# Frame budget: items over it wait for later frames, then the bags are redrawn.
X('PRECISE_STEP = 0.01; AuctionForeverData.items[9010] = { 10000, 1, 10000 }; ITEMS[9010] = { "A", 1, 5, 7 }; ITEMS[9011] = { "B", 1, 50, 7 }')
X('A1, A2 = Icon(9010), Icon(9011)')
ok(L('A1') == 'auction' and L('A2') is None, 'over the time budget: second item waits')
X('BEFORE = REFRESHES; for i = 1, 30 do Tick() end')
ok(L('REFRESHES > BEFORE') and L('Icon(9011)') == 'coin', 'worked out on a later frame, bags refreshed')
X('PRECISE_STEP = 0')

ok(L('#UndefinedReads') == 0, 'no undefined globals read: ' + ', '.join(L('UndefinedReads').values()))
non_ascii = [n for n, line in enumerate(open(os.path.join(ADDON, 'Bags.lua'), encoding='utf-8'), 1) if re.search(r'[^\x00-\x7f]', line)]
ok(not non_ascii, 'Bags.lua is ASCII only')
print('FAILED: %d' % fails if fails else 'ALL PASSED')
sys.exit(1 if fails else 0)
