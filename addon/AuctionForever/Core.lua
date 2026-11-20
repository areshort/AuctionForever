-- AuctionForever core: turns the collector's numbers into statuses, prices, flips and farm values.
-- Pure Lua (no game calls) so it can be tested offline. All money is in copper.
local _, AF = ...
AF = AF or {}
AuctionForever = AF

local Core = {}
AF.Core = Core

-- Settings (tunable in one place; the plan's starting points).
Core.Cut = 0.05                 -- auction house cut
Core.Durations = { 2, 8, 24 }   -- Forever's choices, in hours (index 1/2/3 in the game's post call)
Core.MinSales = 10              -- fewer sales than this: "warming up"
Core.MinHours = 1               -- fewer hours of sales watched than this: "warming up"
Core.EarlyHours = 6             -- under this many hours of sales, numbers are labeled "early"
Core.SteadyShare = 0.7          -- share of watched hours with at least one sale
Core.MinSellThrough = 0.6       -- share of ended listings that sold
Core.LongSellThrough = 0.9      -- needed before an 8 h or 24 h post is chosen
Core.FloodDays = 1              -- more listed than this many days of sales: flooded
Core.FallShare = 0.10           -- last-24 h selling price this far under the 3-day one: falling
Core.MinFlipProfit = 1000       -- 10 silver
Core.ItemBudgetShare = 0.20     -- one flip item may use at most this share of the budget
Core.ReserveShare = 0.5         -- spend up to half your gold...
Core.MinKeep = 10000            -- ...always keeping at least 1 gold

-- One item's numbers from the data file, as a table with named fields. nil when the item isn't in the data.
function Core.Info(id)
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return nil end
	local Row = D.items[id]
	if type(Row) ~= "table" then return nil end
	local I = { id = id }
	for i, Name in ipairs(D.fields) do I[Name] = Row[i] end
	I.ladder = I.ladder or {}
	I.soldQty = (I.perHour or 0) * (I.hoursSeen or 0)
	return Core.MergeScan(I, D.time)
end

-- Adds what the player's own auction house scans saw (AuctionForeverDB, written by Scan.lua):
-- fresher prices when the scan is newer than the cloud data, and the sales measured between scans.
function Core.MergeScan(I, DataTime)
	local DB = AuctionForeverDB
	if type(DB) ~= "table" then return I end
	local id = I.id
	local Fresh = DB.fresh
	if type(Fresh) == "table" and Fresh.items then
		-- Each item carries the time it was last looked at (full or quick scan).
		local F = Fresh.items[id]
		if F and (F[4] or Fresh.time or 0) > (DataTime or 0) then
			I.low, I.qty, I.ladder = F[1], F[2], F[3] or {}
			I.fromScan, I.scanTime = true, F[4] or Fresh.time
		elseif not F and (Fresh.time or 0) > (DataTime or 0) then
			I.low, I.qty, I.ladder = nil, 0, {} -- a full scan newer than the cloud data saw nothing listed
			I.fromScan, I.scanTime = true, Fresh.time
		end
	end
	local Obs = DB.obs and DB.obs[id]
	if type(Obs) == "table" and #Obs > 0 then
		-- Each observation: { time, gap hours, sold qty, sold value, levels that dropped, highest sold price }
		local Hours, Sold, Value, Events, WithSales, Hi = 0, 0, 0, 0, 0, 0
		for _, O in ipairs(Obs) do
			Hours, Sold, Value, Events = Hours + O[2], Sold + O[3], Value + O[4], Events + O[5]
			if O[3] > 0 then WithSales = WithSales + O[2] end
			if (O[6] or 0) > Hi then Hi = O[6] end
		end
		local CloudHours = I.hoursSeen or 0
		local TotalHours = CloudHours + Hours
		if TotalHours > 0 then
			I.perHour = ((I.perHour or 0) * CloudHours + Sold) / TotalHours
			I.hoursWithSales = (I.hoursWithSales or 0) + WithSales
			I.hoursSeen = TotalHours
		end
		I.soldQty = (I.soldQty or 0) + Sold
		I.sales = (I.sales or 0) + Events
		if Sold > 0 then
			local ScanMed = Value / Sold
			if not I.med then I.med, I.med24, I.medAll = ScanMed, ScanMed, ScanMed
			else I.med = (I.med * CloudHours + ScanMed * Hours) / TotalHours end
			if not I.hi or Hi > I.hi then I.hi = math.max(Hi, I.med) end
		end
		I.scanHours = Hours
	end
	return I
end

-- Units bought between an earlier ladder (cheapest first, steps { price, qty, expiring qty }) and a fresh one
-- ({ [price] = qty }). Buyers take the cheapest first, so walk up from the bottom: a level that's completely gone was
-- bought (minus listings that were under 30 min from expiring), a level that partly dropped was bought up to there,
-- and anything above the first untouched level is cancellations, not sales. New cheaper listings don't matter.
-- Returns sold qty, sold value, number of levels that dropped, highest price that dropped.
function Core.CompareLadders(Before, Fresh, Cov)
	local Sold, Value, Levels, Hi = 0, 0, 0, 0
	for _, Step in ipairs(Before) do
		local P, Q, Expiring = Step[1], Step[2], Step[3] or 0
		if Cov and P > Cov then break end -- the fresh look didn't reach this price
		local Left = Fresh[P] or 0
		local Gone = Q - Left
		if Gone <= 0 then break end
		local Bought = math.max(0, Gone - (Left == 0 and Expiring or 0))
		if Bought > 0 then
			Sold, Value, Levels = Sold + Bought, Value + Bought * P, Levels + 1
			if P > Hi then Hi = P end
		end
		if Left > 0 then break end -- buyers stopped here
	end
	return Sold, Value, Levels, Hi
end

-- Age of the data in hours (nil when there's no data).
function Core.DataAge(Now)
	local D = AuctionForeverData
	if type(D) ~= "table" or not D.time then return nil end
	return ((Now or time()) - D.time) / 3600
end

-- Hours of sales the data is based on (nil when there's no data).
function Core.HoursWatched()
	local D = AuctionForeverData
	return type(D) == "table" and D.hours or nil
end

-- Selling price reference: recent median sold, else the current lowest listing.
function Core.Market(I)
	return I.med or I.low
end

-- The most a buyer has recently paid (upper range of sold prices), used as the price ceiling.
function Core.Ceiling(I)
	return I.hi or I.med or I.low
end

-- Why an item is left out, or "good". Order matters: the first reason that applies is shown.
function Core.Status(I)
	if not I then return "no data" end
	if ((I.sales or 0) < Core.MinSales and (I.soldQty or 0) < Core.MinSales) or (I.hoursSeen or 0) < Core.MinHours * 0.25 then return "warming up" end
	if (I.perHour or 0) <= 0 then return "slow" end
	if (I.hoursWithSales or 0) < Core.SteadyShare * (I.hoursSeen or 1) - 0.001 then return "slow" end
	if I.sellThrough and I.sellThrough < Core.MinSellThrough then return "slow" end
	if (I.qty or 0) > Core.FloodDays * 24 * I.perHour then return "flooded" end
	if I.qtyDayAgo and I.qtyDayAgo > 0 and I.qty > 1.5 * I.qtyDayAgo and (I.med24 or 0) <= (I.medAll or 0) then return "flooded" end
	if I.med24 and I.medAll and I.med24 < (1 - Core.FallShare) * I.medAll then return "falling" end
	return "good"
end

-- Hours to sell MyQty at Price, given what's listed below it (buyers take the cheapest first).
function Core.FillHours(Ladder, Price, MyQty, PerHour)
	if not PerHour or PerHour <= 0 then return math.huge end
	local Below = 0
	for _, Step in ipairs(Ladder) do
		if Step[1] < Price then Below = Below + Step[2] end
	end
	return (Below + MyQty) / PerHour
end

-- Highest price that sells MyQty within Hours, never above the ceiling or below Floor.
-- Candidates: 1c under each listed price, and the ceiling itself when nothing is listed below it.
-- Returns price, fill hours (or nil when nothing fits).
function Core.PostPrice(I, MyQty, Hours, Floor, Ladder)
	Ladder = Ladder or I.ladder
	local Cap = Core.Ceiling(I)
	if not Cap then return nil end
	Floor = Floor or 1
	local Best, BestFill
	local function Try(P)
		if P < Floor or P > Cap then return end
		local Fill = Core.FillHours(Ladder, P, MyQty, I.perHour)
		if Fill <= Hours and (not Best or P > Best) then Best, BestFill = P, Fill end
	end
	for _, Step in ipairs(Ladder) do Try(Step[1] - 1) end
	Try(Cap)
	-- Every listing is above the ceiling: post at the ceiling (cheapest anyway).
	return Best, BestFill
end

-- The duration to post for: 2 h unless a longer one earns at least 10% more and the item reliably sells.
-- Returns hours, index (1/2/3), price, fill hours.
function Core.ChooseDuration(I, MyQty, Floor, Ladder)
	local P2, F2 = Core.PostPrice(I, MyQty, 2, Floor, Ladder)
	local BestH, BestIdx, BestP, BestF = 2, 1, P2, F2
	if (I.sellThrough or 0) >= Core.LongSellThrough then
		for Idx = 2, 3 do
			local H = Core.Durations[Idx]
			local P, F = Core.PostPrice(I, MyQty, H, Floor, Ladder)
			if P and (not BestP or P >= BestP * 1.10) then BestH, BestIdx, BestP, BestF = H, Idx, P, F end
		end
	end
	if not BestP then return nil end
	return BestH, BestIdx, BestP, BestF
end

-- How many to post now: what sells within the chosen time; the rest waits.
function Core.PostQuantity(I, Have, Hours, Price, Ladder)
	Ladder = Ladder or I.ladder
	local Below = 0
	for _, Step in ipairs(Ladder) do
		if Step[1] < Price then Below = Below + Step[2] end
	end
	local Room = math.floor((I.perHour or 0) * Hours - Below)
	return math.max(0, math.min(Have, Room))
end

-- Flip budget: up to half your gold, always keeping at least 1 gold.
function Core.Budget(Money)
	return math.max(0, math.min(Money * Core.ReserveShare, Money - Core.MinKeep))
end

-- Best flip for an item: buy the cheapest listings (level by level), then resell on the market as it would look
-- after the purchase. Returns a table {buyQty, buyUpTo, cost, resell, hours, durationIndex, profit} or nil.
function Core.Flip(I, Budget)
	if Core.Status(I) ~= "good" then return nil end
	local Ladder = I.ladder
	local Cap = Budget * Core.ItemBudgetShare
	local Best
	local Qty, Cost = 0, 0
	for Level = 1, #Ladder do
		local P, Q = Ladder[Level][1], Ladder[Level][2]
		local Take = math.min(Q, math.floor((Cap - Cost) / P))
		if Take <= 0 then break end
		Qty, Cost = Qty + Take, Cost + Take * P
		-- What's left after buying: the rest of this level and everything above it.
		local Rest = {}
		if Take < Q then Rest[#Rest + 1] = { P, Q - Take } end
		for j = Level + 1, #Ladder do Rest[#Rest + 1] = Ladder[j] end
		local Floor = math.ceil(Cost / Qty / (1 - Core.Cut)) + 1
		local H, Idx, Price, Fill = Core.ChooseDuration(I, Qty, Floor, Rest)
		if H then
			local Profit = math.floor(Price * Qty * (1 - Core.Cut)) - Cost
			if Profit >= Core.MinFlipProfit and (not Best or Profit > Best.profit) then
				Best = { buyQty = Qty, buyUpTo = P, cost = Cost, resell = Price, hours = H, durationIndex = Idx, fill = Fill, profit = Profit }
			end
		end
		if Take < Q then break end
	end
	return Best
end

-- Market value per day for farming: selling price x how much sells a day.
function Core.ValuePerDay(I)
	local P = Core.Market(I)
	if not P or not I.perHour then return 0 end
	return P * I.perHour * 24
end

-- Exact comparison when both looks have listing IDs (quick scans): { [auctionID] = { qty, unit price, seconds left } }.
-- A listing still there with less quantity was partly bought. A listing that's gone was bought unless it was due to
-- expire, or (commodities) something cheaper from before is still there untouched, which means it was cancelled.
-- Cov = highest price both looks covered (nil = everything). Returns sold qty, value, events, highest sold price.
function Core.CompareAuctions(Before, After, GapSecs, Cov, Commodity)
	local IntactMin
	for Aid, B in pairs(Before) do
		local A = After[Aid]
		if A and A[1] == B[1] and (not IntactMin or B[2] < IntactMin) then IntactMin = B[2] end
	end
	local Sold, Value, Events, Hi = 0, 0, 0, 0
	for Aid, B in pairs(Before) do
		if not Cov or B[2] <= Cov then
			local A, Bought = After[Aid], 0
			if A then Bought = math.max(0, B[1] - A[1])
			elseif B[3] and B[3] <= GapSecs + 60 then Bought = 0                 -- expired
			elseif Commodity and IntactMin and B[2] > IntactMin then Bought = 0   -- cancelled
			else Bought = B[1] end
			if Bought > 0 then
				Sold, Value, Events = Sold + Bought, Value + Bought * B[2], Events + 1
				if B[2] > Hi then Hi = B[2] end
			end
		end
	end
	return Sold, Value, Events, Hi
end

-- What a looted item is worth right now if sold: its post price for that amount (after the cut), else vendor value.
function Core.LootValue(I, Qty, Vendor)
	if I and Core.Status(I) ~= "no data" then
		local H, _, Price = Core.ChooseDuration(I, Qty, Vendor and math.ceil(Vendor / (1 - Core.Cut)) or 1)
		if H then
			local Sell = Core.PostQuantity(I, Qty, H, Price)
			return math.floor(Sell * Price * (1 - Core.Cut)) + (Qty - Sell) * (Vendor or 0)
		end
	end
	return Qty * (Vendor or 0)
end

-- "1g 02s 05c" style text.
function Core.Money(C)
	if not C then return "-" end
	C = math.floor(C + 0.5)
	local Neg = C < 0
	C = math.abs(C)
	local G, S, Cp = math.floor(C / 10000), math.floor(C / 100) % 100, C % 100
	local T
	if G > 0 then T = string.format("%dg %02ds", G, S)
	elseif S > 0 then T = Cp > 0 and string.format("%ds %02dc", S, Cp) or string.format("%ds", S)
	else T = string.format("%dc", Cp) end
	return (Neg and "-" or "") .. T
end

return Core
