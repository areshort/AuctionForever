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
print('FAILED' if fails else 'ALL PASSED', fails)
sys.exit(1 if fails else 0)
