-- AF Buy and AF Sell tabs in the auction house.
-- Every purchase and every post is one real click by the player (the game requires it); nothing is automatic.
local _, AF = ...
local Core, Scan = AF.Core, AF.Scan
local T = {}
AF.Trade = T

local STALE = 120           -- seconds: older item data is re-checked when the item is selected
local ROWS = 14
local ROW_H = 22
local LAST_BAG = 4          -- backpack (0) and four bags
local Status = Enum and Enum.ItemCommodityStatus
local COMMODITY = Status and Status.Commodity or 2
local ITEM = Status and Status.Item or 1

local BuyP, SellP           -- panels
local Buy = { rows = {}, sel = 1, sort = "plan", asc = false }
local Run, LastRun -- a craft plan whose mats you're buying, and the last one you finished (see Craft plans below)
local SORTS
local BUY_KEYS = { "name", "tier", "rate", "cost", "resell", "profit", "status" } -- one per AF Buy column
local Sell = { queue = {}, idx = 1 }

-- Helpers -----------------------------------------------------------------------------------------------------
local function UI() return AF.UI end
local function FreshTime(id)
	local DB = AuctionForeverDB
	local F = DB and DB.fresh and DB.fresh.items and DB.fresh.items[id]
	return F and F[4]
end
local function IsStale(id)
	local W = FreshTime(id)
	return not W or time() - W > STALE
end
-- Fresh prices for these items. If another scan or lookup is running, wait for it and check right after
-- (the latest request wins), instead of silently doing nothing.
local Pending
local function Recheck(Ids, Done)
	if #Ids == 0 then return false end
	if Scan.Busy() then Pending = { Ids, Done } return true end
	return Scan.Lookup(Ids, true, Done)
end
function T.OnScanDone()
	T.ClearScanStatus()
	-- New scan data: rebuild AF Buy's list now if it's open (not mid-purchase), or the next time it opens.
	if Buy.loaded and not Buy.state then
		Buy.loaded = nil
		if BuyP and BuyP:IsShown() then T.RefreshBuy() end
	end
	if not Pending then return end
	-- Let whatever just finished run its own follow-up first (e.g. a quick scan's busy-item lookups).
	C_Timer.After(0.1, function()
		if not Pending or Scan.Busy() then return end
		local P = Pending
		Pending = nil
		if not Scan.Lookup(P[1], true, P[2]) and P[2] then P[2]() end
	end)
end
-- Short: the list-row form of the name (see UI.ShortName); the detail lines keep the full name.
local function NameText(id, Short)
	local Name, Quality = UI().ItemName(id)
	local Color = ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[Quality or 1]
	return (Color and Color.hex or "|cffffffff") .. (Short and UI().ShortName(Name) or Name) .. "|r" .. (Short and UI().CraftedMark(id) or "")
end
local function Text(Parent, Font, X, Y, W)
	local FS = Parent:CreateFontString(nil, "OVERLAY", Font or "GameFontHighlight")
	FS:SetPoint("TOPLEFT", X, Y)
	if W then FS:SetWidth(W) end
	FS:SetJustifyH("LEFT")
	return FS
end
local function Button(Parent, Label, X, Y, W, OnClick)
	local B = CreateFrame("Button", nil, Parent, "UIPanelButtonTemplate")
	B:SetSize(W, 24); B:SetText(Label); B:SetPoint("TOPLEFT", X, Y); B:SetScript("OnClick", OnClick)
	return B
end
-- A list of clickable rows: icon + cells, mouse wheel scrolls.
local function RowList(Parent, X, Y, Width, Count, Cols, OnPick, Gap)
	local Rows = {}
	for r = 1, Count do
		local R = CreateFrame("Button", nil, Parent)
		R:SetSize(Width, ROW_H)
		R:SetPoint("TOPLEFT", X, Y - (r - 1) * ROW_H)
		R:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
		R.Sel = R:CreateTexture(nil, "BACKGROUND")
		R.Sel:SetAllPoints()
		R.Sel:SetColorTexture(1, 0.82, 0, 0.18)
		R.Sel:Hide()
		R.Icon = R:CreateTexture(nil, "ARTWORK")
		R.Icon:SetSize(18, 18)
		R.Icon:SetPoint("LEFT", 2, 0)
		R.Cells = {}
		local CX = 24
		for c, W in ipairs(Cols) do
			local FS = R:CreateFontString(nil, "OVERLAY", c == 1 and "GameFontHighlight" or "GameFontHighlightSmall")
			FS:SetPoint("LEFT", R, "LEFT", CX, 0)
			FS:SetWidth(W)
			FS:SetJustifyH("LEFT")
			FS:SetWordWrap(false)
			FS:SetMaxLines(1)
			R.Cells[c] = FS
			CX = CX + W + (Gap or 6)
		end
		R.row = r
		R:SetScript("OnClick", function(self) OnPick(self.row) end)
		R:SetScript("OnEnter", function(self)
			if not self.id then return end
			GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
			GameTooltip:SetItemByID(self.id)
			GameTooltip:Show()
		end)
		R:SetScript("OnLeave", function() GameTooltip:Hide() end)
		Rows[r] = R
	end
	return Rows
end
local Syncing -- set while a list moves its own bar (not a drag)
-- A scroll bar beside a row list (shown only when the list is longer than the rows), plus "1-14 of 31" under it.
local function ScrollBar(Parent, X, Y, OnScroll)
	local S = CreateFrame("Slider", nil, Parent)
	S:SetOrientation("VERTICAL")
	S:SetSize(16, ROWS * ROW_H)
	S:SetPoint("TOPLEFT", X, Y)
	S.Bg = S:CreateTexture(nil, "BACKGROUND")
	S.Bg:SetAllPoints()
	S.Bg:SetColorTexture(0, 0, 0, 0.45)
	S:SetThumbTexture("Interface\\Buttons\\UI-ScrollBar-Knob")
	S:SetValueStep(1)
	if S.SetObeyStepOnDrag then S:SetObeyStepOnDrag(true) end
	S:SetMinMaxValues(0, 0)
	S:SetValue(0)
	S:SetScript("OnValueChanged", function(self, V)
		if Syncing then return end
		OnScroll(math.floor(V + 0.5))
	end)
	S.Count = Parent:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	S.Count:SetPoint("TOPRIGHT", S, "BOTTOMRIGHT", 0, -2)
	return S
end
-- Bar range and position for a list of Total rows scrolled to Off; returns the offset kept inside the list.
local function SyncBar(S, Off, Total, Rows)
	Rows = Rows or ROWS
	local Max = math.max(0, Total - Rows)
	Off = math.max(0, math.min(Max, Off or 0))
	Syncing = true
	S:SetMinMaxValues(0, Max)
	S:SetValue(Off)
	Syncing = nil
	S:SetShown(Max > 0)
	S.Count:SetShown(Max > 0)
	S.Count:SetText(string.format("%d-%d of %d", Off + 1, math.min(Total, Off + Rows), Total))
	return Off
end
T.ScrollBar, T.SyncBar = ScrollBar, SyncBar -- the AuctionForever window uses them too
-- Column headers; with OnClick(c) they are buttons (click to sort), the text in .Label. Returns them.
local function Header(Parent, X, Y, Cols, Names, OnClick, Gap)
	local CX = X + 24
	local Out = {}
	for c, W in ipairs(Cols) do
		local H
		if OnClick then
			H = CreateFrame("Button", nil, Parent)
			H:SetSize(W, 16)
			H:SetPoint("TOPLEFT", CX, Y + 2)
			H.Label = H:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
			H.Label:SetPoint("LEFT", H, "LEFT", 0, 0)
			H.Label:SetJustifyH("LEFT")
			H.Label:SetText(Names[c])
			H:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
			H:SetScript("OnClick", function() OnClick(c) end)
		else
			H = Parent:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
			H:SetPoint("TOPLEFT", CX, Y)
			H:SetWidth(W)
			H:SetJustifyH("LEFT")
			H:SetText(Names[c])
		end
		Out[c] = H
		CX = CX + W + (Gap or 6)
	end
	return Out
end

local function SaveDB() AuctionForeverDB = AuctionForeverDB or {} return AuctionForeverDB end
-- Remember a purchase: what you paid and the profit the plan expected per unit.
local function RecordBuy(id, Qty, Total, Resell)
	local Expect = Resell and (math.floor(Resell * (1 - Core.Cut)) - Total / math.max(1, Qty)) or 0
	Core.AddBuy(SaveDB(), id, Qty, Total, time(), Expect)
end

-- AF Buy ------------------------------------------------------------------------------------------------------
-- AF Buy fits the page it's on (the auction house window's inside: about 790 wide at the default size): the table
-- and the panel are sized from the page's width each time it's shown or resized. BUY_COLS are the widths at 868
-- (24 icon + columns + 6 gaps of 10); narrower, each column shrinks toward its minimum, wider, Item and Status get
-- the room.
local BUY_BASE = { 220, 34, 60, 150, 90, 100, 130 }
local BUY_MIN = { 120, 30, 50, 90, 60, 70, 80 }
local BUY_COLS = { 220, 34, 60, 150, 90, 100, 130 } -- the current widths (T.LayoutBuy sets them)
local BUY_GAP, BUY_W = 10, 868 -- the current table width
local PAGE_W_DEFAULT = 790 -- when the page can't tell its width yet
local SCROLL_W = 16 + 4 -- the scroll bar and its gap
local EDGE = 6 -- kept free at the page's right edge
local function Sum(T0) local N = 0 for _, V in ipairs(T0) do N = N + V end return N end
-- Column widths for Avail units: base widths shrunk toward the minimums (in proportion), or the slack shared by
-- the Slack columns; never under the minimums unless even those don't fit (then all scaled down).
local function FitCols(Base, Min, Avail, Slack)
	local Out, SB, SM = {}, Sum(Base), Sum(Min)
	if Avail >= SB then
		local Extra = Avail - SB
		for c, W in ipairs(Base) do Out[c] = W end
		for k, c in ipairs(Slack) do
			local Part = k < #Slack and math.floor(Extra / #Slack) or (Extra - math.floor(Extra / #Slack) * (#Slack - 1))
			Out[c] = Out[c] + Part
		end
	elseif Avail >= SM then
		local F = (Avail - SM) / math.max(1, SB - SM)
		for c, W in ipairs(Base) do Out[c] = Min[c] + math.floor((W - Min[c]) * F) end
		Out[Slack[1]] = Out[Slack[1]] + (Avail - Sum(Out))
	else
		for c, W in ipairs(Min) do Out[c] = math.floor(W * math.max(0, Avail) / SM) end
	end
	return Out
end
T.FitCols = FitCols
-- The details panel under the table (the selected row), pixel layout. The table starts at PANE_TOP; the panel ends
-- above the Next button (at -420), 4 below the table. Panel, top down: 4 padding, the header and evidence lines (14
-- each), 2, the column headers (14), one 20 px line per source line (its Buy button 18 tall), 4, three summary
-- lines (14 each), 2: 96 px with 2 text lines, + 20 a source line. With the table at 5 rows (110 px), 5 lines fit.
-- (Over the table: the summary lines at -8 / -23 / -38, the filter bar at -58, the column headers at -82.)
local FILTER_Y, HEAD_Y = -58, -82
local PANE_TOP, PANE_SPACE = -100, 316 -- the table's top, and the height from there to just above the buttons
local PANE_TEXT_H, PANE_LINE_H, PANE_MIN_ROWS, PANE_MAX_LINES = 14, 20, 5, 8
local PANE_BASE = { 40, 190, 80, 110, 60, 100 }
local PANE_MIN = { 30, 110, 60, 80, 55, 75 }
local PANE_COLS = { 40, 190, 80, 110, 60, 100 } -- the current widths (T.LayoutBuy sets them)
local PANE_GAP = 6
local BTN_MIN, BTN_MAX, BTN_H = 80, 160, 18 -- a panel line's Buy button: as wide as its label, within these
local PANE_NAMES = { "Need", "Reagent", "Source", "Pay up to", "Listed now", "Cost" }

local function SayBuy(Msg) if BuyP then BuyP.Status:SetText(Msg or "") end end
local function ResetPurchase(Cancel)
	if Cancel and (Buy.state == "price" or Buy.state == "confirm") then C_AuctionHouse.CancelCommoditiesPurchase() end
	Buy.state, Buy.pending = nil, nil
	if BuyP then BuyP.Buy:SetText("Buy") end
end

function T.SelectedBuy() return Buy.rows[Buy.sel] end
function T.BuyRows() return Buy.rows end

-- The option a row shows (and Buy buys): the plan's or the best affordable one; in profit order, the most profitable
-- at any gold.
local function Shown(E)
	if Buy.sort == "profit" then return E.best or E.flip end
	return E.flip
end
-- Gold the shown option needs before it's a target; nil if you can buy it now.
local function ShownNeed(E)
	local F = Shown(E)
	if E.plan and F == E.flip then return nil end
	if E.now and E.now[F] then return nil end
	if F == E.best and E.bestNeed then return E.bestNeed end
	return E.need
end
local function GoldText(N) return Core.MoneyColor(math.ceil(N / 100) * 100) end
-- Sort keys (plan: FlipRows order - the plan in buying order, then what fits now, then by gold needed). Each gives
-- the value a column shows; the list sorts highest first, or lowest first when Buy.asc.
-- Tier of a flip by its expected return (expected profit / cost; the profit already counts the sell chance, unsold
-- units and lost deposits; vendor buys the same way): S 35%+, A 25%+, B 15%+, C 10%+, D below (or no profit).
T.BUY_TIERS = { { "S", 0.35, "|cffa335ee" }, { "A", 0.25, "|cff1eff00" }, { "B", 0.15, "|cffffd100" }, { "C", 0.10, "|cffff4040" } }
function T.Return(F)
	if not (F and F.cost and F.cost > 0 and F.profit) then return nil end
	return F.profit / F.cost
end
function T.Tier(F)
	local R = T.Return(F)
	if R and F.profit > 0 then
		for _, B in ipairs(T.BUY_TIERS) do if R >= B[2] - 1e-9 then return B[1], B[3], R end end
	end
	return "D", "|cff9d9d9d", R
end
local function TierLine(F)
	local Tier, Color, R = T.Tier(F)
	return string.format("%sTier %s|r: %d%% expected return", Color, Tier, math.floor((R or 0) * 100 + 0.5))
end
T.TierLine = TierLine
-- The item's sell rate (sold / (sold + expired)); nil when not measured yet (sorts last).
local function Rate(E)
	if E.craft and E.flip and E.flip.route == "Vendor" then return 1 end -- sold to a vendor: a sure sale
	if not E.craft and E.flip and E.flip.vendor then return 1 end
	return E.info and type(E.info.sellThrough) == "number" and E.info.sellThrough or nil
end
T.BuyRate = Rate
local function SellsText(E)
	local R = Rate(E)
	return R and string.format("sells %d%%", math.floor(R * 100 + 0.5)) or "sell rate not measured yet"
end
-- Status column order, low to high: in the plan (0), fits now / vendor it (1), needs more gold (2, least gold
-- first), craft plans (3), craft plans on cooldown or blocked (4).
local function StatusRank(E)
	local F = Shown(E)
	if E.craft then return (F.onCooldown or F.blocked) and 4 or 3 end
	local Need = ShownNeed(E)
	if Need then return 2 + math.min(Need, 1e12) / 1e13 end
	if E.plan and F == E.flip then return 0 end
	return 1
end
T.StatusRank = StatusRank
function T.SortKey(Key, E) return SORTS[Key] and SORTS[Key](E) end
SORTS = {
	tier = function(E) return T.Return(Shown(E)) end,
	rate = function(E) return Rate(E) end,
	name = function(E) return UI().SortName(E.id) end,
	-- craft rows by one craft (mats a craft, profit a craft, as their cells show); flips by the whole purchase
	cost = function(E) local F = Shown(E) return F.craft and F.craftCost or F.cost end,
	resell = function(E) return Shown(E).resell end,
	profit = function(E) local F = E.best or E.flip return F.craft and F.craftProfit or F.profit end,
	status = StatusRank,
}
local BUY_NAMES = { "Item", "Tier", "Sell rate", "Buy", "Resell at", "Profit", "Status" }
function T.DrawBuy()
	if not BuyP then return end
	local Sel = Buy.rows[Buy.sel]
	local Model = Sel and T.PaneModel(Sel)
	local Visible = Model and Model.rows or ROWS
	Buy.visible = Visible
	if Buy.keepSel and Sel then -- a new selection: keep it scrolled into view
		local O = Buy.offset or 0
		if Buy.sel <= O then O = Buy.sel - 1 elseif Buy.sel > O + Visible then O = Buy.sel - Visible end
		Buy.offset = O
	end
	Buy.keepSel = nil
	BuyP.Bar:SetHeight(Visible * ROW_H)
	local Off = SyncBar(BuyP.Bar, Buy.offset, #Buy.rows, Visible)
	Buy.offset = Off
	for i, R in ipairs(BuyP.Rows) do
		local E = i <= Visible and Buy.rows[i + Off] or nil
		R:SetShown(E ~= nil)
		R.id = E and E.id
		if E then
			local F = Shown(E)
			local Need = ShownNeed(E)
			R.Icon:SetTexture(UI().Icon(E.id))
			R.Cells[1]:SetText(NameText(E.id, true))
			local Tier, TColor = T.Tier(F)
			R.Cells[2]:SetText(TColor .. Tier .. "|r")
			R.Cells[3]:SetText(F.vendor and "vendor" or UI().RateText(Rate(E)))
			R.Cells[4]:SetText(F.buyQty .. " at up to " .. Core.MoneyColor(F.buyUpTo))
			R.Cells[5]:SetText((F.vendor and "vendor " or "") .. Core.MoneyColor(F.resell))
			R.Cells[6]:SetText(Core.MoneyDelta(F.profit))
			local Status
			if F.craft then
				R.Cells[3]:SetText(F.route == "Vendor" and "vendor" or UI().RateText(Rate(E)))
				R.Cells[4]:SetText("mats " .. Core.MoneyColor(F.craftCost or 0))
				R.Cells[6]:SetText(Core.MoneyDelta(F.craftProfit or 0)) -- a craft (the panel shows the N crafts' totals)
				R.Cells[5]:SetText(F.route == "Vendor" and ("vendor " .. Core.MoneyColor(F.resell)) or ("AH " .. Core.MoneyColor(F.resell) .. " each"))
				Status = T.CraftStatus(E)
			elseif Need then Status = "at " .. GoldText(Need)
			elseif F.vendor then Status = "|cff1eff00vendor it|r"
			elseif E.plan and F == E.flip then Status = F.slow and "|cff1eff00in plan|r |cffffd100(slow)|r" or "|cff1eff00in plan|r"
			else Status = "|cffffd100fits, not in plan|r" .. (F.slow and " (slow)" or "") end
			R.Cells[7]:SetText(Status)
			if Need then R.Cells[1]:SetText("|cff808080" .. UI().ShortName((UI().ItemName(E.id))) .. "|r" .. UI().CraftedMark(E.id)) end -- not affordable yet: name greyed
			R.Sel:SetShown(i + Off == Buy.sel)
		end
	end
	BuyP.Empty:SetShown(#Buy.rows == 0)
	if #Buy.rows == 0 then
		local D = AuctionForeverData
		BuyP.Empty:SetText((type(D) == "table" and type(D.items) == "table") and "No flip targets right now."
			or "No auction data yet: scan at the auction house.")
	end
	local E = T.SelectedBuy()
	local Need = E and ShownNeed(E)
	BuyP.Buy:SetEnabled(E ~= nil and not E.craft and not Need and Buy.state ~= "price" and Buy.state ~= "buying")
	BuyP.Skip:SetEnabled(#Buy.rows > 1)
	T.DrawPane(E, Model)
	local R = Core.FlipResults(SaveDB(), time(), 7)
	BuyP.Results:SetText(R.sold > 0 and string.format("Your flips, last 7 days: %d sold, profit %s (plan expected %s)",
		R.sold, Core.MoneyColor(R.profit), Core.MoneyColor(R.expected)) or "")
	local P = UI().LastPlan
	local Line = "Flip Budget: " .. Core.MoneyColor(UI().FlipBudget())
	if P and P.count > 0 then
		Line = Line .. string.format("     Plan: %d items, cost %s, profit %s", P.count, Core.MoneyColor(P.cost), Core.MoneyDelta(P.profit))
	end
	BuyP.Budget:SetText(Line)
	local Min = T.TargetGold()
	if not Min then
		BuyP.Target:SetText("Target Budget: |cff808080no targets yet at any gold|r")
	elseif Min <= GetMoney() then
		BuyP.Target:SetText("Target Budget: " .. Core.MoneyColor(Min) .. "  |cff1eff00reached|r")
	else
		BuyP.Target:SetText("Target Budget: " .. Core.MoneyColor(Min) .. "  |cff808080(gold you need for the first target)|r")
	end
end

function T.Rows() return Buy.rows end
-- The least gold that makes anything a target (the cheapest way in over all listed targets), rounded up to the
-- silver; nil when nothing is a target at any gold.
function T.TargetGold()
	local Min
	for _, E in ipairs(Buy.rows) do
		local N = E.minGold or E.need
		if N and (not Min or N < Min) then Min = N end
	end
	return Min and math.ceil(Min / 100) * 100
end
-- Filter bar: All, Flips, or one profession's craft plans (only professions with rows now). Remembered per
-- account (AuctionForeverDB.buyFilter); a remembered profession with no rows now shows All.
local PROF_SHORT = { Blacksmithing = "Blacksmith", Enchanting = "Enchant", Engineering = "Engineer", Leatherworking = "Leather",
	Jewelcrafting = "Jewel", Inscription = "Inscript", Mining = "Mining", Smelting = "Mining" }
function T.ProfLabel(Name) return PROF_SHORT[Name] or (Name or "?"):sub(1, 10) end
local function Prof(E) return E.craft and (E.craft.skillName or "?") or nil end
function T.BuyFilter() return SaveDB().buyFilter or "all" end
function T.SetBuyFilter(F)
	SaveDB().buyFilter = F
	Buy.offset = 0
	T.SortRowsNow()
end
-- The professions with craft rows in the loaded list, by name.
function T.BuyProfessions()
	local Seen, Out = {}, {}
	for _, E in ipairs(Buy.loaded or {}) do
		local P = Prof(E)
		if P and not Seen[P] then Seen[P] = true; Out[#Out + 1] = P end
	end
	table.sort(Out)
	return Out
end
local function DrawFilters(Profs, Eff, NShown, Total)
	local P = BuyP
	if not (P and P.Filters) then return end
	local Keys = { "all", "flips" }
	for _, Name in ipairs(Profs) do Keys[#Keys + 1] = Name end
	-- Button widths from their labels; squeezed (down to 30) when they don't fit the table's width, and any that
	-- still don't fit are left out (the table's own filter is unchanged).
	local Widths, Labels = {}, {}
	for i, K in ipairs(Keys) do
		Labels[i] = K == "all" and "All" or K == "flips" and "Flips" or T.ProfLabel(K)
		Widths[i] = math.max(40, #Labels[i] * 7 + 20)
	end
	local Room = BUY_W
	local Need = Sum(Widths) + 4 * math.max(0, #Widths - 1)
	if Need > Room then
		local F = (Room - 4 * math.max(0, #Widths - 1)) / Sum(Widths)
		for i, W in ipairs(Widths) do Widths[i] = math.max(30, math.floor(W * F)) end
	end
	local X = 0
	for i, B in ipairs(P.Filters) do
		local K = Keys[i]
		local Fits = K ~= nil and X + Widths[i] <= Room
		B:SetShown(Fits)
		B.key = Fits and K or nil
		if Fits then
			B:SetText(Labels[i])
			B:SetWidth(Widths[i])
			B:ClearAllPoints()
			B:SetPoint("TOPLEFT", P, "TOPLEFT", 14 + X, FILTER_Y)
			B:SetEnabled(K ~= Eff)
			X = X + Widths[i] + 4
		end
	end
	P.FilterNote:ClearAllPoints()
	P.FilterNote:SetPoint("TOPLEFT", P, "TOPLEFT", 14 + X + 6, FILTER_Y - 5)
	P.FilterNote:SetWidth(100)
	P.FilterNote:SetShown(X + 6 + 100 <= Room)
	P.FilterNote:SetText(string.format("Showing %d of %d", NShown, Total))
end
-- Put the loaded list in the chosen order (no new work: sorting only reorders what's loaded), through the filter.
local function SortRows()
	local Id = Buy.rows[Buy.sel] and Buy.rows[Buy.sel].id
	Buy.rows = {}
	local Profs = T.BuyProfessions()
	local Eff = T.BuyFilter()
	if Eff ~= "all" and Eff ~= "flips" then
		local Ok = false
		for _, Name in ipairs(Profs) do if Name == Eff then Ok = true end end
		if not Ok then Eff = "all" end
	end
	Buy.filterNow = Eff
	for _, E in ipairs(Buy.loaded or {}) do
		if Eff == "all" or (Eff == "flips" and not E.craft) or (E.craft and Prof(E) == Eff) then Buy.rows[#Buy.rows + 1] = E end
	end
	DrawFilters(Profs, Eff, #Buy.rows, #(Buy.loaded or {}))
	if SORTS[Buy.sort] then UI().SortBy(Buy.rows, SORTS[Buy.sort], Buy.asc) end
	Buy.sel = 1
	for i, E in ipairs(Buy.rows) do if E.id == Id then Buy.sel = i end end
	if BuyP and BuyP.Headers then
		for c, H in ipairs(BuyP.Headers) do
			local Mark = BUY_KEYS[c] == Buy.sort and (Buy.asc and " ^" or " v") or ""
			H.Label:SetText(BUY_NAMES[c] .. Mark)
		end
	end
	T.DrawBuy()
end
T.SortRowsNow = function() SortRows() end
-- Rebuild the list from your data (refresh, a purchase, a scan). Opening the tab reuses it unless your gold changed;
-- sorting always reuses it.
-- Craft plans (UI.CraftTargets) join the flip targets: after the plan, among what you can buy now (most profit
-- first); targets that need more gold stay last. They don't compete with flips for the plan's budget (they buy
-- different listings, and each fits one item's share of the budget on its own).
local function WithCrafts(Rows)
	local Crafts = UI().CraftTargets and UI().CraftTargets() or {}
	if #Crafts == 0 then return Rows end
	local Out, Rest = {}, {}
	for _, E in ipairs(Rows) do if E.plan then Out[#Out + 1] = E else Rest[#Rest + 1] = E end end
	local c = 1
	for _, E in ipairs(Rest) do
		local Fits = E.now and E.now[E.flip]
		while Crafts[c] and (not Fits or Crafts[c].flip.profit > E.flip.profit) do Out[#Out + 1] = Crafts[c]; c = c + 1 end
		Out[#Out + 1] = E
	end
	while Crafts[c] do Out[#Out + 1] = Crafts[c]; c = c + 1 end
	return Out
end
function T.RefreshBuy()
	Buy.loaded, Buy.money = WithCrafts(UI().FlipTargets() or {}), GetMoney()
	SortRows()
end
-- Sort AF Buy by a key ("plan" = the plan's order). Asc nil: gold needed lowest first, the rest highest first.
function T.SetBuySort(Key, Asc)
	Buy.sort = SORTS[Key] and Key or "plan"
	if Asc == nil then Asc = Buy.sort == "status" end
	Buy.asc = Asc
	Buy.offset = 0
	SortRows()
end
function T.BuySort() return Buy.sort, Buy.asc end
-- A header click: highest first, again lowest first, a third time back to the plan's order.
function T.BuyHeaderClick(c)
	local Key = BUY_KEYS[c]
	if not Key then return end
	if Buy.sort ~= Key then T.SetBuySort(Key, false)
	elseif not Buy.asc then T.SetBuySort(Key, true)
	else T.SetBuySort("plan") end
end

function T.SelectBuy(i)
	ResetPurchase(true)
	if #Buy.rows == 0 then T.DrawBuy() return end
	Buy.sel = ((i - 1) % #Buy.rows) + 1
	Buy.bought = 0
	Buy.keepSel = true
	T.DrawBuy()
	-- No price check here: the list comes from your scans, and the purchase itself gets the live price from the
	-- server (and cancels if it rose). "Refresh prices" re-checks the list on purpose.
end

function T.RefreshBuyPrices()
	local Ids = {}
	for i = 1, math.min(20, #Buy.rows) do Ids[#Ids + 1] = Buy.rows[i].id end
	if #Ids == 0 then T.RefreshBuy() return end
	if Recheck(Ids, function() T.RefreshBuy(); SayBuy("Prices refreshed.") end) then SayBuy("Refreshing prices for " .. #Ids .. " items...") end
end

local function BuyNext()
	local Next = Buy.rows[Buy.sel + 1] and Buy.rows[Buy.sel + 1].id
	T.RefreshBuy()
	local Pick = 1
	for i, E in ipairs(Buy.rows) do if E.id == Next then Pick = i end end
	T.SelectBuy(Pick)
end

function T.BuyClick()
	local E = T.SelectedBuy()
	if not E then return end
	local F = Shown(E)
	if not Buy.state and ShownNeed(E) then return end
	if Buy.state == "confirm" then
		local Pd = Buy.pending
		C_AuctionHouse.ConfirmCommoditiesPurchase(Pd.id, Pd.qty)
		Buy.state = "buying"
		SayBuy("Buying...")
		T.DrawBuy()
		return
	end
	if Buy.state then return end
	if F.craft then
		if F.onCooldown then SayBuy("This recipe is on cooldown: ready in " .. T.HoursText(F.onCooldown) .. ".") return end
		if F.blocked then SayBuy("Not a craft to buy for: the product is " .. F.blocked .. ".") return end
		SayBuy("Buy each mat with the Buy button on its line below.")
		return
	end
	local Kind = Scan.Kind[E.id] or UI().Kind(E.id)
	if not Kind then
		SayBuy("Checking the current price first; click Buy again in a moment.")
		Recheck({ E.id }, function() T.RefreshBuy() end)
		return
	end
	if Kind == "commodity" then
		Buy.state = "price"
		Buy.pending = { id = E.id, qty = F.buyQty, max = F.buyUpTo, resell = F.resell, chance = F.chance, vendor = F.vendor }
		C_AuctionHouse.StartCommoditiesPurchase(E.id, F.buyQty)
		SayBuy("Getting the current price...")
		T.DrawBuy()
		return
	end
	-- Not a commodity: buy the cheapest listing at or under the max, one listing per click.
	local Budget = UI().FlipBudget()
	local List = Scan.Listings[E.id] or {}
	local Best, BestI
	local Multi
	for i, A in ipairs(List) do
		local Unit = A.buyout / math.max(1, A.qty)
		if Unit <= F.buyUpTo and A.buyout <= Budget and (not Best or Unit < Best.buyout / math.max(1, Best.qty)) then
			-- An auction of several items: what PlaceBid takes for it (one item's price or the whole auction's) isn't
			-- known on Forever, so AF doesn't bid on those; buy them in the Blizzard window.
			if (A.qty or 1) > 1 then Multi = Multi or A else Best, BestI = A, i end
		end
	end
	if not Best and Multi then
		SayBuy(string.format("The cheapest listing is one auction of %d at %s each. AF can't buy multi-item auctions yet: buy it in the Blizzard window.", Multi.qty, Core.MoneyColor(math.floor(Multi.buyout / Multi.qty))))
		return
	end
	if not Best then
		SayBuy("No listing at or under " .. Core.MoneyColor(F.buyUpTo) .. " right now. Re-checking...")
		Recheck({ E.id }, function() T.RefreshBuy() end)
		return
	end
	C_AuctionHouse.PlaceBid(Best.auctionID, Best.buyout)
	table.remove(List, BestI)
	Scan.Consume(E.id, Best.qty)
	RecordBuy(E.id, Best.qty, Best.buyout, F.resell)
	Buy.bought = (Buy.bought or 0) + Best.qty
	SayBuy(string.format("Bought %d for %s (%d of %d).", Best.qty, Core.MoneyColor(Best.buyout), Buy.bought, F.buyQty))
	if Buy.bought >= F.buyQty then BuyNext() else T.DrawBuy() end
end

local CraftPrice
local function OnPriceUpdated(Unit, Total)
	if Buy.state ~= "price" or not Buy.pending then return end
	local Pd = Buy.pending
	if Pd.craft then CraftPrice(Pd, Unit, Total) return end
	-- Resale from the data as it is now (not the price planned when the list was made), at the live cost. A vendor
	-- buy: the vendor pays a fixed price, so the profit is that minus the live cost.
	local R, Profit, MinProfit
	if Pd.vendor then
		R = { resell = Pd.resell }
		Profit, MinProfit = Pd.resell * Pd.qty - Total, Core.MinVendorProfit
	else
		local Now = Core.Info(Pd.id)
		R = Core.Resale(Now, Pd.qty, Total)
		Profit = R and R.profit
		if R then Pd.resell = R.resell end
		-- The return it needs depends on how fast it sells (slow sellers need more), from the data as it is now.
		MinProfit = Core.FlipNeed(Total, Core.MinFlipProfitFor(UI().FlipBudget()), Now)
	end
	local Budget = UI().FlipBudget()
	if Unit > Pd.max then
		ResetPurchase(true)
		SayBuy(string.format("Price went up: now %s each (max %s). Not bought.", Core.MoneyColor(Unit), Core.MoneyColor(Pd.max)))
		Recheck({ Pd.id }, function() T.RefreshBuy() end)
	elseif Total > Budget then
		ResetPurchase(true)
		SayBuy(string.format("Costs %s, over your flip budget (%s). Not bought.", Core.MoneyColor(Total), Core.MoneyColor(Budget)))
	elseif not R then
		ResetPurchase(true)
		SayBuy("The resale doesn't work any more on current data (the price fell or the item stopped selling well). Not bought.")
	elseif Profit < MinProfit then
		ResetPurchase(true)
		SayBuy(string.format("At today's price the expected profit would be %s (under %s). Not bought.", Core.MoneyColor(Profit), Core.MoneyColor(MinProfit)))
	else
		Buy.state = "confirm"
		Pd.total = Total
		T.SetBuyButton(BuyP.Buy, string.format("Confirm %d for %s", Pd.qty, Core.MoneyColor(Total)))
		SayBuy(string.format("Current price %s each. Click Confirm to buy.", Core.MoneyColor(Unit)))
	end
	T.DrawBuy()
end

-- While a scan runs (the server sends no progress while it prepares a full listing), keep the status line current.
local function ScanTicker(P)
	P.ScanTick = 0
	P:SetScript("OnUpdate", function(self, Elapsed)
		self.ScanTick = self.ScanTick + Elapsed
		if self.ScanTick < 0.5 then return end
		self.ScanTick = 0
		if Scan.Busy() then T.OnScanProgress() end
	end)
end
local function BuildBuy()
	BuyP = UI().NewAHPage("AF Buy", "AuctionForeverBuyTab", "AuctionForeverBuyPanel",
		function()
			T.LayoutBuy() -- the window may have another size now
			-- Rebuild only if there's new scan data or your gold changed since the list was made.
			if not Buy.loaded or Buy.money ~= GetMoney() then T.RefreshBuy() end
			T.SelectBuy(Buy.sel)
		end, function() ResetPurchase(true) end, function() T.RefreshBuyPrices() end)
	local P = BuyP
	ScanTicker(P)
	Text(P, "GameFontNormalLarge", 20, -14):SetText("AF Buy: flip targets")
	-- The summary lines 15 apart, then a clear gap before the table.
	P.Budget = Text(P, "GameFontHighlightSmall", 300, -8)
	P.Target = Text(P, "GameFontHighlightSmall", 300, -23)
	P.Results = Text(P, "GameFontHighlightSmall", 300, -38)
	P.Filters = {}
	for i = 1, 14 do
		local B = Button(P, "All", 14, FILTER_Y, 40, function(self) if self.key then T.SetBuyFilter(self.key) end end)
		B:SetHeight(20)
		B:Hide()
		P.Filters[i] = B
	end
	P.FilterNote = Text(P, "GameFontDisableSmall", 14, FILTER_Y - 5)
	P.Headers = Header(P, 14, HEAD_Y, BUY_COLS, BUY_NAMES, function(c) T.BuyHeaderClick(c) end, BUY_GAP)
	P.Rows = RowList(P, 14, PANE_TOP, BUY_W, ROWS, BUY_COLS, function(r) T.SelectBuy(r + (Buy.offset or 0)) end, BUY_GAP)
	P:EnableMouseWheel(true)
	P:SetScript("OnMouseWheel", function(_, Delta)
		Buy.offset = math.max(0, math.min(math.max(0, #Buy.rows - (Buy.visible or ROWS)), (Buy.offset or 0) - Delta * 3))
		T.DrawBuy()
	end)
	P.Bar = ScrollBar(P, 14 + BUY_W + 4, PANE_TOP, function(V) Buy.offset = V; T.DrawBuy() end)
	P.Empty = Text(P, "GameFontDisable", 20, PANE_TOP - 6, 600) -- one line in the table, where the first row would be
	-- Craft plans: only recipes you know, unless this is ticked.
	P.AllRecipes = CreateFrame("CheckButton", nil, P, "UICheckButtonTemplate")
	P.AllRecipes:SetSize(20, 20)
	P.AllRecipes:SetPoint("TOPRIGHT", P, "TOPRIGHT", -EDGE, -36)
	P.AllRecipes:SetChecked(UI().ShowAllRecipes())
	P.AllRecipes:SetScript("OnClick", function(self)
		UI().SetShowAllRecipes(not UI().ShowAllRecipes())
		self:SetChecked(UI().ShowAllRecipes())
		T.RefreshBuy()
	end)
	P.AllRecipesLabel = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.AllRecipesLabel:SetPoint("RIGHT", P.AllRecipes, "LEFT", -2, 0)
	P.AllRecipesLabel:SetJustifyH("RIGHT")
	P.AllRecipesLabel:SetText("Show all recipes")
	T.BuildPane(P)
	P.Skip = Button(P, "Next", 20, -420, 80, function() T.SelectBuy(Buy.sel + 1) end)
	-- Beside the buttons, centred on them and wide enough for two lines: a long message no longer runs down over
	-- the auction house's money/bid bar below the panel.
	P.Status = Text(P, "GameFontHighlightSmall", 320, -420, 350)
	P.Status:ClearAllPoints()
	P.Status:SetPoint("LEFT", P.Skip, "RIGHT", 12, 0)
	T.LayoutBuy()
	P:HookScript("OnSizeChanged", function() T.LayoutBuy(); T.DrawBuy() end)
end

-- AF Sell -----------------------------------------------------------------------------------------------------
local QUEUE_COLS = { 150, 40 }

local function SaySell(Msg) if SellP then SellP.Status:SetText(Msg or "") end end
local function Floor(G) return math.max(1, math.ceil((G.vendor or 0) / (1 - Core.Cut))) end
-- Lowest price that pays back what you paid for this item (nil if you didn't buy it with AF Buy).
local function PaidFloor(G) return G.cost and Core.CostFloor(G.cost) or nil end

-- Suggested price, amount and duration for one bag item.
local function Suggest(G)
	local I = G.info
	G.held, G.cost = Core.Holding(SaveDB(), G.id)
	local Lo = math.max(Floor(G), PaidFloor(G) or 0)
	-- The market stayed under what you paid all day, or it expired twice: price at the market (the loss is shown)
	-- instead of reposting at your cost and losing deposits.
	local Cut = PaidFloor(G) and Core.CutLoss(I, PaidFloor(G), SaveDB(), G.id)
	if Cut then Lo = Floor(G) end
	local Price, H, Idx, Qty, Flag = Core.SellPrice(I, G.count, Lo)
	-- Not a steady seller: never above what buyers have actually paid (the tooltip's AH price), even when the
	-- cheapest listing is far higher (nobody is buying at that price).
	local St = Core.Status(I)
	local Market = Core.Market(I)
	if Price and St ~= "good" and St ~= "early" and Market and Price > Market then Price, Flag = math.max(Lo, Market), "market" end
	if Cut and Price and Price < PaidFloor(G) then Flag = "cutloss" end
	if not Price then H, Idx, Price, Qty = 2, 1, math.max(Lo, Core.Market(I) or Lo), G.count end
	G.price, G.durIdx, G.qty, G.flag = math.max(Lo, math.floor(Price)), Idx, Qty, Flag
end
-- What AF Sell would suggest for Count of an item (the tooltip's Shift lines): price, duration index, how many.
function T.SuggestFor(id, Count)
	local I = Core.Info(id)
	if not I or not Count or Count < 1 then return nil end
	local G = { id = id, count = Count, info = I, vendor = UI().Vendor(id) }
	Suggest(G)
	return G
end

-- Items in the bags that sell on the auction house, grouped by item, most valuable first.
function T.BuildQueue()
	local Groups, Order = {}, {}
	for Bag = 0, LAST_BAG do
		for Slot = 1, C_Container.GetContainerNumSlots(Bag) or 0 do
			local Info = C_Container.GetContainerItemInfo(Bag, Slot)
			local id = Info and Info.itemID
			if id and not Info.isBound then
				local G = Groups[id]
				if not G then G = { id = id, count = 0, locs = {} }; Groups[id] = G; Order[#Order + 1] = G end
				G.count = G.count + (Info.stackCount or 1)
				G.locs[#G.locs + 1] = { Bag, Slot }
			end
		end
	end
	local Q = {}
	for _, G in ipairs(Order) do
		local I = Core.Info(G.id)
		G.vendor = UI().Vendor(G.id)
		-- Same advice as the item tooltip's Rec line: only what's worth selling on the auction house.
		if I and Core.Recommend(I, G.vendor, UI().TargetPrice(I)) == "Auction" then
			G.info = I
			Suggest(G)
			G.value = G.price * G.count
			Q[#Q + 1] = G
		end
	end
	table.sort(Q, function(a, b) return a.value > b.value end)
	return Q
end

function T.SellQueue() return Sell.queue end
function T.SelectedSell() return Sell.queue[Sell.idx] end
function T.SellIndex() return Sell.idx end

local function Copper(Box) return tonumber(Box:GetText()) or 0 end
function T.SellPrice()
	if not SellP then return nil end
	local C = Copper(SellP.Gold) * 10000 + Copper(SellP.Silver) * 100 + Copper(SellP.Copper)
	return C > 0 and math.floor(C) or nil
end
function T.SetSellPrice(C)
	C = math.floor(C or 0)
	SellP.Gold:SetText(tostring(math.floor(C / 10000)))
	SellP.Silver:SetText(tostring(math.floor(C / 100) % 100))
	SellP.Copper:SetText(tostring(C % 100))
	T.UpdateDeposit()
end
function T.SellDuration() return Sell.dur end
function T.SetSellDuration(Idx)
	Sell.dur = Idx
	for i, B in ipairs(SellP.Dur) do
		if i == Idx then B:LockHighlight() else B:UnlockHighlight() end
	end
	T.UpdateDeposit()
end

local function Location(G)
	local L1 = G.locs[1]
	local IL = rawget(_G, "ItemLocation") -- the game's; read safely in case it isn't loaded
	if not (IL and IL.CreateFromBagAndSlot and L1) then return nil end
	return IL:CreateFromBagAndSlot(L1[1], L1[2])
end

function T.UpdateDeposit()
	local G = T.SelectedSell()
	if not (SellP and G) then return end
	local Qty, Dur = tonumber(SellP.Qty:GetText()) or 0, Sell.dur or 1
	local D
	local Loc = Location(G)
	if Loc and Qty > 0 then
		local Kind = C_AuctionHouse.GetItemCommodityStatus and C_AuctionHouse.GetItemCommodityStatus(Loc)
		if Kind == COMMODITY and C_AuctionHouse.CalculateCommodityDeposit then D = C_AuctionHouse.CalculateCommodityDeposit(G.id, Dur, Qty)
		elseif Kind == ITEM and C_AuctionHouse.CalculateItemDeposit then D = C_AuctionHouse.CalculateItemDeposit(Loc, Dur, Qty) end
	end
	local Price = T.SellPrice()
	local Net = Price and Qty > 0 and math.floor(Price * Qty * (1 - Core.Cut)) or nil
	local Exp = ""
	if Price and Qty > 0 and G.info then
		local E, Ch = Core.ExpectedPost(G.info, Price, Qty, D, G.cost)
		Exp = string.format("     Expected %s: %s (%d%% sell)", G.cost and "profit" or "earnings",
			G.cost and Core.MoneyDelta(E) or Core.MoneyColor(E), math.floor(Ch * 100 + 0.5))
	end
	SellP.Deposit:SetText(string.format("Deposit: %s     You get after the cut: %s%s", D and Core.MoneyColor(D) or "-", Net and Core.MoneyColor(Net) or "-", Exp))
end

-- Redraw whichever of our AH panels is open (item names arriving from the server).
function T.RedrawNames()
	if BuyP and BuyP:IsShown() then T.DrawBuy() end
	if SellP and SellP:IsShown() then T.DrawSell() end
end

function T.DrawSell()
	if not SellP then return end
	local Off = SyncBar(SellP.Bar, Sell.offset, #Sell.queue)
	Sell.offset = Off
	for i, R in ipairs(SellP.QueueRows) do
		local G = Sell.queue[i + Off]
		R:SetShown(G ~= nil)
		R.id = G and G.id
		if G then
			R.Icon:SetTexture(UI().Icon(G.id))
			R.Cells[1]:SetText(NameText(G.id, true))
			R.Cells[2]:SetText("x" .. G.count)
			R.Sel:SetShown(i + Off == Sell.idx)
		end
	end
	local G = T.SelectedSell()
	SellP.Empty:SetShown(G == nil)
	SellP.Post:SetEnabled(G ~= nil)
	SellP.Skip:SetEnabled(G ~= nil)
	if not G then
		SellP.Name:SetText("")
		SellP.Info:SetText("")
		return
	end
	local I = G.info
	SellP.Name:SetText(NameText(G.id))
	local Line = string.format("In your bags: %d     Market: %s     Sells about %.0f an hour     Status: %s",
		G.count, Core.MoneyColor(Core.Market(I)), I.perHour or 0, UI().StatusText(Core.Status(I)))
	if G.cost then
		local Price = T.SellPrice() or G.price
		local Each = math.floor(Price * (1 - Core.Cut)) - G.cost
		Line = Line .. string.format("\nYou paid %s each (%d bought). At this price: %s%s each.", Core.MoneyColor(G.cost), G.held,
			Each >= 0 and "|cff1eff00profit|r " or "|cffff4040loss|r ", Core.MoneyColor(math.abs(Each)))
	end
	local Hint = {
		loss = "|cffff4040Being the cheapest would sell below your floor (vendor or what you paid): holding may be better.|r",
		flooding = "|cffffd100More is being posted than sold: priced 1c under the cheapest; prices may keep falling.|r",
		guess = "New listings per hour not measured yet: priced 1c under the cheapest to be safe.",
		market = "|cffffd100Not a steady seller: priced at what buyers have recently paid, not under the (higher) cheapest listing.|r",
		cutloss = "|cffff4040The market has stayed under what you paid (all day, or it expired twice): priced at the market to cut the loss. Or keep it and wait.|r",
	}
	SellP.Hint:SetText(Hint[G.flag or ""] or "Prefilled: the highest price that still sells within 2 h with other sellers posting.")
	SellP.Info:SetText(Line)
end

-- Fill the fields with the suggestion for the selected item.
local function FillFields()
	local G = T.SelectedSell()
	Sell.pending = nil
	if SellP then SellP.Post:SetText("Post") end
	if not (SellP and G) then T.DrawSell() return end
	T.SetSellPrice(G.price)
	SellP.Qty:SetText(tostring(G.qty))
	T.SetSellDuration(G.durIdx or 1)
	T.DrawSell()
end

-- Rebuild the queue (prices may have changed) and keep the selected item selected.
local function Rebuild(KeepFields)
	local Id = T.SelectedSell() and T.SelectedSell().id
	Sell.queue = T.BuildQueue()
	Sell.idx = 1
	for i, G in ipairs(Sell.queue) do if G.id == Id then Sell.idx = i end end
	if KeepFields then T.DrawSell() else FillFields() end
end

function T.SelectSell(i)
	if #Sell.queue == 0 then FillFields() return end
	Sell.idx = ((i - 1) % #Sell.queue) + 1 -- wraps from the end back to the start
	FillFields()
	local G = T.SelectedSell()
	-- The one live check: the item you're about to post, if your data on it is over 2 min old.
	if G and IsStale(G.id) then
		local Id = G.id
		SaySell("Checking the current price...")
		Recheck({ Id }, function()
			if T.SelectedSell() and T.SelectedSell().id == Id and not Sell.edited then Rebuild(false) else Rebuild(true) end
			SaySell("")
		end)
	end
	Sell.edited = false
end
function T.RefreshSellPrices()
	local Ids = {}
	for _, G in ipairs(Sell.queue) do Ids[#Ids + 1] = G.id end
	if #Ids == 0 then return end
	if Recheck(Ids, function() Rebuild(Sell.edited); SaySell("Prices refreshed.") end) then SaySell("Refreshing prices for " .. #Ids .. " items...") end
end
function T.SelectSellId(id)
	for i, G in ipairs(Sell.queue) do if G.id == id then T.SelectSell(i) return true end end
	return false
end

-- Your posts, kept 30 days, so your own listings aren't counted as other sellers posting (Core.MergeScan).
local POST_DAYS = 30
local function RememberPost(id, Qty, Price)
	local DB = SaveDB()
	DB.myposts = DB.myposts or {}
	local Now = time()
	table.insert(DB.myposts, { Now, id, Qty, Price })
	local Kept = {}
	for _, R in ipairs(DB.myposts) do if R[1] >= Now - POST_DAYS * 86400 then Kept[#Kept + 1] = R end end
	DB.myposts = Kept
end
local function AfterPost(Qty, Price)
	local G = T.SelectedSell()
	if G and Price then RememberPost(G.id, Qty, Price) end
	if G then
		G.count = G.count - Qty
		if G.count <= 0 then table.remove(Sell.queue, Sell.idx); Sell.idx = Sell.idx - 1 end
	end
	T.SelectSell(Sell.idx + 1)
end

function T.PostClick()
	local G = T.SelectedSell()
	if not G then return end
	if Sell.pending then
		local Pd = Sell.pending
		Sell.pending = nil
		SellP.Post:SetText("Post")
		if Pd.commodity then C_AuctionHouse.ConfirmPostCommodity(Pd[1], Pd[2], Pd[3], Pd[4])
		else C_AuctionHouse.ConfirmPostItem(Pd[1], Pd[2], Pd[3], nil, Pd[4]) end
		SaySell(string.format("Posted %d at %s each.", Pd[3], Core.MoneyColor(Pd[4])))
		AfterPost(Pd[3], Pd[4])
		return
	end
	local Price, Qty, Dur = T.SellPrice(), tonumber(SellP.Qty:GetText()), Sell.dur or 1
	if not Price then SaySell("Enter a price.") return end
	if Price < Floor(G) then SaySell("That's below what the vendor pays (" .. Core.MoneyColor(Floor(G)) .. " after the cut). Not posted.") return end
	if PaidFloor(G) and Price < PaidFloor(G) and Sell.lossOk ~= G.id then
		Sell.lossOk = G.id
		SaySell("That's below what you paid (" .. Core.MoneyColor(PaidFloor(G)) .. " after the cut). Click Post again to sell at a loss.")
		return
	end
	Sell.lossOk = nil
	Qty = Qty and math.floor(Qty)
	if not Qty or Qty < 1 then SaySell("Enter how many to post.") return end
	if Qty > G.count then SaySell("You only have " .. G.count .. ".") return end
	local Loc = Location(G)
	if not Loc then SaySell("Couldn't find the item in your bags.") return end
	local Kind = C_AuctionHouse.GetItemCommodityStatus(Loc)
	local Needs
	if Kind == COMMODITY then
		Needs = C_AuctionHouse.PostCommodity(Loc, Dur, Qty, Price)
	elseif Kind == ITEM then
		Needs = C_AuctionHouse.PostItem(Loc, Dur, Qty, nil, Price)
	else
		SaySell("The game hasn't loaded this item's details yet; try again in a second.")
		return
	end
	if Needs then
		Sell.pending = { Loc, Dur, Qty, Price, commodity = Kind == COMMODITY }
		SellP.Post:SetText("Confirm post")
		SaySell("The game asks for confirmation (the price is far from the market). Click Confirm post to post anyway.")
		return
	end
	SaySell(string.format("Posted %d at %s each.", Qty, Core.MoneyColor(Price)))
	AfterPost(Qty, Price)
end

local function MoneyBox(Parent, X, Y, W, Suffix)
	local B = CreateFrame("EditBox", nil, Parent, "InputBoxTemplate")
	B:SetSize(W, 20)
	B:SetPoint("TOPLEFT", X, Y)
	B:SetAutoFocus(false)
	B:SetNumeric(true)
	B:SetScript("OnTextChanged", function(_, User) if User then Sell.edited = true; T.UpdateDeposit(); T.DrawSell() end end)
	B:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
	local S = Parent:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	S:SetPoint("LEFT", B, "RIGHT", 2, 0)
	S:SetText(Suffix)
	return B
end

local function BuildSell()
	SellP = UI().NewAHPage("AF Sell", "AuctionForeverSellTab", "AuctionForeverSellPanel", function()
		-- The queue comes from your bags and your scans; only the selected item gets a live price check.
		Sell.queue = T.BuildQueue()
		Sell.edited = false
		T.SelectSell(1)
	end, nil, function() T.RefreshSellPrices() end)
	local P = SellP
	ScanTicker(P)
	Text(P, "GameFontNormalLarge", 20, -14):SetText("AF Sell")
	Text(P, "GameFontNormalSmall", 20, -44):SetText("Your items that sell here (click one)")
	P.QueueRows = RowList(P, 14, -60, 230, ROWS, QUEUE_COLS, function(r) T.SelectSell(r + (Sell.offset or 0)) end)
	P:EnableMouseWheel(true)
	P:SetScript("OnMouseWheel", function(_, Delta)
		Sell.offset = math.max(0, math.min(math.max(0, #Sell.queue - ROWS), (Sell.offset or 0) - Delta * 3))
		T.DrawSell()
	end)
	P.Bar = ScrollBar(P, 248, -60, function(V) Sell.offset = V; T.DrawSell() end)
	P.Empty = Text(P, "GameFontHighlight", 20, -64, 220)
	P.Empty:SetText("Nothing in your bags sells here for more than the vendor pays.")
	local X = 270
	P.Name = Text(P, "GameFontNormalLarge", X, -60, 480)
	P.Info = Text(P, "GameFontHighlightSmall", X, -86, 480)
	Text(P, "GameFontNormal", X, -120):SetText("Price each")
	P.Gold = MoneyBox(P, X + 100, -116, 50, "g")
	P.Silver = MoneyBox(P, X + 170, -116, 30, "s")
	P.Copper = MoneyBox(P, X + 220, -116, 30, "c")
	Text(P, "GameFontNormal", X, -152):SetText("How many")
	P.Qty = MoneyBox(P, X + 100, -148, 50, "")
	Text(P, "GameFontNormal", X, -184):SetText("Duration")
	P.Dur = {}
	for i, H in ipairs(Core.Durations) do
		P.Dur[i] = Button(P, H .. " h", X + 100 + (i - 1) * 70, -180, 64, function() T.SetSellDuration(i) end)
	end
	P.Deposit = Text(P, "GameFontHighlightSmall", X, -216, 600)
	P.Hint = Text(P, "GameFontDisableSmall", X, -236, 480)
	P.Hint:SetText("Prefilled from recent sales: the best price that should sell within the duration.")
	P.Post = Button(P, "Post", X, -270, 160, function() T.PostClick() end)
	P.Skip = Button(P, "Skip", X + 170, -270, 90, function() T.SelectSell(Sell.idx + 1) end)
	P.Status = Text(P, "GameFontHighlightSmall", X, -304, 480)
end

-- Craft plans ---------------------------------------------------------------------------------------------------
local function ItemName(id) return (UI().ItemName(id)) end
local function Profession(E) return E.craft.skillName or "profession" end
function T.HoursText(Secs)
	if Secs >= 3600 then return string.format("%.0fh", Secs / 3600) end
	return string.format("%.0fmin", math.max(1, Secs / 60))
end
-- Status column: "craft: First Aid 225" (the recipe's required rank; trainer recipes have none).
function T.CraftStatus(E)
	local R = E.craft
	if E.flip.onCooldown then return string.format("|cff808080on cooldown %s|r", T.HoursText(E.flip.onCooldown)) end
	if E.flip.blocked then return "|cff808080" .. E.flip.blocked .. "|r" end
	local Text = "craft: " .. Profession(E) .. ((R.req or 0) > 0 and (" " .. R.req) or "")
	if not E.known then Text = "|cff808080" .. Text .. "|r" end
	return Text
end
-- What AF knows about you and the recipe (see UI.RecipeKnown).
local Money = Core.MoneyColor
-- How AF knows you have the recipe, short, for the panel header (see UI.RecipeKnown).
local function KnownShort(E)
	if E.known and E.knownHow == "spell" then return "you know it" end
	if E.known and E.knownHow == "window" then return "known: seen in your " .. Profession(E) .. " window" end
	if E.known then return "probably known: your " .. Profession(E) .. " is " .. (E.rank or 0) end
	return "|cffffd100not known|r"
end
local function NotKnownLine(E)
	local P, R = Profession(E), E.craft
	local Why
	if E.knownHow == "window" then Why = "not learned in your " .. P .. " window"
	elseif E.rank then Why = "your " .. P .. " is " .. E.rank .. ", the recipe needs " .. (R.req or 0)
	else Why = "you don't have " .. P end
	return "|cffffd100You don't know this recipe (" .. Why .. "); shown because Show all recipes is on.|r"
end

-- Buying a craft plan's mats: each AH mat has its own Buy button on its line in the panel, which buys exactly the
-- plan's quantity of it (what's left of it after a partial buy) with its own live price check and Confirm click,
-- like a commodity flip. It cancels when the live price is over the line's "pay up to" (the plan's max for that
-- mat), or the craft no longer pays at the live prices. The plan is kept while you buy (the list may be re-planned
-- meanwhile). When every AH mat is bought, the product is recorded as a purchase (crafts x makes units for what the
-- mats cost, vendor goods included), so AF Sell knows what the crafted items cost you; a run left part way (another
-- craft's mats, or the auction house closed) records the mats bought so far as purchases of those mats instead.
-- Crafting itself is up to you.
-- Run = { key, id, spell, plan, status, bought = { [mat index] = qty }, spent, got = { {id, qty, total} } }
local function RunKey(E) return E.id .. ":" .. (E.craft.spell or 0) end
function T.CraftRun() return Run end
function T.LastCraftRun() return LastRun end
function T.BuyVisible() return Buy.visible end
-- The option the panel shows and buys, and the craft run it belongs to (if any).
local function PlanOf(E)
	if not E.craft then return Shown(E), nil end
	local K = RunKey(E)
	local R = (Run and Run.key == K and Run) or (LastRun and LastRun.key == K and LastRun) or nil
	return R and R.plan or E.flip, R
end
-- Panel text above the lines: what it is (craft: product x N, profession, how known), then the evidence.
function T.PaneText(E)
	local F = PlanOf(E)
	if not E.craft then
		local Need = ShownNeed(E)
		local Out = NameText(E.id) .. "\n" .. TierLine(F) .. (F.vendor and "" or (", " .. SellsText(E))) -- a vendor sale is sure
		if F.slow then Out = Out .. "\n|cffffd100Slow seller: sales come in bursts or often expire, so it may take longer to sell than planned.|r" end
		if Need then
			Out = Out .. "\n" .. (F.vendor and ("Needs " .. GoldText(Need) .. " gold (the cost plus the " .. Money(Core.MinKeep) .. " always kept).")
				or ("A target once you have " .. GoldText(Need) .. " gold (the flip budget is your gold minus " .. Money(Core.MinKeep) .. "; one item may use only part of it)."))
		end
		return Out
	end
	local R = E.craft
	local Head = string.format("%s x%d   %s%s (%s)", NameText(E.id), F.crafts, Profession(E), (R.req or 0) > 0 and (" " .. R.req) or "", KnownShort(E))
	local Ev = TierLine(F) .. ", " .. (F.route == "Vendor" and "sold to a vendor"
		or (SellsText(E) .. string.format(" (based on %d sales in %d h%s)", F.sales or 0, F.salesHours or 0, F.capped and ", priced at what buyers paid" or "")))
	if F.cooldown and F.cooldown > 0 then
		Ev = Ev .. string.format(", cooldown %s%s", T.HoursText(F.cooldown), F.onCooldown and (": ready in " .. T.HoursText(F.onCooldown)) or "")
	end
	if F.blocked == "flooded" then
		Ev = Ev .. "\n|cffffd100Flooded: far more is being posted than sold, so AF doesn't plan to sell it on the AH (shown because Show all recipes is on).|r"
	elseif F.blocked == "over budget" then
		Ev = Ev .. "\n|cffffd100One craft's mats cost more than this item's share of your flip budget (shown because Show all recipes is on).|r"
	elseif F.blocked == "over target" then
		Ev = Ev .. "\n|cffffd100Listed mats cost more than the Pay up to prices: no profit today (shown because Show all recipes is on). Buy under them, or wait.|r"
	elseif F.blocked then
		Ev = Ev .. "\n|cffffd100Product " .. F.blocked .. ": not sold on the AH by a craft plan (shown because Show all recipes is on).|r"
	end
	if not E.known then Ev = Ev .. "\n" .. NotKnownLine(E) end
	return Head .. "\n" .. Ev
end
-- One line per source line of the plan (AH, Vendor, Owned, Bank order); a flip: one line, the item.
-- { kind ("flip" / "AH" / "Vendor" / "Owned" / "Bank"), id, qty, source, upTo (AH: pay up to; Vendor: price each),
-- listed (the cheapest price listed now, each), cost, mat (AH: index in plan.mats), bought (AH: units bought so far),
-- have }.
local function Cheapest(I)
	local L = I and I.ladder
	if type(L) == "table" and L[1] then return L[1][1] end
	return I and I.qty and I.qty > 0 and I.low or nil
end
T.Cheapest = Cheapest
function T.PaneLines(E)
	local F, R = PlanOf(E)
	if not E.craft then
		return { { kind = "flip", id = E.id, qty = F.buyQty, source = "AH", upTo = F.buyUpTo, listed = Cheapest(E.info or Core.Info(E.id)), cost = F.cost } }
	end
	local Out, Bags = {}, nil
	for _, X in ipairs(UI().BySource(F.list or {})) do
		local L = { kind = X.source, id = X.id, qty = X.qty, source = X.source, cost = X.cost }
		if X.source == "AH" then
			L.upTo, L.listed = X.target or X.upTo, Cheapest(Core.Info(X.id))
			for m, M in ipairs(F.mats) do if M.id == X.id then L.mat = m end end
			L.bought = R and R.bought and R.bought[L.mat] or 0
		elseif X.source == "Vendor" then
			L.upTo = X.each
		elseif X.source == "Owned" then
			Bags = Bags or UI().BagCounts()
			L.have = Bags[X.id] or X.qty
		elseif X.source == "Bank" then
			L.have = UI().BankCount(X.id)
		end
		Out[#Out + 1] = L
	end
	return Out
end
-- The summary under the lines: what to do, the money, what it leaves you.
function T.PaneSummary(E)
	local F, R = PlanOf(E)
	local Tier, Color, Ret = T.Tier(F)
	local Then
	if F.craft then
		local Makes = F.makes > 1 and (" (makes " .. F.units .. ")") or ""
		if F.route == "Vendor" then
			Then = string.format("Craft %d%s, then Vendor for %s each (%s)", F.crafts, Makes, Money(F.resell), Money(F.resell * F.units))
		else
			Then = string.format("Craft %d%s, then Auction at %s each (after cut %s)", F.crafts, Makes, Money(F.resell or 0),
				Money(math.floor((F.resell or 0) * (1 - Core.Cut)) * F.units))
		end
	elseif F.vendor then
		local N = F.purchases or 1
		Then = string.format("Then: Vendor for %s each (%s, no AH cut), bought in %d purchase%s", Money(F.resell), Money(F.resell * F.buyQty), N, N == 1 and "" or "s")
	else
		Then = string.format("Then: Auction at %s each over %d h (after cut %s)", Money(F.resell), F.hours or 0, Money(math.floor(F.resell * (1 - Core.Cut)) * F.buyQty))
	end
	-- Still to pay: the AH mats not bought yet (at the plan's prices) and the vendor goods.
	local ToPay = F.cost or 0
	if R and R.bought then
		ToPay = F.vendorCost or 0
		for m, M in ipairs(F.mats) do ToPay = ToPay + M.cost * math.max(0, 1 - (R.bought[m] or 0) / math.max(1, M.qty)) end
	end
	local Out = Then .. "\n" .. string.format("%s %s   Profit %s (%s%s|r, %d%% return)   Leaves you %s", F.craft and "Mats" or "Cost", Money(F.cost),
		Core.MoneyDelta(F.profit), Color, Tier, math.floor((Ret or 0) * 100 + 0.5), Money(math.floor(GetMoney() - ToPay)))
	if F.craft then
		Out = Out .. "\n" .. string.format("Per craft: mats %s, sells %s (%s), profit %s", Money(F.craftCost or 0), Money(F.craftSale or 0),
			F.route == "Vendor" and "Vendor" or "Auction", Core.MoneyDelta(F.craftProfit or 0))
	end
	return Out
end
local function TextLines(S) local N = 1 for _ in S:gmatch("\n") do N = N + 1 end return N end
-- Panel lines take one 20 px slot each; a line you buy from (an AH mat, a flip) takes a second one, for its Buy
-- button under it.
local function Slots(L) return (L.kind == "AH" or L.kind == "flip") and 2 or 1 end
function T.PaneSlots(Lines)
	local N = 0
	for _, L in ipairs(Lines) do N = N + Slots(L) end
	return N
end
-- The panel for a row: its text, lines and summary, its height, and the table rows that fit above it. Lines that
-- don't fit (with the table at PANE_MIN_ROWS) collapse: Owned/Bank lines first into one "Owned/Bank: ..." line,
-- then the last ones into a "+N more" line. Fit counts slots (see Slots).
function T.PaneModel(E)
	local M = { detail = T.PaneText(E), summary = T.PaneSummary(E), lines = T.PaneLines(E) }
	M.top = 4 + TextLines(M.detail) * PANE_TEXT_H + 2 -- the column headers
	local Fixed = M.top + PANE_TEXT_H + 4 + 3 * PANE_TEXT_H + 2
	local Fit = math.floor((PANE_SPACE - 4 - PANE_MIN_ROWS * ROW_H - Fixed) / PANE_LINE_H)
	Fit = math.max(2, math.min(Fit, PANE_MAX_LINES))
	if T.PaneSlots(M.lines) > Fit then
		local Keep, Held = {}, {}
		for _, L in ipairs(M.lines) do
			if L.kind == "Owned" or L.kind == "Bank" then Held[#Held + 1] = L else Keep[#Keep + 1] = L end
		end
		if #Held > 0 then Keep[#Keep + 1] = { kind = "held", parts = Held } end
		if T.PaneSlots(Keep) > Fit then
			local More = 0
			while #Keep > 0 and T.PaneSlots(Keep) + 1 > Fit do
				table.remove(Keep)
				More = More + 1
			end
			Keep[#Keep + 1] = { kind = "more", n = More }
		end
		M.lines = Keep
	end
	M.fit = Fit
	M.slots = T.PaneSlots(M.lines)
	M.height = Fixed + M.slots * PANE_LINE_H
	M.rows = math.max(PANE_MIN_ROWS, math.min(ROWS, math.floor((PANE_SPACE - 4 - M.height) / ROW_H)))
	return M
end
-- Rough text width when the game can't measure it (offline): 6 per character, color codes and textures left out.
local function TextWidth(FS, Str)
	local W = FS and FS.GetStringWidth and FS:GetStringWidth()
	if type(W) == "number" and W > 0 then return W end
	Str = tostring(Str or ""):gsub("|T.-|t", "  "):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")
	return #Str * 6
end
T.TextWidth = TextWidth
-- A panel line's Buy button: Verb, then the quantity and the item's name, shortened ("...") so the button stays
-- within BTN_MAX; the button as wide as its label (BTN_MIN at least).
function T.SetBuyButton(B, Label, Name)
	local Full = Name and (Label .. " " .. Name) or Label
	B:SetText(Full)
	local FS = B.GetFontString and B:GetFontString()
	local W = TextWidth(FS, Full) + 20
	if Name and W > BTN_MAX then
		local Short = Name
		while #Short > 1 and W > BTN_MAX do
			Short = Short:sub(1, -2)
			Full = Label .. " " .. Short .. "..."
			B:SetText(Full)
			W = TextWidth(FS, Full) + 20
		end
	end
	B:SetSize(math.max(BTN_MIN, math.min(BTN_MAX, math.floor(W + 0.5))), BTN_H)
end
function T.BuildPane(P)
	local Pane = CreateFrame("Frame", nil, P)
	Pane:SetSize(BUY_W, 200)
	Pane:SetPoint("TOPLEFT", P, "TOPLEFT", 14, PANE_TOP - ROWS * ROW_H)
	Pane.Bg = Pane:CreateTexture(nil, "BACKGROUND")
	Pane.Bg:SetAllPoints()
	Pane.Bg:SetColorTexture(0, 0, 0, 0.3)
	P.Pane = Pane
	P.Detail = Pane:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	P.Detail:SetPoint("TOPLEFT", Pane, "TOPLEFT", 6, -4)
	P.Detail:SetWidth(BUY_W - 12)
	P.Detail:SetJustifyH("LEFT")
	P.PaneHead = {}
	for c in ipairs(PANE_COLS) do
		local H = Pane:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
		H:SetJustifyH("LEFT")
		H:SetWordWrap(false)
		H:SetText(PANE_NAMES[c])
		P.PaneHead[c] = H
	end
	P.Lines = {}
	for i = 1, PANE_MAX_LINES do
		local W = CreateFrame("Frame", nil, Pane)
		W:SetSize(BUY_W, PANE_LINE_H)
		W.Icon = W:CreateTexture(nil, "ARTWORK")
		W.Icon:SetSize(16, 16)
		W.Icon:SetPoint("TOPLEFT", W, "TOPLEFT", 4, -2)
		W.Cells = {}
		for c in ipairs(PANE_COLS) do
			local FS = W:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
			FS:SetJustifyH("LEFT")
			FS:SetWordWrap(false)
			FS:SetMaxLines(1)
			W.Cells[c] = FS
		end
		W.Wide = W:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
		W.Wide:SetJustifyH("LEFT")
		W.Wide:SetWordWrap(false)
		W.Wide:SetMaxLines(1)
		-- The Buy button on its own line, under the Reagent column; "bought ..." to its right.
		W.Btn = CreateFrame("Button", nil, W, "UIPanelButtonTemplate")
		W.Btn:SetSize(BTN_MIN, BTN_H)
		W.Btn:SetText("Buy")
		W.Btn:SetScript("OnClick", function() T.BuyMat(W.mat) end)
		W.Note = W:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
		W.Note:SetJustifyH("LEFT")
		W.Note:SetWordWrap(false)
		W.Note:SetMaxLines(1)
		P.Lines[i] = W
	end
	-- A flip's Buy button: on the line under its one item line, like a mat's ("Confirm 20 for 1g 05s 00c").
	P.Buy = CreateFrame("Button", nil, P.Lines[1], "UIPanelButtonTemplate")
	P.Buy:SetSize(BTN_MIN, BTN_H)
	P.Buy:SetText("Buy")
	P.Buy:SetScript("OnClick", function() T.BuyClick() end)
	P.Summary = Pane:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	P.Summary:SetWidth(BUY_W - 12)
	P.Summary:SetJustifyH("LEFT")
end
-- Size everything on the AF Buy page from the page's width (the auction house window's inside): the table's
-- columns, rows, scroll bar, the summary lines, the filter bar's room, the panel and its columns.
function T.PageWidth()
	local W = BuyP and BuyP:GetWidth()
	if type(W) ~= "number" or W < 200 then W = PAGE_W_DEFAULT end
	return W
end
function T.LayoutBuy()
	local P = BuyP
	if not P then return end
	local PW = T.PageWidth()
	BUY_W = math.floor(PW - 14 - SCROLL_W - EDGE)
	local Cols = FitCols(BUY_BASE, BUY_MIN, BUY_W - 24 - BUY_GAP * (#BUY_BASE - 1), { 1, 7 })
	for c, W in ipairs(Cols) do BUY_COLS[c] = W end
	local CX = 24
	for c, W in ipairs(BUY_COLS) do
		local H = P.Headers[c]
		H:SetWidth(W)
		H:ClearAllPoints()
		H:SetPoint("TOPLEFT", P, "TOPLEFT", 14 + CX, HEAD_Y + 2)
		if H.Label then H.Label:SetWidth(W); H.Label:SetWordWrap(false) end
		for _, R in ipairs(P.Rows) do
			local FS = R.Cells[c]
			FS:ClearAllPoints()
			FS:SetPoint("LEFT", R, "LEFT", CX, 0)
			FS:SetWidth(W)
		end
		CX = CX + W + BUY_GAP
	end
	for _, R in ipairs(P.Rows) do R:SetWidth(BUY_W) end
	P.Bar:ClearAllPoints()
	P.Bar:SetPoint("TOPLEFT", P, "TOPLEFT", 14 + BUY_W + 4, PANE_TOP)
	P.Empty:SetWidth(math.min(600, BUY_W - 6))
	-- The summary lines (from x 300); the third shares its row with "Show all recipes" at the right edge.
	local Box = 20 + 2 + TextWidth(P.AllRecipesLabel, "Show all recipes") + 8
	for _, FS in ipairs({ P.Budget, P.Target }) do FS:SetWidth(math.max(100, PW - 300 - EDGE)) end
	P.Results:SetWidth(math.max(100, PW - 300 - EDGE - Box))
	-- The panel.
	local Pane = P.Pane
	Pane:SetWidth(BUY_W)
	P.Detail:SetWidth(BUY_W - 12)
	P.Summary:SetWidth(BUY_W - 12)
	local PCols = FitCols(PANE_BASE, PANE_MIN, BUY_W - 24 - PANE_GAP * (#PANE_BASE - 1) - 4, { 2 })
	-- (with room to spare, the columns keep their base widths; the space after them is the note's)
	if BUY_W - 24 - PANE_GAP * (#PANE_BASE - 1) - 4 > Sum(PANE_BASE) then PCols = { unpack(PANE_BASE) } end
	for c, W in ipairs(PCols) do PANE_COLS[c] = W end
	local X = 24
	for c, W in ipairs(PANE_COLS) do
		P.PaneHead[c].x = X
		P.PaneHead[c]:SetWidth(W)
		for _, Ln in ipairs(P.Lines) do
			local FS = Ln.Cells[c]
			FS:ClearAllPoints()
			FS:SetPoint("TOPLEFT", Ln, "TOPLEFT", X, -4)
			FS:SetWidth(W)
		end
		X = X + W + PANE_GAP
	end
	P.PaneEnd = X -- after the last column: a line's note ("buy from a vendor", "you have 4")
	P.BtnX = 24 + PANE_COLS[1] + PANE_GAP -- the Buy buttons: under the Reagent column
	for _, Ln in ipairs(P.Lines) do
		Ln:SetWidth(BUY_W)
		Ln.Wide:ClearAllPoints()
		Ln.Wide:SetPoint("TOPLEFT", Ln, "TOPLEFT", 24, -4)
		Ln.Wide:SetWidth(BUY_W - 30)
		Ln.Btn:ClearAllPoints()
		Ln.Btn:SetPoint("TOPLEFT", Ln, "TOPLEFT", P.BtnX, -PANE_LINE_H - 1)
	end
	P.Buy:ClearAllPoints()
	P.Buy:SetPoint("TOPLEFT", P.Lines[1], "TOPLEFT", P.BtnX, -PANE_LINE_H - 1)
end
local function Owned(K) return K == "Owned" or K == "Bank" end
-- A line's note: right of its Buy button (on the button's line), else after the last column.
local function PlaceNote(W, Btn)
	local P = BuyP
	W.Note:ClearAllPoints()
	if Btn then
		W.Note:SetPoint("LEFT", Btn, "RIGHT", 6, 0)
		W.Note:SetWidth(math.max(20, BUY_W - P.BtnX - Btn:GetWidth() - 6 - 4))
	else
		W.Note:SetPoint("TOPLEFT", W, "TOPLEFT", P.PaneEnd, -4)
		W.Note:SetWidth(math.max(20, BUY_W - P.PaneEnd - 4))
	end
end
local function ShortItem(id) return UI().ShortName((UI().ItemName(id))) end
function T.DrawPane(E, M)
	local P = BuyP
	local Pane = P.Pane
	Pane:SetShown(E ~= nil)
	if not E then P.Detail:SetText(""); P.Summary:SetText("") return end
	Pane:ClearAllPoints()
	Pane:SetPoint("TOPLEFT", P, "TOPLEFT", 14, PANE_TOP - M.rows * ROW_H - 4)
	Pane:SetHeight(M.height)
	P.Detail:SetText(M.detail)
	for _, H in ipairs(P.PaneHead) do
		H:ClearAllPoints()
		H:SetPoint("TOPLEFT", Pane, "TOPLEFT", H.x, -M.top)
	end
	P.PaneHead[2]:SetText(E.craft and "Reagent" or "Item")
	local Y = -M.top - PANE_TEXT_H
	local F, R = PlanOf(E)
	local Busy = Buy.state ~= nil
	local Blocked = E.craft and (F.onCooldown or F.blocked)
	local Slot = 0
	for i, W in ipairs(P.Lines) do
		local L = M.lines[i]
		W:SetShown(L ~= nil)
		W.mat = nil
		if L then
			W:ClearAllPoints()
			W:SetPoint("TOPLEFT", Pane, "TOPLEFT", 0, Y - Slot * PANE_LINE_H)
			W:SetHeight(Slots(L) * PANE_LINE_H)
			Slot = Slot + Slots(L)
			for c = 1, #PANE_COLS do W.Cells[c]:SetText("") end
			W.Wide:SetText("")
			W.Note:SetText("")
			W.Btn:Hide()
			PlaceNote(W)
			W.Icon:SetTexture(L.id and UI().Icon(L.id) or nil)
			if L.kind == "held" then
				local Parts = {}
				for _, H in ipairs(L.parts) do Parts[#Parts + 1] = H.qty .. " " .. ItemName(H.id) .. " (" .. H.kind .. ")" end
				W.Wide:SetText(UI().SourceText("Owned") .. "/Bank: " .. table.concat(Parts, ", "))
			elseif L.kind == "more" then
				W.Wide:SetText(string.format("+%d more: buy them in the Blizzard window", L.n))
			else
				W.Cells[1]:SetText(tostring(L.qty))
				W.Cells[2]:SetText(NameText(L.id))
				W.Cells[3]:SetText(UI().SourceText(L.source))
				W.Cells[4]:SetText(Owned(L.kind) and "-" or Money(L.upTo))
				W.Cells[5]:SetText(L.listed and Money(L.listed) or "-")
				W.Cells[6]:SetText(Owned(L.kind) and "-" or Money(L.cost))
				if L.kind == "AH" then
					W.mat = L.mat
					W.Btn:Show()
					local Pend = R and R == Run and Buy.pending and Buy.pending.craft and Buy.pending.mat == L.mat
					local Left = math.max(0, L.qty - L.bought)
					if L.bought >= L.qty then
						T.SetBuyButton(W.Btn, "Buy " .. L.qty, ShortItem(L.id))
						W.Btn:SetEnabled(false)
						W.Note:SetText("|cff1eff00bought|r")
					else
						if L.bought > 0 then W.Note:SetText(string.format("|cffffd100bought %d of %d|r", L.bought, L.qty)) end
						if Pend and Buy.state == "confirm" then
							T.SetBuyButton(W.Btn, "Confirm " .. Left, ShortItem(L.id))
							W.Btn:SetEnabled(true)
						elseif Pend then
							T.SetBuyButton(W.Btn, "...")
							W.Btn:SetEnabled(false)
						else
							T.SetBuyButton(W.Btn, (L.bought > 0 and "Buy rest " or "Buy ") .. Left, ShortItem(L.id))
							W.Btn:SetEnabled(not Busy and not Blocked and not (R and R == LastRun))
						end
					end
					PlaceNote(W, W.Btn)
				elseif L.kind == "Vendor" then
					W.Note:SetText("buy from a vendor")
				elseif Owned(L.kind) then
					W.Note:SetText("you have " .. (L.have or L.qty))
				end
			end
		end
	end
	P.Buy:SetShown(not E.craft)
	if not E.craft then
		-- (the flip's label is set by the purchase steps; "Buy N name" when it's waiting)
		local Txt = tostring(P.Buy:GetText() or "")
		if Txt == "" or Txt == "Buy" or Txt:match("^Buy %d") then T.SetBuyButton(P.Buy, "Buy " .. (F.buyQty or 0), ShortItem(E.id))
		else T.SetBuyButton(P.Buy, Txt) end
		PlaceNote(P.Lines[1], P.Buy)
	end
	P.Summary:ClearAllPoints()
	P.Summary:SetPoint("TOPLEFT", Pane, "TOPLEFT", 6, Y - Slot * PANE_LINE_H - 4)
	P.Summary:SetText(M.summary)
end
function T.EndCraftRun(Done)
	if not Run then return end
	local DB = SaveDB()
	if Done then
		local P = Run.plan
		local Total = Run.spent + (P.vendorCost or 0)
		Core.AddBuy(DB, Run.id, P.units, Total, time(), (P.saleEach * P.crafts - Total) / math.max(1, P.units))
		DB.crafts = DB.crafts or {}
		table.insert(DB.crafts, { time(), Run.id, P.crafts, Total, Run.spell })
		while #DB.crafts > 100 do table.remove(DB.crafts, 1) end
	else
		for _, G in ipairs(Run.got) do Core.AddBuy(DB, G[1], G[2], G[3], time(), 0) end
	end
	Run = nil
end
-- A mat line's Buy button (m: the mat's index in the plan): get the live price of what's left of it; on that
-- line's Confirm, buy it.
function T.BuyMat(m)
	local E = T.SelectedBuy()
	if not (E and E.craft and m) then return end
	if Buy.state == "confirm" and Buy.pending and Buy.pending.craft and Buy.pending.mat == m then
		local Pd = Buy.pending
		C_AuctionHouse.ConfirmCommoditiesPurchase(Pd.id, Pd.qty)
		Buy.state = "buying"
		SayBuy("Buying...")
		T.DrawBuy()
		return
	end
	if Buy.state then return end
	local F = E.flip
	if F.onCooldown then SayBuy("This recipe is on cooldown: ready in " .. T.HoursText(F.onCooldown) .. ".") return end
	if F.blocked then SayBuy("Not a craft to buy for: the product is " .. F.blocked .. ".") return end
	if LastRun and LastRun.key == RunKey(E) then SayBuy("The mats for this craft are bought: craft it first.") return end
	if Run and Run.key ~= RunKey(E) then T.EndCraftRun(false) end
	if not Run then
		Run = { key = RunKey(E), id = E.id, spell = E.craft.spell, plan = E.flip, status = E.craft.status, bought = {}, spent = 0, got = {} }
	end
	local M = Run.plan.mats[m]
	if not M then return end
	local Left = M.qty - (Run.bought[m] or 0)
	if Left <= 0 then return end
	Buy.state = "price"
	-- The most to pay is the mat's target (one craft still clears its bar), not the listing the plan was priced at.
	local Max = M.target or M.upTo or 0
	Buy.pending = { id = M.id, qty = Left, max = Max, craft = true, mat = m }
	C_AuctionHouse.StartCommoditiesPurchase(M.id, Left)
	SayBuy(string.format("Getting the current price of %d %s (pay up to %s each)...", Left, ItemName(M.id), Money(Max)))
	T.DrawBuy()
end
CraftPrice = function(Pd, Unit, Total)
	local P = Run and Run.plan
	if not P then ResetPurchase(true); T.DrawBuy() return end
	-- Pd.max is the mat's target (one craft still clears its bar with the other mats at their planned price): only
	-- the live price against it and your budget decide.
	local Budget = UI().FlipBudget()
	if Unit > Pd.max then
		ResetPurchase(true)
		SayBuy(string.format("Price of %s is over its target: now %s each (pay up to %s). Not bought.", ItemName(Pd.id), Money(Unit), Money(Pd.max)))
		Recheck({ Pd.id }, function() T.RefreshBuy() end)
	elseif Total > Budget then
		ResetPurchase(true)
		SayBuy(string.format("Costs %s, over your flip budget (%s). Not bought.", Money(Total), Money(Budget)))
	else
		Buy.state = "confirm"
		Pd.total = Total
		SayBuy(string.format("%s: %s each now. Click Confirm on its line to buy %d for %s.", ItemName(Pd.id), Money(Unit), Pd.qty, Money(Total)))
	end
	T.DrawBuy()
end
function T.CraftMatBought(Pd)
	ResetPurchase(false)
	Scan.Consume(Pd.id, Pd.qty)
	if not Run then T.DrawBuy() return end
	Run.spent = Run.spent + (Pd.total or 0)
	Run.got[#Run.got + 1] = { Pd.id, Pd.qty, Pd.total or 0 }
	Run.bought[Pd.mat] = (Run.bought[Pd.mat] or 0) + Pd.qty
	local P = Run.plan
	local Left = {}
	for m, M in ipairs(P.mats) do
		local N = M.qty - (Run.bought[m] or 0)
		if N > 0 then Left[#Left + 1] = N .. " " .. ItemName(M.id) end
	end
	if #Left > 0 then
		SayBuy(string.format("Bought %d %s for %s. Still to buy: %s.", Pd.qty, ItemName(Pd.id), Money(Pd.total or 0), table.concat(Left, ", ")))
		T.DrawBuy()
		return
	end
	local id, Spent = Run.id, Run.spent
	local Goods = {}
	for _, G in ipairs(P.vendorGoods or {}) do Goods[#Goods + 1] = G.qty .. " " .. ItemName(G.id) end
	local Done = Run
	T.EndCraftRun(true)
	LastRun = Done
	SayBuy(string.format("All AH mats bought (%s).%s Craft %d %s, then sell them: AF Sell knows what they cost you.", Money(Spent),
		#Goods > 0 and (" Buy " .. table.concat(Goods, ", ") .. " from a vendor.") or "", P.crafts, ItemName(id)))
	T.RefreshBuy()
end

-- Live updates while a quick scan runs (Scan calls this at most every 2 s): rebuild the open lists with the new
-- data, keeping the selected item, the sort and the scroll position. Never under a purchase or a post that is being
-- priced or confirmed: that waits until it's done (checked again every second).
local LiveBuy, LiveSell, LiveTimer
local function ApplyLive()
	if LiveBuy and not Buy.state then
		LiveBuy = nil
		if Buy.loaded then
			Buy.loaded = nil
			if BuyP and BuyP:IsShown() then
				Buy.loaded, Buy.money = WithCrafts(UI().FlipTargets() or {}), GetMoney()
				SortRows() -- keeps the selected item (by id), the sort and Buy.offset
			end
		end
	end
	if LiveSell and not Sell.pending then
		LiveSell = nil
		if SellP and SellP:IsShown() and Sell.queue then Rebuild(true) end -- your price and quantity fields stay
	end
	if (LiveBuy or LiveSell) and not LiveTimer then
		LiveTimer = true
		C_Timer.After(1, function() LiveTimer = nil; ApplyLive() end)
	end
end
function T.OnScanLive()
	LiveBuy, LiveSell = true, true
	ApplyLive()
end
T.ApplyLive = ApplyLive

-- Scan progress in the AF Buy / AF Sell status line (the AF tab has its own bar), cleared when the scan ends.
local ScanSaid = {}
function T.OnScanProgress()
	local Text = Scan.Busy() and Scan.Status()
	if not Text then return end
	if BuyP and BuyP:IsShown() and not Buy.state then SayBuy(Text); ScanSaid.buy = Text end
	if SellP and SellP:IsShown() and not Sell.pending then SaySell(Text); ScanSaid.sell = Text end
end
function T.ClearScanStatus()
	if ScanSaid.buy and BuyP and BuyP.Status:GetText() == ScanSaid.buy then SayBuy("") end
	if ScanSaid.sell and SellP and SellP.Status:GetText() == ScanSaid.sell then SaySell("") end
	ScanSaid = {}
end

-- Events --------------------------------------------------------------------------------------------------------
local Events = CreateFrame("Frame")
Events:RegisterEvent("COMMODITY_PRICE_UPDATED")
Events:RegisterEvent("COMMODITY_PURCHASE_SUCCEEDED")
Events:RegisterEvent("COMMODITY_PURCHASE_FAILED")
Events:RegisterEvent("ITEM_PURCHASED")
Events:RegisterEvent("AUCTION_HOUSE_CLOSED")
Events:SetScript("OnEvent", function(_, Event, A1, A2)
	if Event == "COMMODITY_PRICE_UPDATED" then
		OnPriceUpdated(A1, A2)
	elseif Event == "COMMODITY_PURCHASE_SUCCEEDED" then
		if Buy.state == "buying" and Buy.pending and Buy.pending.craft then
			T.CraftMatBought(Buy.pending)
		elseif Buy.state == "buying" then
			local Pd = Buy.pending
			ResetPurchase(false)
			SayBuy(string.format("Bought %d for %s.", Pd.qty, Core.MoneyColor(Pd.total)))
			Scan.Consume(Pd.id, Pd.qty)
			RecordBuy(Pd.id, Pd.qty, Pd.total, Pd.resell)
			BuyNext()
		end
	elseif Event == "COMMODITY_PURCHASE_FAILED" then
		if Buy.state then
			local Pd = Buy.pending
			ResetPurchase(false)
			SayBuy("The purchase failed (the listings changed). Re-checking the price...")
			if Pd then Recheck({ Pd.id }, function() T.RefreshBuy() end) end
			T.DrawBuy()
		end
	elseif Event == "ITEM_PURCHASED" then
		SayBuy("Purchase complete.")
	elseif Event == "AUCTION_HOUSE_CLOSED" then
		ResetPurchase(true)
		T.EndCraftRun(false)
		LastRun = nil
		Sell.pending = nil
	end
end)

function T.Build()
	BuildBuy()
	BuildSell()
end
