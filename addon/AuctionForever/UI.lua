-- AuctionForever window, minimap button, tooltips and farming sessions.
local _, AF = ...
local Core = AF.Core
local L = {}

local ROWS = 14
local ROW_H = 22
local TABS = { "Farm", "Flip", "Sessions" }

-- Saved data -----------------------------------------------------------------------------------------------------
local function Char()
	AuctionForeverChar = AuctionForeverChar or {}
	local C = AuctionForeverChar
	C.sessions = C.sessions or {}
	return C
end
local function Account()
	AuctionForeverDB = AuctionForeverDB or {}
	AuctionForeverDB.minimapAngle = AuctionForeverDB.minimapAngle or 220
	return AuctionForeverDB
end

-- Item helpers ---------------------------------------------------------------------------------------------------
local Pending = {}
local function NameCache()
	AuctionForeverDB = AuctionForeverDB or {}
	AuctionForeverDB.names = AuctionForeverDB.names or {}
	return AuctionForeverDB.names
end
local function ItemName(id)
	local Name, _, Quality = C_Item.GetItemInfo(id)
	local Cache = NameCache()
	if Name then
		local C = Cache[id]
		if not C or C[1] ~= Name or C[2] ~= Quality then Cache[id] = { Name, Quality } end
		return Name, Quality
	end
	if not Pending[id] then
		Pending[id] = true
		if C_Item.RequestLoadItemDataByID then C_Item.RequestLoadItemDataByID(id) end
	end
	local C = Cache[id]
	if C then return C[1], C[2] end
	return "|cff808080loading...|r", 1
end
-- Ask the server for names the lists will need, a few at a time, so they're ready when the window opens.
function L.Preload(Ids)
	local i = 0
	local function Batch()
		local Done = 0
		while i < #Ids and Done < 20 do
			i = i + 1
			local id = Ids[i]
			if not C_Item.GetItemInfo(id) and not Pending[id] then
				Pending[id] = true
				if C_Item.RequestLoadItemDataByID then C_Item.RequestLoadItemDataByID(id) end
				Done = Done + 1
			end
		end
		if i < #Ids then C_Timer.After(0.2, Batch) end
	end
	Batch()
end
local function Icon(id)
	local _, _, _, _, Tex = C_Item.GetItemInfoInstant(id)
	return Tex or 134400
end
local function IsReagent(id)
	local _, _, _, _, _, ClassID = C_Item.GetItemInfoInstant(id)
	return ClassID == 7 -- Trade Goods
end
local function Stacks(id)
	local Max = C_Item.GetItemMaxStackSizeByID and C_Item.GetItemMaxStackSizeByID(id)
	return (Max or 1) > 1
end
local function Vendor(id)
	local _, _, _, _, _, _, _, _, _, _, Sell = C_Item.GetItemInfo(id)
	return Sell or 0
end
local STATUS_COLOR = { early = "|cffffd100", good = "|cff1eff00", ["warming up"] = "|cff9d9d9d", slow = "|cffff8040", flooded = "|cffff8040", falling = "|cffff8040", ["no data"] = "|cff9d9d9d" }
local function StatusText(S) return (STATUS_COLOR[S] or "|cffffffff") .. S .. "|r" end

-- Lists ----------------------------------------------------------------------------------------------------------
function L.FarmRows()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return {} end
	local Good, Other = {}, {}
	for id in pairs(D.items) do
		if IsReagent(id) then
			local I = Core.Info(id)
			local S = Core.Status(I)
			local Row = { id = id, info = I, status = S, value = Core.ValuePerDay(I) }
			Row.price = Core.Market(I) or 0
			if S == "good" then Good[#Good + 1] = Row elseif S ~= "no data" then Other[#Other + 1] = Row end
		end
	end
	table.sort(Good, function(a, b) return a.value > b.value end)
	-- Not proven yet (warming up, slow...): best known sellers first, then by price.
	table.sort(Other, function(a, b) if a.value ~= b.value then return a.value > b.value end return a.price > b.price end)
	local Out = {}
	for i = 1, math.min(#Good, 60) do Out[#Out + 1] = Good[i] end
	for i = 1, math.min(#Other, 20) do Out[#Out + 1] = Other[i] end
	return Out
end

function L.FlipRows()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return {} end
	local Budget = Core.Budget(GetMoney())
	local Out = {}
	if Budget <= 0 then return Out end
	for id in pairs(D.items) do
		if Stacks(id) then
			local I = Core.Info(id)
			local F = Core.Flip(I, Budget)
			if F then Out[#Out + 1] = { id = id, info = I, flip = F } end
		end
	end
	table.sort(Out, function(a, b) return a.flip.profit > b.flip.profit end)
	return Out
end

-- Why the Flip list is empty, in one line.
function L.FlipEmptyReason()
	if Core.Budget(GetMoney()) <= 0 then return "No flip budget: you need more than 1 gold." end
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return "No auction data yet: scan at the auction house." end
	local N = {}
	for id in pairs(D.items) do
		local S = Core.Status(Core.Info(id))
		N[S] = (N[S] or 0) + 1
	end
	if (N.good or 0) == 0 then
		return string.format("No flips yet: no item has enough measured sales (%d warming up).\nScan at the auction house (AuctionForever tab), then again 15+ min later.", N["warming up"] or 0)
	end
	return string.format("%d steady sellers, but none has a listing cheap enough to\nflip for 10s+ profit right now. Quick Scan for fresh prices.", N.good)
end

-- Items a quick scan looks up: flip candidates, sellable bag items, top farm reagents, fast sellers still warming up.
function L.QuickList()
	local Out, Seen = {}, {}
	local function Add(id, Cap, Count)
		if Count[1] >= Cap or Seen[id] or #Out >= 45 then return end
		Seen[id] = true; Out[#Out + 1] = id; Count[1] = Count[1] + 1
	end
	local C = { 0 }
	for _, R in ipairs(L.FlipRows()) do Add(R.id, 15, C) end
	C = { 0 }
	local NumSlots = C_Container and C_Container.GetContainerNumSlots
	if NumSlots then
		for Bag = 0, 4 do
			for Slot = 1, NumSlots(Bag) or 0 do
				local Info = C_Container.GetContainerItemInfo(Bag, Slot)
				if Info and Info.itemID and not Info.isBound and Core.Info(Info.itemID) then Add(Info.itemID, 15, C) end
			end
		end
	end
	C = { 0 }
	for _, R in ipairs(L.FarmRows()) do if R.status == "good" then Add(R.id, 10, C) end end
	C = { 0 }
	local D = AuctionForeverData
	if type(D) == "table" and type(D.items) == "table" then
		local Warm = {}
		for id in pairs(D.items) do
			local I = Core.Info(id)
			if Core.Status(I) == "warming up" and (I.qty or 0) > 0 and Stacks(id) then Warm[#Warm + 1] = { id, (I.qty or 0) * (Core.Market(I) or 0) } end
		end
		table.sort(Warm, function(x, y) return x[2] > y[2] end)
		for _, W in ipairs(Warm) do Add(W[1], 10, C) end
	end
	return Out
end

-- Farming sessions -----------------------------------------------------------------------------------------------
local Session = {}
AF.Session = Session

function Session.Current()
	local C = Char()
	return C.current
end
function Session.New()
	local C = Char()
	if C.current and (C.current.secs or 0) > 0 then table.insert(C.sessions, 1, C.current) end
	C.current = { start = time(), secs = 0, items = {}, money = 0, zone = GetRealZoneText and GetRealZoneText() or "" }
	return C.current
end
function Session.Start()
	local S = Session.Current() or Session.New()
	if not S.runningSince then S.runningSince = GetTime() end
	if (S.zone or "") == "" and GetRealZoneText then S.zone = GetRealZoneText() end
end
function Session.Stop()
	local S = Session.Current()
	if S and S.runningSince then
		S.secs = (S.secs or 0) + (GetTime() - S.runningSince)
		S.runningSince = nil
	end
end
function Session.Running()
	local S = Session.Current()
	return S and S.runningSince ~= nil
end
function Session.Seconds(S)
	if not S then return 0 end
	return (S.secs or 0) + (S.runningSince and (GetTime() - S.runningSince) or 0)
end
function Session.Clear()
	local C = Char()
	C.sessions, C.current = {}, nil
end
-- Gold a session's loot would bring now (items at what they'd sell for, after the cut) plus money looted.
function Session.Value(S)
	local V = S.money or 0
	for id, N in pairs(S.items or {}) do
		V = V + Core.LootValue(Core.Info(id), N, Vendor(id))
	end
	return V
end
function Session.AddItem(id, N)
	local S = Session.Current()
	if not (S and S.runningSince) then return end
	S.items[id] = (S.items[id] or 0) + N
end
function Session.AddMoney(C)
	local S = Session.Current()
	if not (S and S.runningSince) then return end
	S.money = (S.money or 0) + C
end
-- Called at logout: a running clock is stopped so time offline doesn't count.
function Session.Pause() Session.Stop() end

-- Loot and money messages ("You receive loot: %s." / "You receive loot: %sx%d." / "You loot 5 Silver").
local function Pattern(Fmt)
	local P = Fmt:gsub("([%(%)%.%%%+%-%*%?%[%]%^%$])", "%%%1")
	P = P:gsub("%%%%s", "(.+)"):gsub("%%%%d", "(%%d+)")
	return "^" .. P .. "$"
end
L.LootPatterns = {}
L.MoneyParts = {}
function L.BuildPatterns()
	L.LootPatterns = {}
	if LOOT_ITEM_SELF_MULTIPLE then L.LootPatterns[#L.LootPatterns + 1] = Pattern(LOOT_ITEM_SELF_MULTIPLE) end
	if LOOT_ITEM_SELF then L.LootPatterns[#L.LootPatterns + 1] = Pattern(LOOT_ITEM_SELF) end
	L.MoneyParts = {}
	for _, Pair in ipairs({ { GOLD_AMOUNT, 10000 }, { SILVER_AMOUNT, 100 }, { COPPER_AMOUNT, 1 } }) do
		if Pair[1] then L.MoneyParts[#L.MoneyParts + 1] = { (Pair[1]:gsub("%%d", "(%%d+)")), Pair[2] } end
	end
end
function L.ParseLoot(Msg)
	for _, P in ipairs(L.LootPatterns) do
		local Link, N = Msg:match(P)
		if Link then
			local id = tonumber(Link:match("item:(%d+)"))
			if id then return id, tonumber(N) or 1 end
		end
	end
end
function L.ParseMoney(Msg)
	local C = 0
	for _, Part in ipairs(L.MoneyParts) do
		local N = Msg:match(Part[1])
		if N then C = C + tonumber(N) * Part[2] end
	end
	return C
end

-- Window ---------------------------------------------------------------------------------------------------------
local Frame
local Rows = {}
local Data, Offset, Tab = {}, 0, 1
local Columns = {
	[1] = { { "Reagent", 200 }, { "Value/day", 90 }, { "Sell at", 80 }, { "Sells/hr", 60 }, { "Your gold/hr", 90 }, { "Status", 80 } },
	[2] = { { "Item", 190 }, { "Profit", 80 }, { "Buy", 110 }, { "Resell", 80 }, { "Sells/hr", 60 }, { "Time", 40 }, { "Status", 50 } },
}

local function MyGoldPerHour(id)
	local Secs, Items = 0, 0
	for _, S in ipairs(Char().sessions) do
		if S.items and S.items[id] then Secs, Items = Secs + (S.secs or 0), Items + S.items[id] end
	end
	local Cur = Session.Current()
	if Cur and Cur.items and Cur.items[id] then Secs, Items = Secs + Session.Seconds(Cur), Items + Cur.items[id] end
	if Secs < 60 then return nil end
	return Core.LootValue(Core.Info(id), Items, Vendor(id)) / (Secs / 3600)
end

local function SetCells(Row, Values)
	for i, Cell in ipairs(Row.Cells) do
		Cell:SetText(Values[i] or "")
	end
end

local function LayoutHeader()
	local Cols = Columns[Tab]
	for i, H in ipairs(Frame.Headers) do
		local C = Cols and Cols[i]
		H:SetShown(C ~= nil)
		if C then H:SetText(C[1]) end
	end
	local X = 34
	for i, H in ipairs(Frame.Headers) do
		local C = Cols and Cols[i]
		if C then
			H:ClearAllPoints(); H:SetPoint("TOPLEFT", Frame.Inset, "TOPLEFT", X, -8); H:SetWidth(C[2])
			for _, R in ipairs(Rows) do
				R.Cells[i]:ClearAllPoints(); R.Cells[i]:SetPoint("LEFT", R, "LEFT", X - 6, 0); R.Cells[i]:SetWidth(C[2])
			end
			X = X + C[2] + 6
		end
	end
end

function L.Refresh()
	if not (Frame and Frame:IsShown()) then return end
	local Age = Core.DataAge()
	local Watched = Core.HoursWatched() or 0
	local Basis = Watched <= 0 and "  |cffff8040waiting for the first hour of sales|r"
		or (Watched < Core.EarlyHours and string.format("  |cffffd100early: %.0f h of sales|r", Watched))
		or string.format("  %.0f h of sales", Watched)
	local Fresh = AuctionForeverDB and AuctionForeverDB.fresh
	local ScanText = ""
	if Fresh and Fresh.time then
		local M = math.floor((time() - Fresh.time) / 60)
		ScanText = "your scan " .. (M < 120 and (M .. " min") or (math.floor(M / 60) .. " h")) .. " ago   "
		if Watched <= 0 then Basis = "" end
	end
	Frame.Age:SetText(ScanText .. (Age and (string.format("cloud data %s old", Age < 1 and (math.floor(Age * 60) .. " min") or (string.format("%.1f h", Age))) .. Basis)
		or (ScanText ~= "" and "" or "no data yet: scan at the auction house, or start AuctionForever Sync and /reload")))
	if Age and Age > 3 then Frame.Age:SetTextColor(1, 0.5, 0.25) else Frame.Age:SetTextColor(0.8, 0.8, 0.8) end
	local Sessions = Tab == 3
	Frame.List:SetShown(not Sessions)
	Frame.SessionPane:SetShown(Sessions)
	if Sessions then L.RefreshSessions() return end
	LayoutHeader()
	for i, R in ipairs(Rows) do
		local E = Data[i + Offset]
		R:SetShown(E ~= nil)
		if E then
			local Name, Quality = ItemName(E.id)
			local Color = ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[Quality or 1]
			R.Icon:SetTexture(Icon(E.id))
			R.id = E.id
			local I = E.info
			local NameText = (Color and Color.hex or "|cffffffff") .. Name .. "|r"
			if Tab == 1 then
				local Mine = MyGoldPerHour(E.id)
				SetCells(R, { NameText, E.status == "good" and Core.Money(E.value) or "-", Core.Money(Core.Market(I)),
					string.format("%.0f", I.perHour or 0), Mine and Core.Money(Mine) or "-", StatusText(E.status) })
			else
				local F = E.flip
				SetCells(R, { NameText, "|cff1eff00" .. Core.Money(F.profit) .. "|r", F.buyQty .. " at up to " .. Core.Money(F.buyUpTo),
					Core.Money(F.resell), string.format("%.0f", I.perHour or 0), F.hours .. " h", StatusText("good") })
			end
		end
	end
	Frame.Empty:SetShown(#Data == 0)
	if #Data == 0 then
		Frame.Empty:SetText(Tab == 2 and L.FlipEmptyReason() or "Nothing to show yet.")
	end
end

function L.RefreshSessions()
	local P = Frame.SessionPane
	local S = Session.Current()
	local Secs = Session.Seconds(S)
	P.Clock:SetText(string.format("%d:%02d:%02d", Secs / 3600, (Secs % 3600) / 60, Secs % 60))
	local Running = Session.Running()
	P.State:SetText(Running and "|cff1eff00Timer running|r" or "|cffff6040Timer stopped|r")
	P.Toggle:SetText(Running and "Stop timer" or "Start timer")
	local V = S and Session.Value(S) or 0
	P.Gold:SetText("This session: " .. Core.Money(V) .. (Secs >= 60 and ("   (" .. Core.Money(V / (Secs / 3600)) .. " per hour)") or ""))
	local Parts = {}
	if S then
		for id, N in pairs(S.items) do Parts[#Parts + 1] = (ItemName(id)) .. " x" .. N end
		table.sort(Parts)
		if (S.money or 0) > 0 then Parts[#Parts + 1] = "money " .. Core.Money(S.money) end
	end
	P.Loot:SetText(#Parts > 0 and ("Looted: " .. table.concat(Parts, ", ")) or "Looted: nothing yet")
	local Lines = {}
	for i, Old in ipairs(Char().sessions) do
		if i > 10 then break end
		local OSecs = Old.secs or 0
		local OV = Session.Value(Old)
		Lines[#Lines + 1] = string.format("%s   %s   %d min   %s   %s/hr", date("%b %d %H:%M", Old.start or 0), Old.zone or "?",
			math.floor(OSecs / 60), Core.Money(OV), OSecs >= 60 and Core.Money(OV / (OSecs / 3600)) or "-")
	end
	P.History:SetText(#Lines > 0 and table.concat(Lines, "\n") or "No finished sessions yet.")
end

function L.Load()
	if Tab == 1 then Data = L.FarmRows() elseif Tab == 2 then Data = L.FlipRows() else Data = {} end
	Offset = 0
	L.Refresh()
end

function L.SelectTab(i)
	Tab = i
	PanelTemplates_SetTab(Frame, i)
	L.Load()
end

local function SavePosition()
	local Point, _, RelPoint, X, Y = Frame:GetPoint(1)
	Char().pos = { Point, RelPoint, X, Y }
end

function L.CreateWindow()
	if Frame then return Frame end
	Frame = CreateFrame("Frame", "AuctionForeverFrame", UIParent, "ButtonFrameTemplate")
	ButtonFrameTemplate_HidePortrait(Frame)
	Frame:SetSize(720, 470)
	Frame:SetTitle("AuctionForever")
	Frame:SetFrameStrata("HIGH")
	Frame:SetToplevel(true)
	Frame:SetClampedToScreen(true)
	Frame:SetMovable(true)
	Frame:EnableMouse(true)
	Frame:RegisterForDrag("LeftButton")
	Frame:SetScript("OnDragStart", function(self) if IsShiftKeyDown() then self:StartMoving() end end)
	Frame:SetScript("OnDragStop", function(self) self:StopMovingOrSizing(); SavePosition() end)
	local Pos = Char().pos
	if Pos then Frame:SetPoint(Pos[1], UIParent, Pos[2], Pos[3], Pos[4]) else Frame:SetPoint("CENTER") end
	tinsert(UISpecialFrames, "AuctionForeverFrame") -- Escape closes it

	Frame.Age = Frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	Frame.Age:SetPoint("TOPRIGHT", -30, -6)

	for i, Name in ipairs(TABS) do
		local T = CreateFrame("Button", "AuctionForeverFrameTab" .. i, Frame, "PanelTabButtonTemplate")
		T:SetID(i)
		T:SetText(Name)
		if i == 1 then T:SetPoint("TOPLEFT", Frame, "BOTTOMLEFT", 12, 2) else T:SetPoint("LEFT", Frame.Tabs[i - 1], "RIGHT", 4, 0) end
		T:SetScript("OnClick", function(self) L.SelectTab(self:GetID()) end)
		PanelTemplates_TabResize(T, 0)
	end
	PanelTemplates_SetNumTabs(Frame, #TABS)

	-- List pane
	Frame.List = CreateFrame("Frame", nil, Frame.Inset)
	Frame.List:SetAllPoints()
	Frame.Headers = {}
	for i = 1, 7 do
		local H = Frame.List:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
		H:SetJustifyH("LEFT")
		Frame.Headers[i] = H
	end
	for r = 1, ROWS do
		local R = CreateFrame("Button", nil, Frame.List)
		R:SetSize(680, ROW_H)
		R:SetPoint("TOPLEFT", Frame.Inset, "TOPLEFT", 6, -24 - (r - 1) * ROW_H)
		R:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
		R.Icon = R:CreateTexture(nil, "ARTWORK")
		R.Icon:SetSize(18, 18)
		R.Icon:SetPoint("LEFT", 2, 0)
		R.Cells = {}
		for c = 1, 7 do
			local FS = R:CreateFontString(nil, "OVERLAY", c == 1 and "GameFontHighlight" or "GameFontHighlightSmall")
			FS:SetJustifyH("LEFT")
			FS:SetWordWrap(false)
			R.Cells[c] = FS
		end
		R:SetScript("OnEnter", function(self)
			if not self.id then return end
			GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
			GameTooltip:SetItemByID(self.id)
			GameTooltip:Show()
		end)
		R:SetScript("OnLeave", function() GameTooltip:Hide() end)
		Rows[r] = R
	end
	Frame.Empty = Frame.List:CreateFontString(nil, "OVERLAY", "GameFontDisable")
	Frame.Empty:SetPoint("CENTER", Frame.Inset, "CENTER")
	Frame.List:EnableMouseWheel(true)
	Frame.List:SetScript("OnMouseWheel", function(_, Delta)
		Offset = math.max(0, math.min(math.max(0, #Data - ROWS), Offset - Delta * 3))
		L.Refresh()
	end)

	-- Sessions pane
	local P = CreateFrame("Frame", nil, Frame.Inset)
	P:SetAllPoints()
	Frame.SessionPane = P
	P.Clock = P:CreateFontString(nil, "OVERLAY", "GameFontNormalHuge")
	P.Clock:SetPoint("TOPLEFT", 16, -16)
	P.State = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.State:SetPoint("TOPLEFT", P.Clock, "BOTTOMLEFT", 0, -4)
	P.Gold = P:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	P.Gold:SetPoint("TOPLEFT", P.State, "BOTTOMLEFT", 0, -10)
	local function Btn(Text, X, OnClick)
		local B = CreateFrame("Button", nil, P, "UIPanelButtonTemplate")
		B:SetSize(120, 26)
		B:SetText(Text)
		B:SetPoint("TOPLEFT", 16 + X, -110)
		B:SetScript("OnClick", OnClick)
		return B
	end
	P.Toggle = Btn("Start timer", 0, function() if Session.Running() then Session.Stop() else Session.Start() end L.RefreshSessions() end)
	Btn("New session", 130, function() Session.Stop(); Session.New(); L.RefreshSessions() end)
	Btn("Clear sessions", 260, function() StaticPopup_Show("AUCTIONFOREVER_CLEAR_SESSIONS") end)
	P.Loot = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.Loot:SetPoint("TOPLEFT", 16, -146)
	P.Loot:SetWidth(670)
	P.Loot:SetJustifyH("LEFT")
	local HistTitle = P:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	HistTitle:SetPoint("TOPLEFT", 16, -200)
	HistTitle:SetText("Past sessions")
	P.History = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.History:SetPoint("TOPLEFT", HistTitle, "BOTTOMLEFT", 0, -6)
	P.History:SetJustifyH("LEFT")
	P.Ticker = 0
	P:SetScript("OnUpdate", function(self, Elapsed)
		self.Ticker = self.Ticker + Elapsed
		if self.Ticker >= 1 then self.Ticker = 0; L.RefreshSessions() end
	end)

	Frame:SetScript("OnShow", function() L.Load() end)
	Frame:Hide()
	PanelTemplates_SetTab(Frame, 1)
	return Frame
end

function L.Toggle(TabIndex)
	L.CreateWindow()
	if Frame:IsShown() and (not TabIndex or TabIndex == Tab) then Frame:Hide() return end
	Tab = TabIndex or Tab
	PanelTemplates_SetTab(Frame, Tab)
	if Frame:IsShown() then L.Load() else Frame:Show() end
end

-- AuctionForever tab in the auction house ----------------------------------------------------------------------
-- Built without writing to Blizzard's tab list or display modes (that would taint the auction house and get
-- purchases blocked): our own tab button, owned by our own frame, and a panel laid over the content area that hides
-- whenever one of the other tabs is clicked.
local AH = {}
local function SelectedBlizzTab()
	local i = AuctionHouseFrame.selectedTab
	return i and AuctionHouseFrame.Tabs and AuctionHouseFrame.Tabs[i]
end
local function TabRow()
	-- Every visible tab-like button on the bottom row (Blizzard's and other add-ons'), ours excluded.
	local Row, Buy = {}, AuctionHouseFrame.BuyTab
	local Top = Buy and Buy:GetTop()
	if not Top then return Row end
	local function Walk(F, Depth)
		for _, C in ipairs({ F:GetChildren() }) do
			if C ~= AH.Tab and C ~= AH.Holder and C ~= AH.Panel then
				if C:IsShown() and C:GetObjectType() == "Button" and C:GetTop()
					and math.abs(C:GetTop() - Top) < 4 and (C:GetLeft() or 0) >= (Buy:GetLeft() or 0) - 1 then
					Row[#Row + 1] = C
				elseif Depth < 2 then Walk(C, Depth + 1) end
			end
		end
	end
	Walk(AuctionHouseFrame, 0)
	return Row
end
local function PlaceTab()
	local Buy = AuctionHouseFrame.BuyTab
	if not (Buy and Buy:GetLeft()) then return end
	local Right = Buy:GetRight()
	for _, B in ipairs(TabRow()) do if (B:GetRight() or 0) > Right then Right = B:GetRight() end end
	AH.Tab:ClearAllPoints()
	AH.Tab:SetPoint("LEFT", Buy, "LEFT", Right - Buy:GetLeft() + 3, 0) -- standard tabs sit 3 px apart
end
function L.ShowAHPanel()
	AH.Panel:Show()
	PanelTemplates_SelectTab(AH.Tab)
	local Sel = SelectedBlizzTab()
	if Sel then PanelTemplates_DeselectTab(Sel) end
	L.RefreshAHPanel()
end
function L.HideAHPanel()
	if not (AH.Panel and AH.Panel:IsShown()) then return end
	AH.Panel:Hide()
	PanelTemplates_DeselectTab(AH.Tab)
	local Sel = SelectedBlizzTab()
	if Sel then PanelTemplates_SelectTab(Sel) end
end
local function HookRowButtons()
	for _, B in ipairs(TabRow()) do
		if not AH.Hooked[B] then AH.Hooked[B] = true; B:HookScript("OnClick", function() L.HideAHPanel() end) end
	end
end
function L.CreateAHTab()
	if AH.Tab or not AuctionHouseFrame then return end
	AH.Hooked = {}
	AH.Holder = CreateFrame("Frame", nil, AuctionHouseFrame) -- owns the tab, so it isn't added to Blizzard's Tabs
	AH.Holder:SetSize(1, 1)
	AH.Holder:SetPoint("TOPLEFT")
	AH.Tab = CreateFrame("Button", "AuctionForeverAHTab", AH.Holder, "PanelTabButtonTemplate")
	AH.Tab:SetText("AuctionForever")
	PanelTemplates_TabResize(AH.Tab, 20, nil, 70)
	PanelTemplates_DeselectTab(AH.Tab)
	AH.Tab:SetScript("OnClick", function() PlaySound(SOUNDKIT and SOUNDKIT.IG_CHARACTER_INFO_TAB or 841); L.ShowAHPanel() end)
	AH.Tab:SetPoint("TOPLEFT", AuctionHouseFrame, "BOTTOMRIGHT", -150, 2)

	local P = CreateFrame("Frame", "AuctionForeverAHPanel", AuctionHouseFrame)
	AH.Panel = P
	P:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPLEFT", 4, -58)
	P:SetPoint("BOTTOMRIGHT", AuctionHouseFrame, "BOTTOMRIGHT", -4, 28)
	P:SetFrameLevel(AuctionHouseFrame:GetFrameLevel() + 60)
	P:EnableMouse(true)
	local Bg = P:CreateTexture(nil, "BACKGROUND")
	Bg:SetAllPoints()
	Bg:SetColorTexture(0.06, 0.06, 0.06, 1)
	local Inset = CreateFrame("Frame", nil, P, "InsetFrameTemplate")
	Inset:SetAllPoints()
	P:Hide()

	P.Title = P:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
	P.Title:SetPoint("TOPLEFT", 20, -18)
	P.Title:SetText("AuctionForever")
	P.Data = P:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	P.Data:SetPoint("TOPLEFT", P.Title, "BOTTOMLEFT", 0, -10)
	P.Data:SetJustifyH("LEFT")
	local function Btn(Text, X, Y, W, OnClick, Tip)
		local B = CreateFrame("Button", nil, P, "UIPanelButtonTemplate")
		B:SetSize(W, 26); B:SetText(Text); B:SetPoint("TOPLEFT", X, Y); B:SetScript("OnClick", OnClick)
		B:SetScript("OnEnter", function(self)
			GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
			GameTooltip:AddLine(Text)
			for _, Ln in ipairs(Tip) do GameTooltip:AddLine(Ln, 1, 1, 1, true) end
			GameTooltip:Show()
		end)
		B:SetScript("OnLeave", function() GameTooltip:Hide() end)
		return B
	end
	P.Quick = Btn("Quick Scan", 20, -90, 140, function() AF.Scan.Quick(); L.RefreshAHPanel() end,
		{ "Fast: current lowest price and stock for every item, in a few requests (the same method as Auctionator's scan).",
		  "Doesn't measure sales by itself; full scans and the cloud data do that." })
	P.Full = Btn("Full Scan", 170, -90, 140, function() AF.Scan.Start(); L.RefreshAHPanel() end,
		{ "Reads every listing in the auction house: fresh prices for everything, and sales measured for every item.",
		  "The server may allow this only once every 15 min." })
	P.Open = Btn("Open lists", 320, -90, 140, function() L.Toggle(1) end, { "Opens the AuctionForever window (Farm, Flip and Sessions)." })
	P.QuickInfo = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.QuickInfo:SetPoint("TOPLEFT", 20, -124)
	P.QuickInfo:SetJustifyH("LEFT")
	-- Progress bar shown while a scan runs (same spot as the line above).
	local Bar = CreateFrame("StatusBar", nil, P)
	Bar:SetPoint("TOPLEFT", 20, -122)
	Bar:SetSize(440, 18)
	Bar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
	Bar:SetStatusBarColor(0.1, 0.6, 0.1)
	Bar:SetMinMaxValues(0, 1)
	local BarBg = Bar:CreateTexture(nil, "BACKGROUND")
	BarBg:SetAllPoints()
	BarBg:SetColorTexture(0, 0, 0, 0.6)
	Bar.Text = Bar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	Bar.Text:SetPoint("CENTER")
	Bar:Hide()
	P.Bar = Bar
	P.Tick = 0
	P:SetScript("OnUpdate", function(self, Elapsed)
		self.Tick = self.Tick + Elapsed
		if self.Tick < 0.1 then return end
		self.Tick = 0
		if AF.Scan.Busy() then L.ScanProgress() end
	end)
	P.Result = P:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	P.Result:SetPoint("TOPLEFT", 20, -150)
	P.Result:SetWidth(740)
	P.Result:SetJustifyH("LEFT")
	P.Next = P:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	P.Next:SetPoint("BOTTOMLEFT", 20, 16)
	P.Next:SetText("Coming next in this tab: the sell queue (prefilled price, amount and duration; Post / Skip) and Buy next for flips.")

	AH.Holder:SetScript("OnShow", function() C_Timer.After(0, function() PlaceTab(); HookRowButtons() end) end)
	AH.Holder:SetScript("OnHide", function() L.HideAHPanel() end)
	hooksecurefunc(AuctionHouseFrame, "SetDisplayMode", function() L.HideAHPanel() end)
	C_Timer.After(0, function() PlaceTab(); HookRowButtons() end)
end
function L.RefreshAHPanel()
	if not (AH.Panel and AH.Panel:IsShown()) then return end
	local P = AH.Panel
	local Parts = {}
	local Age, Watched = Core.DataAge(), Core.HoursWatched() or 0
	Parts[#Parts + 1] = Age and string.format("Cloud data: %s old, %.1f h of sales measured.", Age < 1 and (math.floor(Age * 60) .. " min") or string.format("%.1f h", Age), Watched) or "Cloud data: none yet (start AuctionForever Sync, then /reload)."
	local Fresh = AuctionForeverDB and AuctionForeverDB.fresh
	if Fresh and Fresh.time then Parts[#Parts + 1] = string.format("Your last full scan: %d min ago.", math.floor((time() - Fresh.time) / 60)) end
	P.Data:SetText(table.concat(Parts, "   "))
	local Busy = AF.Scan.Busy()
	P.Quick:SetEnabled(not Busy); P.Full:SetEnabled(not Busy)
	if not Busy then P.QuickInfo:SetText("Quick Scan: fresh prices for everything.  Full Scan: also measures sales (scan 15+ min apart).") end
	P.Result:SetText(AF.Scan.LastResult or "No scan yet this session.")
end
function L.ScanProgress()
	if not (AH.Panel and AH.Panel:IsShown()) then return end
	local P = AH.Panel
	local Text, F = AF.Scan.Status()
	if not Text then return end
	P.Quick:SetEnabled(false); P.Full:SetEnabled(false)
	P.QuickInfo:Hide()
	P.Bar:Show()
	P.Bar.Text:SetText(Text)
	if F then
		P.Bar:SetStatusBarColor(0.1, 0.6, 0.1)
		P.Bar:SetValue(F)
	else
		-- Waiting for the server: a short block sweeping back and forth, so it's clearly still working.
		local T = GetTime() % 2
		P.Bar:SetStatusBarColor(0.6, 0.5, 0.1)
		P.Bar:SetValue(T < 1 and T or 2 - T)
	end
end
function L.ScanDone()
	if AH.Panel then AH.Panel.Bar:Hide(); AH.Panel.QuickInfo:Show() end
	L.RefreshAHPanel()
	if Frame and Frame:IsShown() then L.Load() end
end

StaticPopupDialogs["AUCTIONFOREVER_CLEAR_SESSIONS"] = {
	text = "Delete all recorded farming sessions?",
	button1 = YES or "Yes", button2 = NO or "No",
	OnAccept = function() Session.Clear(); L.RefreshSessions() end,
	timeout = 0, whileDead = true, hideOnEscape = true,
}

-- Minimap button -------------------------------------------------------------------------------------------------
local function PlaceMinimapButton(B)
	local A = math.rad(Account().minimapAngle)
	local R = (Minimap:GetWidth() / 2) + 5
	B:ClearAllPoints()
	B:SetPoint("CENTER", Minimap, "CENTER", math.cos(A) * R, math.sin(A) * R)
end
function L.CreateMinimapButton()
	local B = CreateFrame("Button", "AuctionForeverMinimapButton", Minimap)
	B:SetSize(31, 31)
	B:SetFrameStrata("MEDIUM")
	B:SetFrameLevel(8)
	B:RegisterForClicks("LeftButtonUp", "RightButtonUp")
	B:RegisterForDrag("LeftButton")
	B:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
	local Bg = B:CreateTexture(nil, "BACKGROUND")
	Bg:SetSize(20, 20); Bg:SetPoint("TOPLEFT", 7, -5)
	Bg:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
	local Ic = B:CreateTexture(nil, "ARTWORK")
	Ic:SetSize(17, 17); Ic:SetPoint("TOPLEFT", 7, -6)
	Ic:SetTexture("Interface\\Icons\\INV_Misc_Coin_02")
	local Border = B:CreateTexture(nil, "OVERLAY")
	Border:SetSize(53, 53); Border:SetPoint("TOPLEFT")
	Border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
	B:SetScript("OnClick", function(_, Button) L.Toggle(Button == "RightButton" and 2 or 1) end)
	B:SetScript("OnDragStart", function(self)
		self:SetScript("OnUpdate", function()
			local MX, MY = Minimap:GetCenter()
			local CX, CY = GetCursorPosition()
			local S = Minimap:GetEffectiveScale()
			Account().minimapAngle = math.deg(math.atan2(CY / S - MY, CX / S - MX))
			PlaceMinimapButton(self)
		end)
	end)
	B:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
	B:SetScript("OnEnter", function(self)
		GameTooltip:SetOwner(self, "ANCHOR_LEFT")
		GameTooltip:AddLine("AuctionForever")
		GameTooltip:AddLine("Click: farm list   Right-click: flips", 1, 1, 1)
		GameTooltip:AddLine("Drag: move this button", 0.7, 0.7, 0.7)
		GameTooltip:Show()
	end)
	B:SetScript("OnLeave", function() GameTooltip:Hide() end)
	PlaceMinimapButton(B)
	return B
end

-- Tooltips -------------------------------------------------------------------------------------------------------
function L.TooltipLines(id)
	local I = Core.Info(id)
	if not I then return nil end
	local Lines = {}
	local S = Core.Status(I)
	Lines[#Lines + 1] = { "Recent selling price", Core.Money(I.med) }
	Lines[#Lines + 1] = { "Sells", string.format("~%.0f per hour", I.perHour or 0) .. ((I.scanHours and I.scanHours > 0) and " (incl. your scans)" or "") }
	Lines[#Lines + 1] = { "Lowest listed", (I.low and Core.Money(I.low) or "-") .. string.format(" (%d listed)", I.qty or 0) }
	if S == "good" then
		local H, _, Price = Core.ChooseDuration(I, 1)
		if H then Lines[#Lines + 1] = { "Post at", "|cff1eff00" .. Core.Money(Price) .. ", " .. H .. " h|r" } end
	else
		Lines[#Lines + 1] = { "Status", StatusText(S) }
	end
	return Lines
end
local function OnTooltip(Tip, TData)
	if Tip ~= GameTooltip and Tip ~= ItemRefTooltip then return end
	local id = TData and TData.id
	if not id then return end
	local Lines = L.TooltipLines(id)
	if not Lines then return end
	Tip:AddLine(" ")
	Tip:AddLine("AuctionForever", 1, 0.82, 0)
	for _, Ln in ipairs(Lines) do Tip:AddDoubleLine(Ln[1], Ln[2], 0.8, 0.8, 0.8, 1, 1, 1) end
end

-- Events ---------------------------------------------------------------------------------------------------------
local Events = CreateFrame("Frame")
Events:RegisterEvent("PLAYER_LOGIN")
Events:RegisterEvent("PLAYER_LOGOUT")
Events:RegisterEvent("CHAT_MSG_LOOT")
Events:RegisterEvent("CHAT_MSG_MONEY")
Events:RegisterEvent("GET_ITEM_INFO_RECEIVED")
Events:RegisterEvent("AUCTION_HOUSE_SHOW")
local RefreshQueued
Events:SetScript("OnEvent", function(_, Event, Msg)
	if Event == "PLAYER_LOGIN" then
		L.BuildPatterns()
		Char(); Account()
		local S = Session.Current()
		if S then S.runningSince = nil end -- a clock never runs across logins
		L.CreateMinimapButton()
		C_Timer.After(5, function()
			local Ids = {}
			for _, R in ipairs(L.FarmRows()) do Ids[#Ids + 1] = R.id end
			for _, R in ipairs(L.FlipRows()) do Ids[#Ids + 1] = R.id end
			L.Preload(Ids)
		end)
		if TooltipDataProcessor and Enum and Enum.TooltipDataType then
			TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, OnTooltip)
		end
	elseif Event == "AUCTION_HOUSE_SHOW" then
		L.CreateAHTab()
		L.HideAHPanel()
	elseif Event == "PLAYER_LOGOUT" then
		Session.Pause()
	elseif Event == "CHAT_MSG_LOOT" then
		local id, N = L.ParseLoot(Msg or "")
		if id then Session.AddItem(id, N) end
	elseif Event == "CHAT_MSG_MONEY" then
		local C = L.ParseMoney(Msg or "")
		if C > 0 then Session.AddMoney(C) end
	elseif Event == "GET_ITEM_INFO_RECEIVED" then
		if Frame and Frame:IsShown() and not RefreshQueued then
			RefreshQueued = true
			C_Timer.After(0.3, function() RefreshQueued = false; L.Refresh() end)
		end
	end
end)

SLASH_AUCTIONFOREVER1 = "/af"
SLASH_AUCTIONFOREVER2 = "/auctionforever"
SlashCmdList.AUCTIONFOREVER = function(Msg)
	Msg = (Msg or ""):lower()
	if Msg == "flip" then L.Toggle(2) elseif Msg == "sessions" then L.Toggle(3) elseif Msg == "scan" then AF.Scan.Start() elseif Msg == "quick" then AF.Scan.Quick() else L.Toggle(1) end
end

AF.UI = L
