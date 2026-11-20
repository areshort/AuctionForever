-- Minimal fake WoW API for offline tests: frames accept any method call; scripts and events are recorded.
local Clock = 1000
function GetTime() return Clock end
function AdvanceTime(s) Clock = Clock + s end
time = os.time; date = os.date
local AllFrames = {}
AllFramesForTest = AllFrames
local Methods = {}
local FrameMT = { __index = function(t, k)
	if Methods[k] then return Methods[k] end
	return function() return nil end
end }
local function NewObj(kind, name)
	local f = setmetatable({ _kind = kind, _scripts = {}, _events = {}, _shown = true, _text = "", _points = {} }, FrameMT)
	if name then _G[name] = f end
	AllFrames[#AllFrames + 1] = f
	return f
end
function Methods:SetScript(k, fn) self._scripts[k] = fn end
function Methods:GetScript(k) return self._scripts[k] end
function Methods:RegisterEvent(e) self._events[e] = true end
function Methods:UnregisterEvent(e) self._events[e] = nil end
function Methods:Show() local was = self._shown; self._shown = true; if not was and self._scripts.OnShow then self._scripts.OnShow(self) end end
function Methods:Hide() self._shown = false end
function Methods:SetShown(v) if v then self:Show() else self:Hide() end end
function Methods:IsShown() return self._shown end
function Methods:SetText(t) self._text = t end
function Methods:GetText() return self._text end
function Methods:SetTitle(t) self._title = t end
function Methods:SetID(i) self._id = i end
function Methods:GetID() return self._id end
function Methods:CreateFontString() return NewObj("FontString") end
function Methods:CreateTexture() return NewObj("Texture") end
function Methods:SetPoint(...) self._points[#self._points + 1] = { ... } end
function Methods:GetPoint() return "CENTER", nil, "CENTER", 10, 20 end
function Methods:GetWidth() return 140 end
function Methods:GetCenter() return 500, 500 end
function Methods:GetEffectiveScale() return 1 end
function CreateFrame(kind, name, parent, template)
	local f = NewObj(kind, name)
	f._parent = parent
	if template == "ButtonFrameTemplate" then f.Inset = NewObj("Frame") end
	if template == "PanelTabButtonTemplate" and parent then rawset(parent, "Tabs", rawget(parent, "Tabs") or {}); table.insert(rawget(parent, "Tabs"), f) end
	return f
end
function FireEvent(e, ...)
	for _, f in ipairs(AllFrames) do
		if f._events[e] and f._scripts.OnEvent then f._scripts.OnEvent(f, e, ...) end
	end
end
UIParent = NewObj("Frame"); Minimap = NewObj("Frame")
GameTooltip = NewObj("GameTooltip"); ItemRefTooltip = NewObj("GameTooltip")
UISpecialFrames = {}; StaticPopupDialogs = {}; SlashCmdList = {}
function StaticPopup_Show(n) LastPopup = n end
function tinsert(t, v) table.insert(t, v) end
function IsShiftKeyDown() return false end
function GetCursorPosition() return 0, 0 end
function ButtonFrameTemplate_HidePortrait() end
function PanelTemplates_SetNumTabs(f, n) f.numTabs = n end
function PanelTemplates_SetTab(f, i) f.selectedTab = i end
function PanelTemplates_TabResize() end
Money = 2000000
function GetMoney() return Money end
function GetRealZoneText() return "Arathi Highlands" end
Timers = {}
C_Timer = { After = function(_, fn) table.insert(Timers, fn) end }
function RunTimers() local T = Timers; Timers = {}; for _, fn in ipairs(T) do fn() end end
LOOT_ITEM_SELF = "You receive loot: %s."
LOOT_ITEM_SELF_MULTIPLE = "You receive loot: %sx%d."
GOLD_AMOUNT = "%d Gold"; SILVER_AMOUNT = "%d Silver"; COPPER_AMOUNT = "%d Copper"
ITEM_QUALITY_COLORS = { [1] = { hex = "|cffffffff" } }
-- Items: everything is a stackable Trade Good named "Item <id>", vendor 5c.
C_Item = {
	GetItemInfo = function(id) return "Item " .. id, nil, 1, nil, nil, nil, nil, nil, nil, nil, 5 end,
	GetItemInfoInstant = function(id) return id, "Trade Goods", "", "", 134400, 7, 0 end,
	GetItemMaxStackSizeByID = function() return 20 end,
	RequestLoadItemDataByID = function() end,
}
TooltipPostCalls = {}
TooltipDataProcessor = { AddTooltipPostCall = function(_, fn) TooltipPostCalls[#TooltipPostCalls + 1] = fn end }
Enum = { TooltipDataType = { Item = 0 } }
TipLines = {}
function GameTooltip:AddLine(t) table.insert(TipLines, t) end
function GameTooltip:AddDoubleLine(a, b) table.insert(TipLines, a .. ": " .. b) end

function print(...) LastPrint = table.concat({ tostring((...)) }, " ") end
function Methods:Disable() self._disabled = true end
function Methods:Enable() self._disabled = false end

-- Auction house tab support: children, hooks, positions, tab visuals.
local OrigCreate = CreateFrame
function CreateFrame(kind, name, parent, template)
	local f = OrigCreate(kind, name, parent, template)
	f._hooks = {}
	if parent then rawset(parent, "_children", rawget(parent, "_children") or {}); table.insert(rawget(parent, "_children"), f) end
	return f
end
function Methods:GetChildren() return unpack(rawget(self, "_children") or {}) end
function Methods:GetObjectType() return self._kind end
function Methods:GetTop() return rawget(self, "_top") end
function Methods:GetLeft() return rawget(self, "_left") end
function Methods:GetRight() return rawget(self, "_right") end
function Methods:GetFrameLevel() return 1 end
function Methods:SetEnabled(v) self._disabled = not v end
function Methods:HookScript(k, fn) self._hooks[k] = self._hooks[k] or {}; table.insert(self._hooks[k], fn) end
function Methods:ClearAllPoints() self._points = {} end
function Click(f, ...)
	local s = f._scripts.OnClick
	if s then s(f, ...) end
	for _, h in ipairs((f._hooks and f._hooks.OnClick) or {}) do h(f, ...) end
end
function hooksecurefunc(t, name, fn)
	local orig = t[name]
	t[name] = function(...) local r = orig(...); fn(...); return r end
end
function PanelTemplates_SelectTab(t) t._selected = true end
function PanelTemplates_DeselectTab(t) t._selected = false end
function PlaySound() end
SOUNDKIT = {}
C_Container = {
	GetContainerNumSlots = function(bag) return bag == 0 and 2 or 0 end,
	GetContainerItemInfo = function(bag, slot)
		if bag ~= 0 then return nil end
		if slot == 1 then return { itemID = 2589, isBound = false } end
		return { itemID = 999999, isBound = true }
	end,
}
YES = "Yes"; NO = "No"
