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
local Buy = { rows = {}, sel = 1, sort = "plan" }
local SORTS, SORT_LABEL
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
local function NameText(id)
	local Name, Quality = UI().ItemName(id)
	local Color = ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[Quality or 1]
	return (Color and Color.hex or "|cffffffff") .. Name .. "|r"
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
local function Header(Parent, X, Y, Cols, Names)
	local CX = X + 24
	for c, W in ipairs(Cols) do
		local H = Parent:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
		H:SetPoint("TOPLEFT", CX, Y)
		H:SetWidth(W)
		H:SetJustifyH("LEFT")
		H:SetText(Names[c])
		CX = CX + W + 6
	end
end

local function SaveDB() AuctionForeverDB = AuctionForeverDB or {} return AuctionForeverDB end
-- Remember a purchase: what you paid and the profit the plan expected per unit.
local function RecordBuy(id, Qty, Total, Resell)
	local Expect = Resell and (math.floor(Resell * (1 - Core.Cut)) - Total / math.max(1, Qty)) or 0
	Core.AddBuy(SaveDB(), id, Qty, Total, time(), Expect)
end

-- AF Buy ------------------------------------------------------------------------------------------------------
local BUY_COLS = { 200, 150, 90, 90, 80 }

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
local function GoldText(N) return Core.Money(math.ceil(N / 100) * 100) end
SORTS = {
	-- plan: FlipRows order (the plan, then what fits now, then by gold needed)
	gold = function(a, b)
		local An, Bn = a.need or 0, b.need or 0
		if An ~= Bn then return An < Bn end
		return (a.best or a.flip).profit > (b.best or b.flip).profit
	end,
	profit = function(a, b)
		local Ap, Bp = (a.best or a.flip).profit, (b.best or b.flip).profit
		if Ap ~= Bp then return Ap > Bp end
		return (a.bestNeed or 0) < (b.bestNeed or 0)
	end,
}
SORT_LABEL = { plan = "Sort: plan", gold = "Sort: gold needed", profit = "Sort: profit" }
function T.DrawBuy()
	if not BuyP then return end
	local Off = Buy.offset or 0
	for i, R in ipairs(BuyP.Rows) do
		local E = Buy.rows[i + Off]
		R:SetShown(E ~= nil)
		R.id = E and E.id
		if E then
			local F = Shown(E)
			local Need = ShownNeed(E)
			R.Icon:SetTexture(UI().Icon(E.id))
			R.Cells[1]:SetText(NameText(E.id))
			R.Cells[2]:SetText(F.buyQty .. " at up to " .. Core.Money(F.buyUpTo))
			R.Cells[3]:SetText((F.vendor and "vendor " or "") .. Core.Money(F.resell))
			R.Cells[4]:SetText("|cff1eff00" .. Core.Money(F.profit) .. "|r")
			local Status
			if Need then Status = "at " .. GoldText(Need)
			elseif F.vendor then Status = "|cff1eff00vendor it|r"
			elseif E.plan and F == E.flip then Status = F.slow and "|cff1eff00in plan|r |cffffd100(slow)|r" or "|cff1eff00in plan|r"
			else Status = "|cffffd100fits, not in plan|r" .. (F.slow and " (slow)" or "") end
			R.Cells[5]:SetText(Status)
			if Need then for c = 1, 4 do R.Cells[c]:SetText("|cff808080" .. (R.Cells[c]:GetText() or ""):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "") .. "|r") end end
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
			BuyP.Detail:SetText(string.format("%s\nBuy %d at up to %s each (about %s) and sell them to a vendor for %s each: %s profit, no AH cut.%s",
				NameText(E.id), F.buyQty, Core.Money(F.buyUpTo), Core.Money(F.cost), Core.Money(F.resell), Core.Money(F.profit),
				Need and ("\n" .. "Needs " .. GoldText(Need) .. " gold (the cost plus the " .. Core.Money(Core.MinKeep) .. " always kept).") or ""))
		else
		BuyP.Detail:SetText(string.format("%s\nBuy %d at up to %s each (about %s), resell at %s over %d h: %s profit after the 5%% cut.%s%s",
			NameText(E.id), F.buyQty, Core.Money(F.buyUpTo), Core.Money(F.cost), Core.Money(F.resell), F.hours, Core.Money(F.profit),
			F.slow and ("\n" .. "|cffffd100Slow seller: sales come in bursts or often expire, so it may take longer to sell than planned.|r") or "",
			Need and ("\n" .. "A target once you have " .. GoldText(Need) .. " gold (the flip budget is your gold minus " .. Core.Money(Core.MinKeep) .. "; one item may use only part of it).") or ""))
		end
	else
		BuyP.Detail:SetText("")
	end
	local R = Core.FlipResults(SaveDB(), time(), 7)
	BuyP.Results:SetText(R.sold > 0 and string.format("Your flips, last 7 days: %d sold, profit %s (plan expected %s)",
		R.sold, Core.Money(R.profit), Core.Money(R.expected)) or "")
	local P = UI().LastPlan
	local Line = "Flip Budget: " .. Core.MoneyColor(UI().FlipBudget())
	if P and P.count > 0 then
		Line = Line .. string.format("     Plan: %d items, cost %s, profit %s", P.count, Core.Money(P.cost), Core.Money(P.profit))
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
	if SORTS[Buy.sort] then table.sort(Buy.rows, SORTS[Buy.sort]) end
	Buy.sel = 1
	for i, E in ipairs(Buy.rows) do if E.id == Id then Buy.sel = i end end
	if BuyP and BuyP.Sort then BuyP.Sort:SetText(SORT_LABEL[Buy.sort]) end
	T.DrawBuy()
end
-- Rebuild the list from your data (refresh, a purchase, a scan). Opening the tab reuses it unless your gold changed;
-- sorting always reuses it.
function T.RefreshBuy()
	Buy.loaded, Buy.money = UI().FlipTargets() or {}, GetMoney()
	SortRows()
end
function T.SetBuySort(Key)
	Buy.sort = SORT_LABEL[Key] and Key or "plan"
	Buy.offset = 0
	SortRows()
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
	for i, A in ipairs(List) do
		local Unit = A.buyout / math.max(1, A.qty)
		if Unit <= F.buyUpTo and A.buyout <= Budget and (not Best or Unit < Best.buyout / math.max(1, Best.qty)) then Best, BestI = A, i end
	end
	if not Best then
		SayBuy("No listing at or under " .. Core.Money(F.buyUpTo) .. " right now. Re-checking...")
		Recheck({ E.id }, function() T.RefreshBuy() end)
		return
	end
	C_AuctionHouse.PlaceBid(Best.auctionID, Best.buyout)
	table.remove(List, BestI)
	Scan.Consume(E.id, Best.qty)
	RecordBuy(E.id, Best.qty, Best.buyout, F.resell)
	Buy.bought = (Buy.bought or 0) + Best.qty
	SayBuy(string.format("Bought %d for %s (%d of %d).", Best.qty, Core.Money(Best.buyout), Buy.bought, F.buyQty))
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
		R = Core.Resale(Core.Info(Pd.id), Pd.qty, Total)
		Profit = R and R.profit
		if R then Pd.resell = R.resell end
		MinProfit = Core.FlipNeed(Total, Core.MinFlipProfitFor(UI().FlipBudget()))
	end
	local Budget = UI().FlipBudget()
	if Unit > Pd.max then
		ResetPurchase(true)
		SayBuy(string.format("Price went up: now %s each (max %s). Not bought.", Core.Money(Unit), Core.Money(Pd.max)))
		Recheck({ Pd.id }, function() T.RefreshBuy() end)
	elseif Total > Budget then
		ResetPurchase(true)
		SayBuy(string.format("Costs %s, over your flip budget (%s). Not bought.", Core.Money(Total), Core.Money(Budget)))
	elseif not R then
		ResetPurchase(true)
		SayBuy("The resale doesn't work any more on current data (the price fell or the item stopped selling well). Not bought.")
	elseif Profit < MinProfit then
		ResetPurchase(true)
		SayBuy(string.format("At today's price the expected profit would be %s (under %s). Not bought.", Core.Money(Profit), Core.Money(MinProfit)))
	else
		Buy.state = "confirm"
		Pd.total = Total
		BuyP.Buy:SetText(string.format("Confirm %d for %s", Pd.qty, Core.Money(Total)))
		SayBuy(string.format("Current price %s each. Click Confirm to buy.", Core.Money(Unit)))
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
	Header(P, 14, -44, BUY_COLS, { "Item", "Buy", "Resell at", "Profit", "Status" })
	P.Rows = RowList(P, 14, -60, 660, ROWS, BUY_COLS, function(r) T.SelectBuy(r + (Buy.offset or 0)) end)
	P:EnableMouseWheel(true)
	P:SetScript("OnMouseWheel", function(_, Delta)
		Buy.offset = math.max(0, math.min(math.max(0, #Buy.rows - ROWS), (Buy.offset or 0) - Delta * 3))
		T.DrawBuy()
	end)
	P.Empty = Text(P, "GameFontDisable", 20, -66, 600) -- one line in the table, where the first row would be
	P.Detail = Text(P, "GameFontHighlight", 20, -380, 640)
	P.Buy = Button(P, "Buy", 20, -420, 200, function() T.BuyClick() end)
	P.Skip = Button(P, "Next", 230, -420, 80, function() T.SelectBuy(Buy.sel + 1) end)
	P.Sort = Button(P, "Sort: plan", 320, -420, 150, function()
		T.SetBuySort(({ plan = "gold", gold = "profit", profit = "plan" })[Buy.sort])
	end)
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
	if Cut and Price and Price < PaidFloor(G) then Flag = "cutloss" end
	if not Price then H, Idx, Price, Qty = 2, 1, math.max(Lo, Core.Market(I) or Lo), G.count end
	G.price, G.durIdx, G.qty, G.flag = math.max(Lo, math.floor(Price)), Idx, Qty, Flag
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
		local Market = I and Core.Market(I)
		G.vendor = UI().Vendor(G.id)
		if Market and Market > G.vendor then
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
		Exp = string.format("     Expected %s: %s%s%s|r (%d%% sell)", G.cost and "profit" or "earnings",
			E >= 0 and "|cff1eff00" or "|cffff4040", E < 0 and "-" or "", Core.Money(math.abs(E)), math.floor(Ch * 100 + 0.5))
	end
	SellP.Deposit:SetText(string.format("Deposit: %s     You get after the cut: %s%s", D and Core.Money(D) or "-", Net and Core.Money(Net) or "-", Exp))
end

-- Redraw whichever of our AH panels is open (item names arriving from the server).
function T.RedrawNames()
	if BuyP and BuyP:IsShown() then T.DrawBuy() end
	if SellP and SellP:IsShown() then T.DrawSell() end
end

function T.DrawSell()
	if not SellP then return end
	local Off = Sell.offset or 0
	for i, R in ipairs(SellP.QueueRows) do
		local G = Sell.queue[i + Off]
		R:SetShown(G ~= nil)
		R.id = G and G.id
		if G then
			R.Icon:SetTexture(UI().Icon(G.id))
			R.Cells[1]:SetText(NameText(G.id))
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
		G.count, Core.Money(Core.Market(I)), I.perHour or 0, UI().StatusText(Core.Status(I)))
	if G.cost then
		local Price = T.SellPrice() or G.price
		local Each = math.floor(Price * (1 - Core.Cut)) - G.cost
		Line = Line .. string.format("\nYou paid %s each (%d bought). At this price: %s%s|r each.", Core.Money(G.cost), G.held,
			Each >= 0 and "|cff1eff00profit " or "|cffff4040loss ", Core.Money(math.abs(Each)))
	end
	local Hint = {
		loss = "|cffff4040Being the cheapest would sell below your floor (vendor or what you paid): holding may be better.|r",
		flooding = "|cffffd100More is being posted than sold: priced 1c under the cheapest; prices may keep falling.|r",
		guess = "New listings per hour not measured yet: priced 1c under the cheapest to be safe.",
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
		SaySell(string.format("Posted %d at %s each.", Pd[3], Core.Money(Pd[4])))
		AfterPost(Pd[3], Pd[4])
		return
	end
	local Price, Qty, Dur = T.SellPrice(), tonumber(SellP.Qty:GetText()), Sell.dur or 1
	if not Price then SaySell("Enter a price.") return end
	if Price < Floor(G) then SaySell("That's below what the vendor pays (" .. Core.Money(Floor(G)) .. " after the cut). Not posted.") return end
	if PaidFloor(G) and Price < PaidFloor(G) and Sell.lossOk ~= G.id then
		Sell.lossOk = G.id
		SaySell("That's below what you paid (" .. Core.Money(PaidFloor(G)) .. " after the cut). Click Post again to sell at a loss.")
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
	SaySell(string.format("Posted %d at %s each.", Qty, Core.Money(Price)))
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
			SayBuy(string.format("Bought %d for %s.", Pd.qty, Core.Money(Pd.total)))
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
