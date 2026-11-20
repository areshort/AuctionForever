-- AuctionForever scanner.
-- Full scan: reads every listing (ReplicateItems). Quick scan: looks up a short list of items one by one, which also
-- gives each listing's ID and exact time left. Either way every item it saw gets fresh prices, and sales are measured
-- against that item's own starting point (your last look at it, or the cloud snapshot). Items a scan didn't look at
-- are left alone, so short scans add to the data and never replace it.
local _, AF = ...
local Core = AF.Core
local Scan = {}
AF.Scan = Scan

local BATCH = 2000          -- full scan: listings read per frame, so the game doesn't stall
local LADDER = 12           -- cheapest price levels kept per item
local MAX_AUC = 200         -- quick scan: cheapest listings kept per item for exact comparison
local MIN_GAP = 0.25        -- hours between two looks at an item before its sales are measured (15 min)
local KEEP_HOURS = 72
local KEEP_OBS = 30
local ITEM_TIMEOUT = 3      -- item lookup: seconds to wait for one item's results
local BROWSE_TIMEOUT = 15   -- quick scan: seconds to wait for the next page

local Mode                  -- nil, "full-wait", "full", "lookup", "browse"
Scan.Keys = {}              -- itemID -> the server's item key, learned from quick scans
local Levels, Expiring, Count, Index, Total, Started
local Q                     -- item lookup state
local BQ_STATE              -- quick scan (browse) state

local function DB()
	AuctionForeverDB = AuctionForeverDB or {}
	local S = AuctionForeverDB
	S.obs = S.obs or {}
	S.fresh = S.fresh or { items = {} }
	S.fresh.items = S.fresh.items or {}
	-- Older versions kept one starting point for everything: { time, items = { [id] = { low, qty, ladder } } }.
	if type(S.base) == "table" and S.base.items then
		local Old, New = S.base, {}
		for id, F in pairs(Old.items) do New[id] = { t = Old.time, ladder = F[3] or {} } end
		S.base = New
	end
	S.base = S.base or {}
	return S
end

local function Say(Msg) print("|cffffd100AuctionForever:|r " .. Msg) end
local function Notify(Fn) if AF.UI and AF.UI[Fn] then AF.UI[Fn]() end end

-- { [price] = qty } -> cheapest LADDER levels { {price, qty, expiringQty}, ... }
local function ToLadder(L, E)
	local Prices = {}
	for P in pairs(L) do Prices[#Prices + 1] = P end
	table.sort(Prices)
	local Out = {}
	for i = 1, math.min(#Prices, LADDER) do
		local P = Prices[i]
		Out[i] = { P, L[P], (E and E[P]) or 0 }
	end
	return Out
end

local function CloudQty(id)
	local D = AuctionForeverData
	if type(D) ~= "table" or not D.items or not D.items[id] then return nil end
	for i, Name in ipairs(D.fields) do if Name == "qty" then return D.items[id][i] end end
end

local function CloudLadder(id)
	local D = AuctionForeverData
	if type(D) ~= "table" or not D.items or not D.items[id] then return nil end
	for i, Name in ipairs(D.fields) do if Name == "ladder" then return D.items[id][i] or {} end end
	return {}
end

-- One item seen by a scan. Map = { [price] = qty }, Exp = { [price] = expiring qty } (or nil),
-- Auc = { [auctionID] = { qty, price, secs } } (quick scans only), Cov = highest price the look covered (nil = all).
-- Returns "measured", "soon" (under 15 min since its starting point) or "new", and the quantity sold.
function Scan.Observe(id, Map, Exp, Auc, Cov, Now, Commodity)
	local S = DB()
	local D = AuctionForeverData
	local B = S.base[id]
	local CloudTime = (type(D) == "table" and D.time and CloudLadder(id)) and (D.time - 900) or nil
	-- D.time is when the cloud first saw its snapshot; Blizzard made it a little earlier, so it counts 15 min older.
	local BT, BL, BA, BC, BQ
	if B and (not CloudTime or B.t > CloudTime) then BT, BL, BA, BC, BQ = B.t, B.ladder, B.auc, B.cov, B.qty
	elseif CloudTime then BT, BL, BQ = CloudTime, CloudLadder(id), CloudQty(id) end
	local Ladder = ToLadder(Map, Exp)
	local Qty = 0
	for _, N in pairs(Map) do Qty = Qty + N end
	S.fresh.items[id] = { Ladder[1] and Ladder[1][1], Qty, Ladder, Now }

	local Status, Sold = "new", 0
	if BT then
		local H = (Now - BT) / 3600
		if H < MIN_GAP then
			Status = "soon"
		elseif H <= 6 then
			local Value, Ev, Hi
			local C = (BC and Cov) and math.min(BC, Cov) or (BC or Cov)
			if BA and Auc then Sold, Value, Ev, Hi = Core.CompareAuctions(BA, Auc, H * 3600, C, Commodity)
			else Sold, Value, Ev, Hi = Core.CompareLadders(BL or {}, Map, C) end
			local O = S.obs[id] or {}
			O[#O + 1] = { Now, H, Sold, Value, Ev, Hi, BQ }
			local Kept = {}
			for _, X in ipairs(O) do if X[1] >= Now - KEEP_HOURS * 3600 then Kept[#Kept + 1] = X end end
			while #Kept > KEEP_OBS do table.remove(Kept, 1) end
			S.obs[id] = Kept
			Status = "measured"
		end
	end
	-- A look too soon after the starting point only refreshes prices; otherwise it becomes the new starting point.
	if Status ~= "soon" then S.base[id] = { t = Now, ladder = Ladder, auc = Auc, cov = Cov, qty = Qty } end
	return Status, Sold
end

-- Minutes until the earliest item in the list can be measured again (for the chat message).
local function MinutesToWait(Ids, Now)
	local S, Best = DB(), nil
	for _, id in ipairs(Ids) do
		local B = S.base[id]
		if B and B.t then
			local M = math.ceil(15 - (Now - B.t) / 60)
			if M > 0 and (not Best or M < Best) then Best = M end
		end
	end
	return Best or 15
end

-- Full scan ------------------------------------------------------------------------------------------------------
-- Pure step (tested offline): L = { [itemID] = { [price] = qty } }, E = same for listings under 30 min left.
-- Returns measured count, items with sales, partial?, soon count.
function Scan.FinishFull(L, E, Now)
	local S = DB()
	local D = AuctionForeverData
	local Mine, Theirs = 0, 0
	for _ in pairs(L) do Mine = Mine + 1 end
	local Ref = (type(D) == "table" and D.items) or nil
	if not Ref then Ref = {}; for id, F in pairs(S.fresh.items) do if F[2] and F[2] > 0 then Ref[id] = true end end end
	for _ in pairs(Ref) do Theirs = Theirs + 1 end
	-- A scan that saw far fewer items than expected is incomplete: keep its prices, don't measure sales from it.
	if Theirs > 0 and Mine < 0.7 * Theirs then
		for id, Map in pairs(L) do
			local Ladder = ToLadder(Map, E[id])
			local Qty = 0
			for _, N in pairs(Map) do Qty = Qty + N end
			S.fresh.items[id] = { Ladder[1] and Ladder[1][1], Qty, Ladder, Now }
		end
		return 0, 0, true, 0
	end
	-- Everything the scan saw, plus items it should have seen: those are gone (bought, expired or cancelled).
	local Check = {}
	for id in pairs(L) do Check[id] = true end
	for id in pairs(Ref) do Check[id] = true end
	for id in pairs(S.base) do Check[id] = true end
	local Measured, WithSales, Soon = 0, 0, 0
	for id in pairs(Check) do
		local Map = L[id]
		if Map or S.base[id] or CloudLadder(id) then
			local St, Sold = Scan.Observe(id, Map or {}, E[id], nil, nil, Now, nil)
			if St == "measured" then Measured = Measured + 1; if Sold > 0 then WithSales = WithSales + 1 end
			elseif St == "soon" then Soon = Soon + 1 end
		end
	end
	S.fresh.time = Now
	return Measured, WithSales, false, Soon
end

local Worker = CreateFrame("Frame")
local function FullStep()
	local Stop = math.min(Total, Index + BATCH - 1)
	for i = Index, Stop do
		local _, _, Cnt, _, _, _, _, _, _, Buyout, _, _, _, _, _, _, ItemID = C_AuctionHouse.GetReplicateItemInfo(i)
		if ItemID and Buyout and Buyout > 0 and Cnt and Cnt > 0 then
			local P = math.floor(Buyout / Cnt)
			local M = Levels[ItemID]
			if not M then M = {}; Levels[ItemID] = M end
			M[P] = (M[P] or 0) + Cnt
			if C_AuctionHouse.GetReplicateItemTimeLeft(i) == 0 then
				local X = Expiring[ItemID]
				if not X then X = {}; Expiring[ItemID] = X end
				X[P] = (X[P] or 0) + Cnt
			end
			Count = Count + 1
		end
	end
	Index = Stop + 1
	Scan.Progress = Total > 0 and (Index - 1) / Total or 1
	Notify("ScanProgress")
	if Index > Total then
		Worker:SetScript("OnUpdate", nil)
		local Now = time()
		local Measured, WithSales, Partial, Soon = Scan.FinishFull(Levels, Expiring, Now)
		Mode = nil
		local Took = GetTime() - Started
		if Partial then
			Scan.LastResult = string.format("Full scan: %d listings, looked incomplete. Prices updated; sales not measured.", Count)
		elseif Measured > 0 then
			Scan.LastResult = string.format("Full scan: %d listings in %.0f s. Sales measured for %d items (%d sold something).", Count, Took, Measured, WithSales)
		else
			Scan.LastResult = string.format("Full scan: %d listings in %.0f s. Prices updated; sales are measured on a scan 15+ min after your last one.", Count, Took)
		end
		Say(Scan.LastResult)
		Levels, Expiring = nil, nil
		Notify("ScanDone")
	end
end

function Scan.Busy() return Mode ~= nil end

local function Commas(N)
	local S = tostring(math.floor(N))
	local Out = S:reverse():gsub("(%d%d%d)", "%1,"):reverse()
	return (Out:gsub("^,", ""))
end
-- What's happening right now, for the progress bar: text, and fraction done (nil while waiting for the server).
function Scan.Status()
	if Mode == "full-wait" then
		return string.format("Full scan: waiting for the server... %d s", GetTime() - (Started or GetTime())), nil
	elseif Mode == "full" then
		local Done = math.min(Total or 0, (Index or 1) - 1)
		local F = (Total or 0) > 0 and Done / Total or 1
		return string.format("Full scan: reading listings %d%% (%s of %s)", F * 100, Commas(Done), Commas(Total or 0)), F
	elseif Mode == "browse" and BQ_STATE then
		local E = math.max(1, BQ_STATE.expected or 1)
		local F = BQ_STATE.gotFirst and math.min(0.99, BQ_STATE.n / E) or nil
		if not BQ_STATE.gotFirst then return "Quick scan: waiting for the server...", nil end
		return string.format("Quick scan: %d items read (%d%%)", BQ_STATE.n, F * 100), F
	elseif Mode == "lookup" and Q then
		local Done = math.max(0, Q.i - 1)
		local F = #Q.ids > 0 and Done / #Q.ids or 1
		return string.format("Looking up items %d of %d (%d%%)", Done, #Q.ids, F * 100), F
	end
	return nil, nil
end

local function AHOpen() return AuctionHouseFrame and AuctionHouseFrame:IsShown() end

function Scan.Start()
	if Mode then Say("a scan is already running.") return end
	if not AHOpen() then Say("open the auction house first.") return end
	Mode = "full-wait"
	Started = GetTime()
	Scan.Progress = nil
	C_AuctionHouse.ReplicateItems()
	local Ticket = Started
	C_Timer.After(60, function()
		if Mode == "full-wait" and Started == Ticket then
			Mode = nil
			Scan.LastResult = "The server didn't send the full listing within 60 s. Full scans may be limited to one every 15 min."
			Say(Scan.LastResult)
			Notify("ScanDone")
		end
	end)
	Say("full scan: waiting for the server...")
	Notify("ScanProgress")
end

-- Item lookup (detailed, one item at a time) -----------------------------------------------------------------------------------------------------
local SORTS = { { sortOrder = (Enum and Enum.AuctionHouseSortOrder and Enum.AuctionHouseSortOrder.Price) or 0, reverseSort = false } }
local QuickNext

local function QuickRecord(id, Map, Exp, Auc, Cov, Commodity)
	-- An empty answer can mean the results weren't loaded yet; treating it as "everything sold" would be a fake
	-- sell-out, so it counts as no answer (a full scan is what tells us an item really has nothing listed).
	if next(Map) == nil then Q.skipped = Q.skipped + 1 return end
	local St, Sold = Scan.Observe(id, Map, Exp, Auc, Cov, time(), Commodity)
	Q.done = Q.done + 1
	if St == "measured" then Q.measured = Q.measured + 1; if Sold > 0 then Q.withSales = Q.withSales + 1 end
	elseif St == "soon" then Q.soon = Q.soon + 1 end
end

local function ReadCommodity(id)
	local N = C_AuctionHouse.GetNumCommoditySearchResults(id) or 0
	local Full = C_AuctionHouse.HasFullCommoditySearchResults(id)
	local Map, Exp, Auc, Last, Kept = {}, {}, {}, nil, 0
	for j = 1, N do
		local R = C_AuctionHouse.GetCommoditySearchResultInfo(id, j)
		if R and R.unitPrice and R.quantity and R.quantity > 0 then
			local P = R.unitPrice
			Map[P] = (Map[P] or 0) + R.quantity
			if R.timeLeftSeconds and R.timeLeftSeconds < 1800 then Exp[P] = (Exp[P] or 0) + R.quantity end
			if Kept < MAX_AUC and R.auctionID then Auc[R.auctionID] = { R.quantity, P, R.timeLeftSeconds }; Kept = Kept + 1; Last = P end
		end
	end
	local Cov = (Full and Kept < MAX_AUC) and nil or Last
	QuickRecord(id, Map, Exp, Auc, Cov, true)
end

local BAND_SECS = { [0] = 900, [1] = 4500, [2] = 25200, [3] = 86400 } -- middle of each time-left band
local function ReadItems(id, Key)
	local N = C_AuctionHouse.GetNumItemSearchResults(Key) or 0
	local Full = C_AuctionHouse.HasFullItemSearchResults(Key)
	local Map, Exp, Auc, Rows = {}, {}, {}, {}
	for j = 1, N do
		local R = C_AuctionHouse.GetItemSearchResultInfo(Key, j)
		if R and R.buyoutAmount and R.buyoutAmount > 0 and (R.quantity or 0) > 0 then
			local P = math.floor(R.buyoutAmount / R.quantity)
			local Secs = R.timeLeftSeconds or BAND_SECS[R.timeLeft or 3]
			Map[P] = (Map[P] or 0) + R.quantity
			if Secs < 1800 then Exp[P] = (Exp[P] or 0) + R.quantity end
			if R.auctionID then Rows[#Rows + 1] = { R.auctionID, R.quantity, P, Secs } end
		end
	end
	table.sort(Rows, function(a, b) return a[3] < b[3] end)
	local Last
	for j = 1, math.min(#Rows, MAX_AUC) do local R = Rows[j]; Auc[R[1]] = { R[2], R[3], R[4] }; Last = R[3] end
	local Cov = (Full and #Rows <= MAX_AUC) and nil or Last
	QuickRecord(id, Map, Exp, Auc, Cov, false)
end

local function QuickFinish(Reason)
	local Took = GetTime() - Q.started
	if Reason then
		Scan.LastResult = string.format("Item lookup stopped (%s) after %d of %d items.", Reason, Q.done, #Q.ids)
	elseif Q.measured > 0 then
		Scan.LastResult = string.format("Item lookup: %d items in %.0f s. Sales measured for %d (%d sold something).", Q.done, Took, Q.measured, Q.withSales)
	else
		Scan.LastResult = string.format("Item lookup: %d items in %.0f s. Prices updated; sales are measured %d+ min from now.", Q.done, Took, MinutesToWait(Q.ids, time()))
	end
	if Q.skipped > 0 then Scan.LastResult = Scan.LastResult .. string.format(" %d didn't answer.", Q.skipped) end
	if not Q.silent then Say(Scan.LastResult) end
	local Done = Q.onDone
	Q, Mode = nil, nil
	Scan.Progress = nil
	Notify("ScanDone")
	if Done then Done() end
end

QuickNext = function()
	if not Q then return end
	if not AHOpen() then QuickFinish("auction house closed") return end
	Q.i = Q.i + 1
	if Q.i > #Q.ids then QuickFinish() return end
	Scan.Progress = (Q.i - 1) / #Q.ids
	Notify("ScanProgress")
	Q.waitingReady = true
	if C_AuctionHouse.IsThrottledMessageSystemReady() then Scan.QuickSend() return end
	-- Otherwise AUCTION_HOUSE_THROTTLED_SYSTEM_READY calls QuickSend; this re-check covers a missed event.
	local function Recheck()
		if Q and Q.waitingReady then
			if C_AuctionHouse.IsThrottledMessageSystemReady() then Scan.QuickSend() else C_Timer.After(0.5, Recheck) end
		end
	end
	C_Timer.After(0.5, Recheck)
end

function Scan.QuickSend()
	if not (Q and Q.waitingReady) then return end
	Q.waitingReady = false
	local id = Q.ids[Q.i]
	Q.current, Q.key = id, Scan.Keys[id] or C_AuctionHouse.MakeItemKey(id)
	Q.ticket = (Q.ticket or 0) + 1
	local Ticket = Q.ticket
	C_AuctionHouse.SendSearchQuery(Q.key, SORTS, false)
	C_Timer.After(ITEM_TIMEOUT, function()
		if Q and Q.ticket == Ticket and Q.current then
			Q.current, Q.skipped = nil, Q.skipped + 1
			QuickNext()
		end
	end)
end

-- Look up these items now, listing by listing. Silent = no chat line; OnDone = called when finished.
function Scan.Lookup(Ids, Silent, OnDone)
	if Mode then if not Silent then Say("a scan is already running.") end return false end
	if not AHOpen() then if not Silent then Say("open the auction house first.") end return false end
	if #Ids == 0 then if not Silent then Say("nothing to quick scan yet.") end return false end
	Mode = "lookup"
	Q = { ids = Ids, i = 0, done = 0, measured = 0, withSales = 0, soon = 0, skipped = 0, started = GetTime(), silent = Silent, onDone = OnDone }
	QuickNext()
	return true
end

-- Quick scan: one "browse everything" query read in pages, the way Auctionator's fast scan works. Gives every
-- item's lowest price and total quantity (and the server's item keys) in a handful of requests. It refreshes prices
-- and stock only; sales are measured by full scans, item lookups and the cloud.
-- (BQ_STATE is declared at the top of the file so Scan.Status can see it)
local function BrowseItemCount()
	local D, N = AuctionForeverData, 0
	if type(D) == "table" and D.items then for _ in pairs(D.items) do N = N + 1 end end
	return N
end
local function BrowseAdd(Results)
	for _, R in ipairs(Results or {}) do
		local K = R.itemKey
		local id = K and K.itemID
		if id and (R.totalQuantity or 0) > 0 then
			local A = BQ_STATE.items[id]
			if not A then A = { R.minPrice, 0 }; BQ_STATE.items[id] = A; BQ_STATE.n = BQ_STATE.n + 1 end
			if R.minPrice and (not A[1] or R.minPrice < A[1]) then A[1] = R.minPrice end
			A[2] = A[2] + R.totalQuantity
			if not Scan.Keys[id] then Scan.Keys[id] = K end
		end
	end
	BQ_STATE.last = GetTime()
end

-- Pure step (tested offline): apply browse results { [id] = { minPrice, totalQty } } at time Now.
-- Keeps each item's known price levels at or above the new lowest price (cheaper ones are gone) and adds the new
-- lowest price when it's new. Complete = the browse reached the end, so unlisted items really have nothing listed.
function Scan.ApplyBrowse(Items, Now, Complete)
	local S = DB()
	local D = AuctionForeverData
	for id, A in pairs(Items) do
		local Min, Qty = A[1], A[2]
		local F = S.fresh.items[id]
		local Prev
		if F and (F[4] or S.fresh.time or 0) > ((type(D) == "table" and D.time) or 0) then Prev = F[3] else Prev = CloudLadder(id) end
		local Kept = {}
		for _, Step in ipairs(Prev or {}) do if Min and Step[1] >= Min and #Kept < LADDER then Kept[#Kept + 1] = Step end end
		if Min and (not Kept[1] or Kept[1][1] > Min) then table.insert(Kept, 1, { Min, 1, 0 }); if #Kept > LADDER then Kept[#Kept] = nil end end
		S.fresh.items[id] = { Min, Qty, Kept, Now }
	end
	if Complete then
		local Expected = BrowseItemCount()
		local Got = 0
		for _ in pairs(Items) do Got = Got + 1 end
		if Expected == 0 or Got >= 0.7 * Expected then
			if type(D) == "table" and D.items then
				for id in pairs(D.items) do if not Items[id] then S.fresh.items[id] = { nil, 0, {}, Now } end end
			end
		end
	end
end

local function BrowseFinish(Reason)
	local St = BQ_STATE
	local Complete = not Reason and C_AuctionHouse.HasFullBrowseResults()
	Scan.ApplyBrowse(St.items, time(), Complete)
	local Took = GetTime() - St.started
	if Reason and St.n == 0 then
		Scan.LastResult = "Quick scan: " .. Reason .. "."
	else
		Scan.LastResult = string.format("Quick scan: prices and stock for %d items in %.0f s.%s", St.n, Took, Reason and (" Stopped early: " .. Reason .. ".") or "")
	end
	if not St.silent then Say(Scan.LastResult) end
	local Done = St.onDone
	BQ_STATE, Mode, Scan.Progress = nil, nil, nil
	Notify("ScanDone")
	if Done then Done() end
end

local function BrowseWhenReady(Fn)
	local Ticket = BQ_STATE.ticket
	local function Try()
		if not BQ_STATE or BQ_STATE.ticket ~= Ticket then return end
		if C_AuctionHouse.IsThrottledMessageSystemReady() then Fn() else C_Timer.After(0.2, Try) end
	end
	Try()
end

local function BrowseWatch()
	-- Give up if the server goes quiet for BROWSE_TIMEOUT seconds.
	local St = BQ_STATE
	local Ticket = St.ticket
	C_Timer.After(BROWSE_TIMEOUT, function()
		if BQ_STATE == St and St.ticket == Ticket then BrowseFinish("the server stopped answering") end
	end)
end

local function BrowseNext()
	local St = BQ_STATE
	if not St then return end
	if C_AuctionHouse.HasFullBrowseResults() then BrowseFinish() return end
	St.ticket = St.ticket + 1
	BrowseWatch()
	BrowseWhenReady(function() C_AuctionHouse.RequestMoreBrowseResults() end)
end

function Scan.Quick(Silent, OnDone)
	if Mode then if not Silent then Say("a scan is already running.") end return false end
	if not AHOpen() then if not Silent then Say("open the auction house first.") end return false end
	Mode = "browse"
	BQ_STATE = { items = {}, n = 0, started = GetTime(), ticket = 1, silent = Silent, onDone = OnDone, expected = BrowseItemCount() }
	BrowseWatch()
	BrowseWhenReady(function()
		C_AuctionHouse.SendBrowseQuery({ searchString = "", sorts = {}, filters = {}, itemClassFilters = {} })
	end)
	Notify("ScanProgress")
	return true
end

local Events = CreateFrame("Frame")
Events:RegisterEvent("REPLICATE_ITEM_LIST_UPDATE")
Events:RegisterEvent("AUCTION_HOUSE_CLOSED")
Events:RegisterEvent("AUCTION_HOUSE_THROTTLED_SYSTEM_READY")
Events:RegisterEvent("COMMODITY_SEARCH_RESULTS_UPDATED")
Events:RegisterEvent("ITEM_SEARCH_RESULTS_UPDATED")
Events:RegisterEvent("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED")
Events:RegisterEvent("AUCTION_HOUSE_BROWSE_RESULTS_ADDED")
Events:SetScript("OnEvent", function(_, Event, Arg)
	if Event == "REPLICATE_ITEM_LIST_UPDATE" and Mode == "full-wait" then
		Mode = "full"
		Levels, Expiring, Count, Index = {}, {}, 0, 1
		Total = C_AuctionHouse.GetNumReplicateItems()
		Worker:SetScript("OnUpdate", FullStep)
	elseif Event == "AUCTION_HOUSE_THROTTLED_SYSTEM_READY" then
		if Mode == "lookup" then Scan.QuickSend() end
	elseif Event == "COMMODITY_SEARCH_RESULTS_UPDATED" then
		if Q and Q.current and Arg == Q.current then
			local id = Q.current
			Q.current = nil
			ReadCommodity(id)
			QuickNext()
		end
	elseif Event == "ITEM_SEARCH_RESULTS_UPDATED" then
		if Q and Q.current and type(Arg) == "table" and Arg.itemID == Q.current then
			local id, Key = Q.current, Arg
			Q.current = nil
			ReadItems(id, Key)
			QuickNext()
		end
	elseif Event == "AUCTION_HOUSE_BROWSE_RESULTS_UPDATED" then
		-- The first page of our browse (this event also fires for other searches; only the first one counts).
		if Mode == "browse" and BQ_STATE and not BQ_STATE.gotFirst then
			BQ_STATE.gotFirst = true
			BrowseAdd(C_AuctionHouse.GetBrowseResults())
			BrowseNext()
		end
	elseif Event == "AUCTION_HOUSE_BROWSE_RESULTS_ADDED" then
		if Mode == "browse" and BQ_STATE and BQ_STATE.gotFirst then
			BrowseAdd(Arg)
			BrowseNext()
		end
	elseif Event == "AUCTION_HOUSE_CLOSED" then
		if Mode == "full" or Mode == "full-wait" then
			Worker:SetScript("OnUpdate", nil)
			Mode, Levels, Expiring = nil, nil, nil
			Scan.LastResult = "Full scan stopped: the auction house closed."
			Say(Scan.LastResult)
			Notify("ScanDone")
		elseif Mode == "lookup" then
			QuickFinish("auction house closed")
		elseif Mode == "browse" then
			BrowseFinish("the auction house closed")
		end
	end
end)
