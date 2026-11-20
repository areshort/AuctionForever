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
Core.MinHours = 3               -- fewer hours watched than this: "warming up"
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
	return I
end

-- Age of the data in hours (nil when there's no data).
function Core.DataAge(Now)
	local D = AuctionForeverData
	if type(D) ~= "table" or not D.time then return nil end
	return ((Now or time()) - D.time) / 3600
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
	if (I.sales or 0) < Core.MinSales or (I.hoursSeen or 0) < Core.MinHours then return "warming up" end
	if (I.perHour or 0) <= 0 then return "slow" end
	if (I.hoursWithSales or 0) < Core.SteadyShare * (I.hoursSeen or 1) then return "slow" end
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
