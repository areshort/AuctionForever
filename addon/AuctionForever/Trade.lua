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
local SORTS
local BUY_KEYS = { "name", "tier", "rate", "cost", "resell", "profit", "gold" } -- one per AF Buy column
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
	return (Color and Color.hex or "|cffffffff") .. (Short and UI().ShortName(Name) or Name) .. "|r"
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
local function RowList(Parent, X, Y, Width, Count, Cols, OnPick)
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
			R.Cells[c] = FS
			CX = CX + W + 6
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
local function SyncBar(S, Off, Total)
	local Max = math.max(0, Total - ROWS)
	Off = math.max(0, math.min(Max, Off or 0))
	Syncing = true
	S:SetMinMaxValues(0, Max)
	S:SetValue(Off)
	Syncing = nil
	S:SetShown(Max > 0)
	S.Count:SetShown(Max > 0)
	S.Count:SetText(string.format("%d-%d of %d", Off + 1, math.min(Total, Off + ROWS), Total))
	return Off
end
T.ScrollBar, T.SyncBar = ScrollBar, SyncBar -- the AuctionForever window uses them too
-- Column headers; with OnClick(c) they are buttons (click to sort), the text in .Label. Returns them.
local function Header(Parent, X, Y, Cols, Names, OnClick)
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
		CX = CX + W + 6
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
local BUY_COLS = { 180, 26, 46, 122, 76, 72, 78 }

local function SayBuy(Msg) if BuyP then BuyP.Status:SetText(Msg or "") end end
local function ResetPurchase(Cancel)
	if Cancel and (Buy.state == "price" or Buy.state == "confirm") then C_AuctionHouse.CancelCommoditiesPurchase() end
	Buy.state, Buy.pending = nil, nil
	if BuyP then BuyP.Buy:SetText("Buy") end
end

function T.SelectedBuy() return Buy.rows[Buy.sel] end

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
local function Rate(E) return E.info and type(E.info.sellThrough) == "number" and E.info.sellThrough or nil end
T.BuyRate = Rate
local function SellsText(E)
	local R = Rate(E)
	return R and string.format("sells %d%%", math.floor(R * 100 + 0.5)) or "sell rate not measured yet"
end
SORTS = {
	tier = function(E) return T.Return(Shown(E)) end,
	rate = function(E) return Rate(E) end,
	name = function(E) return UI().SortName(E.id) end,
	cost = function(E) return Shown(E).cost end,
	resell = function(E) return Shown(E).resell end,
	profit = function(E) return (E.best or E.flip).profit end,
	gold = function(E) return E.need or 0 end,
}
local BUY_NAMES = { "Item", "Tier", "Sell rate", "Buy", "Resell at", "Profit", "Status" }
function T.DrawBuy()
	if not BuyP then return end
	local Off = SyncBar(BuyP.Bar, Buy.offset, #Buy.rows)
	Buy.offset = Off
	for i, R in ipairs(BuyP.Rows) do
		local E = Buy.rows[i + Off]
		R:SetShown(E ~= nil)
		R.id = E and E.id
		if E then
			local F = Shown(E)
			local Need = ShownNeed(E)
			R.Icon:SetTexture(UI().Icon(E.id))
			R.Cells[1]:SetText(NameText(E.id, true))
			local Tier, TColor = T.Tier(F)
			R.Cells[2]:SetText(TColor .. Tier .. "|r")
			R.Cells[3]:SetText(UI().RateText(Rate(E)))
			R.Cells[4]:SetText(F.buyQty .. " at up to " .. Core.MoneyColor(F.buyUpTo))
			R.Cells[5]:SetText((F.vendor and "vendor " or "") .. Core.MoneyColor(F.resell))
			R.Cells[6]:SetText(Core.MoneyColor(F.profit))
			local Status
			if Need then Status = "at " .. GoldText(Need)
			elseif F.vendor then Status = "|cff1eff00vendor it|r"
			elseif E.plan and F == E.flip then Status = F.slow and "|cff1eff00in plan|r |cffffd100(slow)|r" or "|cff1eff00in plan|r"
			else Status = "|cffffd100fits, not in plan|r" .. (F.slow and " (slow)" or "") end
			R.Cells[7]:SetText(Status)
			if Need then R.Cells[1]:SetText("|cff808080" .. UI().ShortName((UI().ItemName(E.id))) .. "|r") end -- not affordable yet: name greyed
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
	BuyP.Buy:SetEnabled(E ~= nil and not Need and Buy.state ~= "price" and Buy.state ~= "buying")
	BuyP.Skip:SetEnabled(#Buy.rows > 1)
	if E then
		local F = Shown(E)
		if F.vendor then
			BuyP.Detail:SetText(string.format("%s   %s\nBuy %d at up to %s each (about %s) and sell them to a vendor for %s each: %s profit, no AH cut.%s",
				NameText(E.id), TierLine(F) .. ", " .. SellsText(E), F.buyQty, Core.MoneyColor(F.buyUpTo), Core.MoneyColor(F.cost), Core.MoneyColor(F.resell), Core.MoneyColor(F.profit),
				Need and ("\n" .. "Needs " .. GoldText(Need) .. " gold (the cost plus the " .. Core.MoneyColor(Core.MinKeep) .. " always kept).") or ""))
		else
		BuyP.Detail:SetText(string.format("%s   %s\nBuy %d at up to %s each (about %s), resell at %s over %d h: %s profit after the 5%% cut.%s%s",
			NameText(E.id), TierLine(F) .. ", " .. SellsText(E), F.buyQty, Core.MoneyColor(F.buyUpTo), Core.MoneyColor(F.cost), Core.MoneyColor(F.resell), F.hours, Core.MoneyColor(F.profit),
			F.slow and ("\n" .. "|cffffd100Slow seller: sales come in bursts or often expire, so it may take longer to sell than planned.|r") or "",
			Need and ("\n" .. "A target once you have " .. GoldText(Need) .. " gold (the flip budget is your gold minus " .. Core.MoneyColor(Core.MinKeep) .. "; one item may use only part of it).") or ""))
		end
	else
		BuyP.Detail:SetText("")
	end
	local R = Core.FlipResults(SaveDB(), time(), 7)
	BuyP.Results:SetText(R.sold > 0 and string.format("Your flips, last 7 days: %d sold, profit %s (plan expected %s)",
		R.sold, Core.MoneyColor(R.profit), Core.MoneyColor(R.expected)) or "")
	local P = UI().LastPlan
	local Line = "Flip Budget: " .. Core.MoneyColor(UI().FlipBudget())
	if P and P.count > 0 then
		Line = Line .. string.format("     Plan: %d items, cost %s, profit %s", P.count, Core.MoneyColor(P.cost), Core.MoneyColor(P.profit))
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
-- Put the loaded list in the chosen order (no new work: sorting only reorders what's loaded).
local function SortRows()
	local Id = Buy.rows[Buy.sel] and Buy.rows[Buy.sel].id
	Buy.rows = {}
	for i, E in ipairs(Buy.loaded or {}) do Buy.rows[i] = E end
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
-- Rebuild the list from your data (refresh, a purchase, a scan). Opening the tab reuses it unless your gold changed;
-- sorting always reuses it.
function T.RefreshBuy()
	Buy.loaded, Buy.money = UI().FlipTargets() or {}, GetMoney()
	SortRows()
end
-- Sort AF Buy by a key ("plan" = the plan's order). Asc nil: gold needed lowest first, the rest highest first.
function T.SetBuySort(Key, Asc)
	Buy.sort = SORTS[Key] and Key or "plan"
	if Asc == nil then Asc = Buy.sort == "gold" end
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

local function OnPriceUpdated(Unit, Total)
	if Buy.state ~= "price" or not Buy.pending then return end
	local Pd = Buy.pending
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
		BuyP.Buy:SetText(string.format("Confirm %d for %s", Pd.qty, Core.MoneyColor(Total)))
		SayBuy(string.format("Current price %s each. Click Confirm to buy.", Core.MoneyColor(Unit)))
	end
	T.DrawBuy()
end

local function BuildBuy()
	BuyP = UI().NewAHPage("AF Buy", "AuctionForeverBuyTab", "AuctionForeverBuyPanel",
		function()
			-- Rebuild only if there's new scan data or your gold changed since the list was made.
			if not Buy.loaded or Buy.money ~= GetMoney() then T.RefreshBuy() end
			T.SelectBuy(Buy.sel)
		end, function() ResetPurchase(true) end, function() T.RefreshBuyPrices() end)
	local P = BuyP
	Text(P, "GameFontNormalLarge", 20, -14):SetText("AF Buy: flip targets")
	P.Budget = Text(P, "GameFontHighlightSmall", 300, -6)
	P.Target = Text(P, "GameFontHighlightSmall", 300, -19)
	P.Results = Text(P, "GameFontHighlightSmall", 300, -32)
	P.Headers = Header(P, 14, -44, BUY_COLS, BUY_NAMES, function(c) T.BuyHeaderClick(c) end)
	P.Rows = RowList(P, 14, -60, 660, ROWS, BUY_COLS, function(r) T.SelectBuy(r + (Buy.offset or 0)) end)
	P:EnableMouseWheel(true)
	P:SetScript("OnMouseWheel", function(_, Delta)
		Buy.offset = math.max(0, math.min(math.max(0, #Buy.rows - ROWS), (Buy.offset or 0) - Delta * 3))
		T.DrawBuy()
	end)
	P.Bar = ScrollBar(P, 678, -60, function(V) Buy.offset = V; T.DrawBuy() end)
	P.Empty = Text(P, "GameFontDisable", 20, -66, 600) -- one line in the table, where the first row would be
	P.Buy = Button(P, "Buy", 20, -420, 200, function() T.BuyClick() end)
	-- Pinned by its bottom just above the buttons: longer text grows upward instead of running into them.
	P.Detail = Text(P, "GameFontHighlight", 20, -380, 640)
	P.Detail:ClearAllPoints()
	P.Detail:SetPoint("BOTTOMLEFT", P.Buy, "TOPLEFT", 0, 6)
	P.Skip = Button(P, "Next", 230, -420, 80, function() T.SelectBuy(Buy.sel + 1) end)
	P.Status = Text(P, "GameFontHighlightSmall", 480, -425, 190)
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
		Exp = string.format("     Expected %s: %s%s (%d%% sell)", G.cost and "profit" or "earnings",
			E < 0 and "|cffff4040-|r" or "", Core.MoneyColor(math.abs(E)), math.floor(Ch * 100 + 0.5))
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
		if Buy.state == "buying" then
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
		Sell.pending = nil
	end
end)

function T.Build()
	BuildBuy()
	BuildSell()
end
