-- AuctionForever scanner: reads the whole auction house (ReplicateItems), saves fresh prices, and measures sales by
-- comparing with the cloud snapshot or your previous scan.
local _, AF = ...
local Core = AF.Core
local Scan = {}
AF.Scan = Scan

local BATCH = 2000          -- listings read per frame, so the game doesn't stall
local LADDER = 12           -- cheapest price levels kept per item
local MIN_GAP = 0.25        -- hours between two looks before sales are measured (15 min)
local KEEP_HOURS = 72
local KEEP_OBS = 30

local Busy, Waiting
local Levels, Expiring, Count, Index, Total, Started

local function DB()
	AuctionForeverDB = AuctionForeverDB or {}
	AuctionForeverDB.obs = AuctionForeverDB.obs or {}
	return AuctionForeverDB
end

local function Say(Msg) print("|cffffd100AuctionForever:|r " .. Msg) end

-- Ladder of the cheapest LADDER price levels: { {price, qty, expiringQty}, ... }
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

-- What we compare against: your previous scan when it's newer than the cloud data, else the cloud snapshot.
local function Baseline(id, Now)
	local D, Prev = AuctionForeverData, DB().fresh
	if Prev and Prev.items and (not (type(D) == "table" and D.time) or Prev.time > D.time) then
		local F = Prev.items[id]
		return F and F[3] or {}, Prev.time
	end
	if type(D) == "table" and D.items and D.items[id] then
		local Row, Ladder = D.items[id], nil
		for i, Name in ipairs(D.fields) do if Name == "ladder" then Ladder = Row[i] end end
		return Ladder or {}, D.time
	end
	return nil, nil
end

-- Pure step (tested offline): turn the counted listings into saved prices and sales observations.
function Scan.Finish(L, E, Now)
	local Store = DB()
	local Items = {}
	local Gap, Measured = nil, 0
	local D = AuctionForeverData
	local Seen = {}
	for id, Prices in pairs(L) do
		local Ladder = ToLadder(Prices, E[id])
		local Qty = 0
		for _, N in pairs(Prices) do Qty = Qty + N end
		Items[id] = { Ladder[1] and Ladder[1][1], Qty, Ladder }
		Seen[id] = true
	end
	-- A scan that saw far fewer items than the baseline is incomplete: keep its prices, don't measure sales from it
	-- (every missing item would look sold out).
	local Mine, Theirs = 0, 0
	for _ in pairs(Seen) do Mine = Mine + 1 end
	local BaseItems = (Store.fresh and Store.fresh.items) or (type(D) == "table" and D.items) or {}
	for _ in pairs(BaseItems) do Theirs = Theirs + 1 end
	if Theirs > 0 and Mine < 0.7 * Theirs then
		Store.fresh = { time = Now, items = Items }
		return nil, 0, true
	end
	-- Items the baseline had but the scan doesn't: everything there is gone (bought, expired or cancelled).
	local Check = {}
	for id in pairs(Seen) do Check[id] = true end
	if type(D) == "table" and D.items then for id in pairs(D.items) do Check[id] = true end end
	if Store.fresh and Store.fresh.items then for id in pairs(Store.fresh.items) do Check[id] = true end end
	for id in pairs(Check) do
		local Before, BaseTime = Baseline(id, Now)
		if Before and BaseTime then
			local H = (Now - BaseTime) / 3600
			if H >= MIN_GAP and H <= 6 then
				Gap = H
				local Sold, Value, Lv, Hi = Core.CompareLadders(Before, L[id] or {})
				local O = Store.obs[id] or {}
				O[#O + 1] = { Now, H, Sold, Value, Lv, Hi }
				local Kept = {}
				for _, X in ipairs(O) do if X[1] >= Now - KEEP_HOURS * 3600 then Kept[#Kept + 1] = X end end
				while #Kept > KEEP_OBS do table.remove(Kept, 1) end
				Store.obs[id] = Kept
				if Sold > 0 then Measured = Measured + 1 end
			end
		end
	end
	Store.fresh = { time = Now, items = Items }
	return Gap, Measured
end

local Worker = CreateFrame("Frame")
local function Step()
	local Stop = math.min(Total, Index + BATCH - 1)
	for i = Index, Stop do
		local _, _, Cnt, _, _, _, _, _, _, Buyout, _, _, _, _, _, _, ItemID = C_AuctionHouse.GetReplicateItemInfo(i)
		if ItemID and Buyout and Buyout > 0 and Cnt and Cnt > 0 then
			local P = math.floor(Buyout / Cnt)
			local L = Levels[ItemID]
			if not L then L = {}; Levels[ItemID] = L end
			L[P] = (L[P] or 0) + Cnt
			if C_AuctionHouse.GetReplicateItemTimeLeft(i) == 0 then
				local E = Expiring[ItemID]
				if not E then E = {}; Expiring[ItemID] = E end
				E[P] = (E[P] or 0) + Cnt
			end
			Count = Count + 1
		end
	end
	Index = Stop + 1
	Scan.Progress = Total > 0 and (Index - 1) / Total or 1
	if AF.UI and AF.UI.ScanProgress then AF.UI.ScanProgress() end
	if Index > Total then
		Worker:SetScript("OnUpdate", nil)
		local Gap, Measured, Partial = Scan.Finish(Levels, Expiring, time())
		Busy = false
		local Took = GetTime() - Started
		if Partial then
			Say(string.format("scanned %d listings, but that looks incomplete. Prices updated; sales not measured this time.", Count))
		elseif Gap then
			Say(string.format("scanned %d listings in %.0f s. Sales measured over the last %d min: %d items sold something.", Count, Took, math.floor(Gap * 60 + 0.5), Measured))
		else
			Say(string.format("scanned %d listings in %.0f s. Prices updated; scan again in 15+ min to measure sales.", Count, Took))
		end
		Levels, Expiring = nil, nil
		if AF.UI and AF.UI.ScanDone then AF.UI.ScanDone() end
	end
end

function Scan.Busy() return Busy or Waiting end

function Scan.Start()
	if Busy or Waiting then Say("a scan is already running.") return end
	if not (AuctionHouseFrame and AuctionHouseFrame:IsShown()) then Say("open the auction house first.") return end
	Waiting = true
	Started = GetTime()
	C_AuctionHouse.ReplicateItems()
	Say("scanning the auction house...")
end

local Events = CreateFrame("Frame")
Events:RegisterEvent("REPLICATE_ITEM_LIST_UPDATE")
Events:RegisterEvent("AUCTION_HOUSE_CLOSED")
Events:SetScript("OnEvent", function(_, Event)
	if Event == "REPLICATE_ITEM_LIST_UPDATE" and Waiting then
		Waiting, Busy = false, true
		Levels, Expiring, Count, Index = {}, {}, 0, 1
		Total = C_AuctionHouse.GetNumReplicateItems()
		Worker:SetScript("OnUpdate", Step)
	elseif Event == "AUCTION_HOUSE_CLOSED" and (Waiting or Busy) then
		Worker:SetScript("OnUpdate", nil)
		Waiting, Busy, Levels, Expiring = false, false, nil, nil
		Say("scan stopped: the auction house closed.")
		if AF.UI and AF.UI.ScanDone then AF.UI.ScanDone() end
	end
end)
