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
Core.LongerGain = 1.10          -- an 8 h or 24 h post must be expected to earn this much more than a shorter one
Core.FloodDays = 1              -- more listed than this many days of sales: flooded
Core.FallShare = 0.10           -- last-24 h selling price this far under the 3-day one: falling
Core.MinFlipProfit = 500        -- 5 silver: a flip must expect at least this (smaller ones aren't worth the clicks)
Core.MinVendorProfit = 200      -- 2 silver: a craft sold to a vendor must pay at least this (see MinVendorPurchase for
                                -- buying listings to sell to a vendor)
-- A flip that needs this many units or more bought (to clear the cheap listings under its resale price) isn't a
-- flip at all: not cut down to fewer units, since reposting above a wall of cheap listings left behind won't sell
-- (Mild Spices: 5,088 at 3-4c to make +1g 31s). 99 units is fine, 100 is not. Craft plans and vendor buys don't
-- clear a wall: not limited by this.
Core.MaxBuyUnits = 100
-- Vendor buys (listings under the vendor price, sold to a vendor): 10s per purchase - each item auction, or one
-- commodity purchase. A commodity is one purchase for any quantity (200 Silk Cloth: one click), so the whole purchase
-- must earn 10s (122 Instant Poison for +2s 14c isn't worth the time); no unit cap. Item auctions are one purchase
-- each, so each must earn 10s on its own (vendor price - its price; the ladder doesn't say how units are grouped into
-- auctions, so each unit counts as one auction); any number of such auctions is fine.
Core.MinVendorPurchase = 1000
Core.FlipMaxHours = 8           -- a flip never buys more than the cautious resale speed sells in this many hours
Core.FlipMinHours = 4           -- hours of sales data an item needs before it's a flip target (two 2 h posting cycles)
-- Weak sellers aren't flipped (Fable review, checked on 72 h of hourly data): sell-through under FlipMinSellThrough
-- (35% losers, 14% return, against 10% and 26%), or more listed than FlipMaxCoverHours of sales (29% losers, 15%
-- return, against 11% and 25%). Farm values and craft plans keep the wider rules (Status: 0.6 = slow, 24 h = flooded).
Core.FlipMinSellThrough = 0.5
Core.FlipMaxCoverHours = 12
-- Flips plan their profit at this share of the resale price. Flips are commodities only, and commodity buyers fill
-- cheapest first (newest first at the same price), so matching the lowest price sells; the small haircut is for
-- being undercut by a few copper now and then, not for a race to the bottom.
Core.UndercutHaircut = 0.97
-- A flip must expect at least this return on what it costs (and MinFlipProfitFor): less for fast, steady sellers
-- (FlipStatus "good"), more for slow ones (sales in bursts, or many expiring: the money is tied up longer).
Core.MinFlipReturn = 0.10
Core.MinFlipReturnSlow = 0.20
Core.UnsoldValue = 0.5          -- what a unit that doesn't sell is worth, as a share of the resale (a later, cheaper relist)
Core.FallingKnife = 0.30        -- lowest price this far under the 3-day median and still dropping: not a flip
Core.BurstFactor = 4            -- a scan window selling this many times faster than the item usually does: a burst
Core.MinWindows = 2             -- separate windows with sales before an item is a steady seller
Core.PlanRateShare = 0.75       -- flips plan resales at this share of the measured sales speed (the low end)
Core.MinKeep = 5000             -- the flip budget is all your gold except this (50 silver)

-- Market keys. Random-suffix gear ("of the Bear", "of the Whale"...) is a market per version: its key is
-- "itemID:bonus" (the item's bonus list, as in its link and in the cloud data's sfx table); other items' key is the
-- plain item ID. An item link with an old-style random suffix (and no bonus list) gets "itemID:r<suffix>", which has
-- no data (no AH value rather than another version's).
function Core.LinkKey(Link, id)
	if type(Link) ~= "string" then return id end
	local Body = Link:match("item:([%-%d:]*)")
	if not Body then return id end
	local F = {}
	for V in (Body .. ":"):gmatch("([^:]*):") do F[#F + 1] = V end
	local ID = tonumber(F[1]) or id
	local NB = tonumber(F[13] or "")
	local Bon = {}
	for k = 1, NB or 0 do
		local B = tonumber(F[13 + k] or "")
		if B then Bon[#Bon + 1] = B end
	end
	if #Bon > 0 then
		table.sort(Bon)
		return ID .. ":" .. table.concat(Bon, ":")
	end
	local Suf = tonumber(F[7] or "")
	if Suf and Suf ~= 0 then return ID .. ":r" .. Suf end
	return ID
end
-- (item ID, bonus part or nil) of a key.
function Core.SplitKey(Key)
	if type(Key) ~= "string" then return Key, nil end
	local id, Rest = Key:match("^(%d+):(.+)$")
	if id then return tonumber(id), Rest end
	return tonumber(Key), nil
end
-- The data row of a key: items[id], or sfx[id][bonus] for a suffix version.
function Core.Row(Key)
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return nil end
	local id, Bon = Core.SplitKey(Key)
	if not id then return nil end
	if not Bon then return D.items[id] end
	local S = type(D.sfx) == "table" and D.sfx[id]
	if type(S) ~= "table" then return nil end
	return S[tonumber(Bon) or Bon]
end
-- Does the item come in suffix versions in the data (then its plain entry is only the listings without one)?
function Core.HasSuffixes(id)
	local D = AuctionForeverData
	return type(D) == "table" and type(D.sfx) == "table" and D.sfx[id] ~= nil
end
-- Every market key in the data (plain IDs, then the suffix versions).
function Core.AllKeys()
	local D, Out = AuctionForeverData, {}
	if type(D) ~= "table" or type(D.items) ~= "table" then return Out end
	for id in pairs(D.items) do Out[#Out + 1] = id end
	for id, S in pairs(type(D.sfx) == "table" and D.sfx or {}) do
		for B in pairs(S) do Out[#Out + 1] = id .. ":" .. B end
	end
	return Out
end

-- One item's numbers from the data file, as a table with named fields. nil when the item isn't in the data.
-- Key: an item ID or a suffix version's key (see Core.LinkKey).
function Core.Info(Key)
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return nil end
	local Row = Core.Row(Key)
	if type(Row) ~= "table" then return nil end
	local id = Core.SplitKey(Key)
	local I = { id = id, key = Key }
	for i, Name in ipairs(D.fields) do I[Name] = Row[i] end
	I.ladder = I.ladder or {}
	I.soldQty = (I.perHour or 0) * (I.hoursSeen or 0)
	I = Core.MergeScan(I, D.time)
	-- Your own listings aren't stock in front of you (known once the game has shown your auctions).
	local Mine = Core.MyListings and Key == id and Core.MyListings[id] -- (your listings aren't split by suffix)
	if Mine then
		local Listed = 0
		for _, Q in pairs(Mine) do Listed = Listed + Q end
		I.ladder = Core.RemoveMine(I.ladder, Mine)
		I.qty = math.max(0, (I.qty or 0) - Listed)
		I.low = I.ladder[1] and I.ladder[1][1] or (I.qty > 0 and I.low or nil)
		I.myListed = Listed
	end
	-- What you already hold of it (bought and not sold yet, in bags or listed): flips count it against their limit.
	local DB = AuctionForeverDB
	if type(DB) == "table" and type(DB.buys) == "table" then
		for _, B in ipairs(DB.buys) do
			if B[2] == id then I.held = (Core.Holding(DB, id)) break end
		end
	end
	if I.myListed then I.held = math.max(I.held or 0, I.myListed) end
	Core.AddMySales(I, id)
	return I
end

-- A price ladder without your own listings. Mine = { [price] = qty }.
function Core.RemoveMine(Ladder, Mine)
	local Out = {}
	for _, Step in ipairs(Ladder or {}) do
		local Q = Step[2] - (Mine[Step[1]] or 0)
		if Q > 0 then Out[#Out + 1] = { Step[1], Q, Step[3] } end
	end
	return Out
end

-- Highest price a new listing can have and still count as competition for sellers at the cheap end: the price where
-- the cheapest 25% of the stock is reached, at least 10% over the lowest. Map = { [price] = qty }. Same rule as the
-- cloud collector's new_cutoff.
function Core.NewCutoff(Map)
	local Steps, Total = {}, 0
	for P, Q in pairs(Map or {}) do Steps[#Steps + 1] = { P, Q }; Total = Total + Q end
	if #Steps == 0 then return nil end
	table.sort(Steps, function(a, b) return a[1] < b[1] end)
	local Run, P25 = 0, Steps[#Steps][1]
	for _, St in ipairs(Steps) do
		Run = Run + St[2]
		if Run * 4 >= Total then P25 = St[1] break end
	end
	return math.max(P25, math.floor(Steps[1][1] * 1.1))
end

-- Your own auction results from the mailbox (Mail.lua): exact, kept apart from the market's sales rate.
Core.MySalesDays = 3
function Core.AddMySales(I, id, Now)
	local DB = AuctionForeverDB
	local M = type(DB) == "table" and DB.mysales
	if type(M) ~= "table" then return end
	local Since = (Now or time()) - Core.MySalesDays * 86400
	local Sold, Value, Expired = 0, 0, 0
	for _, R in ipairs(M) do
		if R[2] == id and R[1] >= Since then
			if R[5] == "sold" then Sold, Value = Sold + R[3], Value + R[4] elseif R[5] == "expired" then Expired = Expired + R[3] end
		end
	end
	if Sold > 0 then I.mySold, I.mySoldValue = Sold, Value end
	if Expired > 0 then I.myExpired = Expired end
end

-- Adds what the player's own auction house scans saw (AuctionForeverDB, written by Scan.lua):
-- fresher prices when the scan is newer than the cloud data, and the sales measured between scans.
function Core.MergeScan(I, DataTime)
	local DB = AuctionForeverDB
	if type(DB) ~= "table" then return I end
	local id = I.id
	local Key = I.key or id -- scans keep suffix versions apart too
	local Fresh = DB.fresh
	if type(Fresh) == "table" and Fresh.items then
		-- Each item carries the time it was last looked at (full or quick scan).
		local F = Fresh.items[Key]
		if F and (F[4] or Fresh.time or 0) > (DataTime or 0) then
			I.low, I.qty, I.ladder = F[1], F[2], F[3] or {}
			I.fromScan, I.scanTime = true, F[4] or Fresh.time
		elseif not F and (Fresh.time or 0) > (DataTime or 0) then
			I.low, I.qty, I.ladder = nil, 0, {} -- a full scan newer than the cloud data saw nothing listed
			I.fromScan, I.scanTime = true, Fresh.time
		end
	end
	-- Sales windows: every compared cloud hour, and every scan window (time between two looks at the item).
	-- The rate is the median across windows, so one big buyout can't make an item look like a fast seller. A scan
	-- window that sold at BurstFactor times the item's usual speed (the median of its other windows) is a burst
	-- (one buyer clearing the bottom, or a mass cancel) and is left out. It's a speed check, not a stock share:
	-- a quarter of the stock selling over a busy hour is normal, the same amount gone in minutes is not.
	-- An item needs sales in 2+ separate windows before it counts as a steady seller.
	-- Your own trades aren't the market: in the cloud's hours your purchases were counted as sales and your posts as
	-- new listings. Take them out (spread over the hours watched). Scans already leave your purchases out.
	local CloudH = I.hoursSeen or 0
	local From, To = (DataTime or 0) - CloudH * 3600, DataTime or 0
	local OwnBought, OwnPosted = 0, 0
	for _, B in ipairs(type(DB.buys) == "table" and DB.buys or {}) do
		if B[2] == id and B[1] >= From and B[1] <= To then OwnBought = OwnBought + B[3] end
	end
	local Posts = type(DB.myposts) == "table" and DB.myposts or {}
	for _, Ps in ipairs(Posts) do
		if Ps[2] == id and Ps[1] >= From and Ps[1] <= To then OwnPosted = OwnPosted + Ps[3] end
	end
	if CloudH > 0 and OwnBought > 0 then
		local Less = OwnBought / CloudH
		if I.perHour then I.perHour = math.max(0, I.perHour - Less) end
		if I.medHour then I.medHour = math.max(0, I.medHour - Less) end
		I.soldQty = math.max(0, (I.soldQty or 0) - OwnBought)
	end
	local function PostedIn(T0, T1)
		local N = 0
		for _, Ps in ipairs(Posts) do if Ps[2] == id and Ps[1] >= T0 and Ps[1] <= T1 then N = N + Ps[3] end end
		return N
	end
	-- The cloud hours' rate: the median hour. For items selling under QuantizedBelow an hour (gear, one at a time),
	-- an hour's count is a whole number, so its median is 0 or 1 or 2 (0, 24, 48 a day: a step, not the rate): there
	-- the median over 4-hour blocks (blockHour, from the cloud data) is used. Busy items keep the hourly median.
	local CloudRate = I.medHour or I.perHour or 0
	if I.blockHour and (I.medHour or 0) < Core.QuantizedBelow then CloudRate = I.blockHour end
	local Rates = {}
	for _ = 1, math.floor(CloudH + 0.5) do Rates[#Rates + 1] = CloudRate end
	local CloudN = #Rates
	local Windows = math.floor((I.hoursWithSales or 0) + 0.5)
	local Obs = DB.obs and DB.obs[Key]
	if type(Obs) ~= "table" then Obs = {} end
	-- Each observation: { time, gap hours, sold qty, sold value, events, highest sold price, stock before, new listed }
	for _, O in ipairs(Obs) do Rates[#Rates + 1] = O[3] / O[2] end
	-- New listings per hour (other sellers posting): cloud hours and scan windows together.
	local NewQ, NewH = 0, 0
	if I.newHour then NewQ, NewH = math.max(0, I.newHour * CloudH - OwnPosted), CloudH end
	for _, O in ipairs(Obs) do
		if O[8] then NewQ, NewH = NewQ + math.max(0, O[8] - PostedIn(O[1] - O[2] * 3600, O[1])), NewH + O[2] end
	end
	if NewH > 0 then I.newHour = NewQ / NewH end
	local function MedianWithout(Skip)
		local T = {}
		for i, R in ipairs(Rates) do if i ~= Skip then T[#T + 1] = R end end
		if #T < 2 then return nil end
		table.sort(T)
		local M = (#T + 1) / 2
		return (T[math.floor(M)] + T[math.ceil(M)]) / 2
	end
	local Keep = {}
	for i = 1, CloudN do Keep[#Keep + 1] = Rates[i] end
	local Hours, Sold, Value, Events, WithSales, Hi, Spikes = 0, 0, 0, 0, 0, 0, 0
	for j, O in ipairs(Obs) do
		local R = Rates[CloudN + j]
		local Usual = MedianWithout(CloudN + j)
		if R > 0 and Usual and R > Core.BurstFactor * math.max(Usual, 1 / O[2]) then
			Spikes = Spikes + 1
		else
			Keep[#Keep + 1] = R
			Hours, Sold, Value, Events = Hours + O[2], Sold + O[3], Value + O[4], Events + O[5]
			if O[3] > 0 then WithSales = WithSales + O[2]; Windows = Windows + 1 end
			if (O[6] or 0) > Hi then Hi = O[6] end
		end
	end
	Rates = Keep
	I.windows, I.salesWindows, I.spikes = #Rates, Windows, Spikes
	if Hours > 0 or Spikes > 0 then
		local TotalHours = CloudH + Hours
		I.hoursWithSales = (I.hoursWithSales or 0) + WithSales
		I.hoursSeen = TotalHours
		I.soldQty = (I.soldQty or 0) + Sold
		I.sales = (I.sales or 0) + Events
		if Sold > 0 then
			local ScanMed = Value / Sold
			if not I.med then I.med, I.med24, I.medAll = ScanMed, ScanMed, ScanMed
			elseif TotalHours > 0 then I.med = (I.med * CloudH + ScanMed * Hours) / TotalHours end
			if not I.hi or Hi > I.hi then I.hi = math.max(Hi, I.med) end
		end
		I.scanHours = Hours
	end
	if #Rates >= 3 then
		table.sort(Rates)
		local M = (#Rates + 1) / 2
		I.perHour = (Rates[math.floor(M)] + Rates[math.ceil(M)]) / 2
	elseif #Rates == 2 then
		I.perHour = math.min(Rates[1], Rates[2]) -- only two windows: take the lower one
	elseif #Rates == 1 then
		I.perHour = Rates[1]
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
	if I.salesWindows and I.salesWindows < Core.MinWindows then return I.salesWindows == 1 and "early" or "warming up" end
	if (I.perHour or 0) <= 0 then return "slow" end
	if (I.hoursWithSales or 0) < Core.SteadyShare * (I.hoursSeen or 1) - 0.001 then return "slow" end
	if I.sellThrough and I.sellThrough < Core.MinSellThrough then return "slow" end
	if (I.qty or 0) > Core.FloodDays * 24 * I.perHour then return "flooded" end
	if I.qtyDayAgo and I.qtyDayAgo > 0 and I.qty > 1.5 * I.qtyDayAgo and (I.med24 or 0) <= (I.medAll or 0) then return "flooded" end
	if I.med24 and I.medAll and I.med24 < (1 - Core.FallShare) * I.medAll then return "falling" end
	return "good"
end

-- Comparable gear: a price estimate for a weapon or armor piece with no market data, from similar gear that has one.
-- Similar: the same kind (weapon / armor), subclass (sword, mail...), slot (robes count as chest) and quality, item
-- level within GearBands[1] (then GearBands[2] when fewer than GearMin match), from AF_Gear (Recipes.lua, the game
-- data). Priced: a measured sold price (median) and sales measured long enough (status good, slow, falling or
-- flooded; not "warming up"). The estimate is the median of the GearNearest closest in item level, never below what
-- a vendor pays after the AH cut. Random-suffix gear ("of the Bear") is matched by its base item: the data's price
-- for an item covers all its suffix versions. Returns { price, n, band, ids, prices } or nil (no price: not gear, or
-- too few matches).
Core.GearBands = { 3, 5 }
Core.GearMin = 3
Core.GearNearest = 7
local GEAR_PRICED = { good = true, slow = true, falling = true, flooded = true }
-- AF_Gear's packed number -> kind (0 weapon, 1 armor), subclass, slot, quality, item level.
function Core.GearInfo(id)
	local P = type(AF_Gear) == "table" and AF_Gear[id]
	if not P then return nil end
	local Lvl = P % 1024; P = (P - Lvl) / 1024
	local Q = P % 8; P = (P - Q) / 8
	local Slot = P % 32; P = (P - Slot) / 32
	local Sub = P % 32
	return (P - Sub) / 32, Sub, Slot, Q, Lvl
end
local GearGroups, GearCache, GearCacheKey
local function GearGroup(id)
	if not GearGroups then
		GearGroups = {}
		for G, P in pairs(AF_Gear) do
			local K = math.floor(P / 1024)
			local T = GearGroups[K]
			if not T then T = {}; GearGroups[K] = T end
			T[#T + 1] = G
		end
	end
	return GearGroups[math.floor(AF_Gear[id] / 1024)] or {}
end
-- The trusted market price of one gear item, or nil.
function Core.GearPrice(id)
	local I = Core.Info(id)
	if not (I and I.med and I.med > 0 and GEAR_PRICED[Core.Status(I)]) then return nil end
	return I.med
end
function Core.GearEstimate(id, Vendor)
	id = Core.SplitKey(id)
	if not (type(AF_Gear) == "table" and AF_Gear[id]) then return nil end
	local D = AuctionForeverData
	local Key = tostring(AF.Scan and AF.Scan.Version or 0) .. ":" .. tostring(type(D) == "table" and D.time or 0)
	if GearCacheKey ~= Key then GearCache, GearCacheKey = {}, Key end
	local C = GearCache[id]
	if C == nil then
		C = false
		local Lvl = AF_Gear[id] % 1024
		local Near = {}
		for _, G in ipairs(GearGroup(id)) do
			local Diff = math.abs(AF_Gear[G] % 1024 - Lvl)
			if G ~= id and Diff <= Core.GearBands[#Core.GearBands] then
				local P = Core.GearPrice(G)
				if P then Near[#Near + 1] = { G, P, Diff } end
			end
		end
		for _, Band in ipairs(Core.GearBands) do
			local In = {}
			for _, X in ipairs(Near) do if X[3] <= Band then In[#In + 1] = X end end
			if #In >= Core.GearMin then
				table.sort(In, function(a, b) if a[3] ~= b[3] then return a[3] < b[3] end return a[1] < b[1] end)
				local Ids, Prices = {}, {}
				for i = 1, math.min(Core.GearNearest, #In) do Ids[i], Prices[i] = In[i][1], In[i][2] end
				local S = {}
				for i, P in ipairs(Prices) do S[i] = P end
				table.sort(S)
				local N = #S
				local Mid = N % 2 == 1 and S[(N + 1) / 2] or math.floor((S[N / 2] + S[N / 2 + 1]) / 2)
				C = { price = Mid, n = N, band = Band, ids = Ids, prices = Prices }
				break
			end
		end
		GearCache[id] = C
	end
	if not C then return nil end
	local Out = {}
	for k, v in pairs(C) do Out[k] = v end
	-- never below what a vendor pays (after the AH cut, so posting at it never pays less than vendoring)
	if Vendor and Vendor > 0 then Out.price = math.max(Out.price, math.ceil(Vendor / (1 - Core.Cut))) end
	return Out
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
function Core.PostPrice(I, MyQty, Hours, Floor, Ladder, MaxPrice)
	Ladder = Ladder or I.ladder
	local Cap = Core.Ceiling(I)
	if not Cap then return nil end
	if MaxPrice then Cap = math.min(Cap, MaxPrice) end
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
-- How fast the queue in front of a new listing shrinks: sales (planned at PlanRateShare) minus other sellers' new
-- listings, which land in front (they undercut the lowest price). nil when new listings aren't measured yet.
function Core.NetSpeed(I)
	if not I.newHour then return nil end
	return (I.perHour or 0) * Core.PlanRateShare - I.newHour
end

-- Your selling price: 1c under the cheapest listing (your own listings are already out of the ladder, see
-- Core.Info); nothing listed: what buyers recently paid. Never below Floor. Duration = the shortest that fits your
-- stack at the net speed; more than a day of sales posts only what sells in 24 h.
-- Returns price, hours, duration index, quantity to post, and a flag: "loss" (being in front is below Floor),
-- "flooding" (more posted than sold) or nil.
function Core.SellPrice(I, Qty, Floor)
	Qty, Floor = math.max(1, Qty or 1), Floor or 1
	local Ladder = I.ladder or {}
	local Net = Core.NetSpeed(I)
	local Speed = (Net and Net > 0) and Net or (I.perHour or 0) * Core.PlanRateShare
	local Flag
	if Net and Net <= 0 then Flag = "flooding" end
	local Price
	if not Ladder[1] then
		Price = Core.Ceiling(I) or Core.Market(I)
		if not Price then return nil end
	else
		Price = Ladder[1][1] - 1
	end
	if Price < Floor then Price, Flag = Floor, "loss" end
	Price = math.floor(Price)
	local Below = 0
	for _, Step in ipairs(Ladder) do if Step[1] < Price then Below = Below + Step[2] end end
	local Fill = Speed > 0 and (Below + Qty) / Speed or math.huge
	local H, Idx = Core.Durations[#Core.Durations], #Core.Durations
	for i, D in ipairs(Core.Durations) do if Fill <= D then H, Idx = D, i break end end
	local Post = Qty
	if Speed > 0 and Fill > H then Post = math.max(1, math.min(Qty, math.floor(Speed * H - Below))) end
	return Price, H, Idx, Post, Flag
end

-- Core.Deposit(I, Hours, Qty) -> deposit in copper; set by the UI from the game (nil = not known, counted as 0).
-- Expected earnings of a post: chance it sells (the item's measured sell-through) x what you get after the cut,
-- minus the deposit you lose when it doesn't sell.
local function Expected(I, H, Qty, P)
	local Chance = math.max(0.05, math.min(1, I.sellThrough or 1))
	local Dep = Core.Deposit and Core.Deposit(I, H, Qty) or 0
	return Chance * P * Qty * (1 - Core.Cut) - (1 - Chance) * Dep
end
-- The duration that earns the most: a longer one must earn at least LongerGain more than the best shorter one.
function Core.ChooseDuration(I, MyQty, Floor, Ladder, MaxPrice)
	local Qty = math.max(1, MyQty or 1)
	local BestH, BestIdx, BestP, BestF, BestE
	for Idx, H in ipairs(Core.Durations) do
		local P, F = Core.PostPrice(I, Qty, H, Floor, Ladder, MaxPrice)
		if P then
			local E = Expected(I, H, Qty, P)
			if not BestE or E >= BestE * Core.LongerGain then BestH, BestIdx, BestP, BestF, BestE = H, Idx, P, F, E end
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

-- Flip budget: your gold, always keeping MinKeep.
function Core.Budget(Money)
	return math.max(0, Money - Core.MinKeep)
end

-- Best flip for an item: buy the cheapest listings (level by level), then resell on the market as it would look
-- after the purchase. Returns a table {buyQty, buyUpTo, cost, resell, hours, durationIndex, profit} or nil.
-- What you paid -------------------------------------------------------------------------------------------------
-- DB.buys = { { time, itemID, qty, total paid, expected profit per unit } }, kept 30 days. Sales come from your
-- "Auction successful" mail in DB.mysales = { { time, itemID, qty, total, "sold" | "expired" } }. Units bought first
-- are counted as sold first.
local BUY_DAYS = 30
function Core.AddBuy(DB, id, Qty, Total, Now, ExpectEach)
	if not (DB and id and Qty and Qty > 0) then return end
	DB.buys = DB.buys or {}
	table.insert(DB.buys, { Now, id, Qty, Total or 0, ExpectEach or 0 })
	local Newest = 0
	for _, B in ipairs(DB.buys) do Newest = math.max(Newest, B[1]) end
	local Kept = {}
	for _, B in ipairs(DB.buys) do if B[1] >= Newest - BUY_DAYS * 86400 then Kept[#Kept + 1] = B end end
	DB.buys = Kept
end

-- Walk purchases and sales of one item (or all items) in time order. OnSale(row, matched units, their cost,
-- their expected profit) is called for each sale that used bought units. Returns the lots still held per item.
local function MatchSales(DB, OnlyId, OnSale)
	local Lots = {}
	local Events = {}
	for _, B in ipairs(DB and DB.buys or {}) do
		if not OnlyId or B[2] == OnlyId then Events[#Events + 1] = { B[1], 0, B } end
	end
	for _, R in ipairs(DB and DB.mysales or {}) do
		if R[5] == "sold" and (not OnlyId or R[2] == OnlyId) then Events[#Events + 1] = { R[1], 1, R } end
	end
	table.sort(Events, function(a, b) if a[1] ~= b[1] then return a[1] < b[1] end return a[2] < b[2] end)
	for _, E in ipairs(Events) do
		local X = E[3]
		local id = X[2]
		Lots[id] = Lots[id] or {}
		if E[2] == 0 then
			table.insert(Lots[id], { left = X[3], unit = X[4] / X[3], expect = X[5] or 0 })
		else
			local Need, Units, Cost, Expect = X[3], 0, 0, 0
			local L = Lots[id]
			while Need > 0 and L[1] do
				local T = math.min(Need, L[1].left)
				Units, Cost, Expect = Units + T, Cost + T * L[1].unit, Expect + T * L[1].expect
				L[1].left, Need = L[1].left - T, Need - T
				if L[1].left <= 0 then table.remove(L, 1) end
			end
			if Units > 0 and OnSale then OnSale(X, Units, Cost, Expect) end
		end
	end
	return Lots
end

-- Bought units of this item you still hold (bags or listed), and their average cost each (0, nil if none).
function Core.Holding(DB, id)
	local L = MatchSales(DB, id)[id] or {}
	local Qty, Cost = 0, 0
	for _, Lot in ipairs(L) do Qty, Cost = Qty + Lot.left, Cost + Lot.left * Lot.unit end
	if Qty <= 0 then return 0, nil end
	return Qty, math.ceil(Cost / Qty - 1e-9)
end

-- Lowest price that gets back what you paid after the AH cut.
function Core.CostFloor(UnitCost) return math.ceil(UnitCost / (1 - Core.Cut) - 1e-9) end

-- Time to stop holding out for what you paid: the market's lowest price stayed under Floor for a whole watched day,
-- or your listings of it expired twice since you bought it. Then selling at the market (taking the loss) or simply
-- holding beats reposting at your cost and losing deposits.
function Core.CutLoss(I, Floor, DB, id)
	if I and I.lowHi24 and Floor and I.lowHi24 < Floor then return true end
	local Since
	for _, B in ipairs(DB and DB.buys or {}) do
		if B[2] == id and (not Since or B[1] < Since) then Since = B[1] end
	end
	local N = 0
	for _, R in ipairs(DB and DB.mysales or {}) do
		if R[2] == id and R[5] == "expired" and (not Since or R[1] >= Since) then N = N + 1 end
	end
	return N >= 2
end

-- How your flips sold in the last Days: units sold, profit after the cut, and what the plans expected for them.
function Core.FlipResults(DB, Now, Days)
	local Out = { sold = 0, profit = 0, expected = 0 }
	MatchSales(DB, nil, function(R, Units, Cost, Expect)
		if R[1] < Now - Days * 86400 then return end
		local Net = math.floor(R[4] * (1 - Core.Cut)) * Units / R[3]
		Out.sold = Out.sold + Units
		Out.profit = Out.profit + math.floor(Net - Cost + 0.5)
		Out.expected = Out.expected + math.floor(Expect + 0.5)
	end)
	return Out
end

-- How much of the flip budget one item may take: 40% while the budget is small (5g or less), then 20% of the budget
-- plus 1g, so a bigger budget always allows a bigger item but is spread over more items (21% at 100g).
function Core.ItemShare(Budget)
	Budget = Budget or 0
	if Budget <= 50000 then return 0.40 end
	return (0.20 * Budget + 10000) / Budget
end

-- The least gold at which a flip costing Cost becomes a target: its cost fits one item's share of the flip budget
-- (your gold minus MinKeep).
function Core.GoldFor(Cost)
	local Budget = Cost <= 20000 and Cost / 0.40 or (Cost - 10000) / 0.20
	return math.ceil(Budget + Core.MinKeep)
end

-- Every worthwhile way to flip one item within Cap: buying the cheapest listings up to each price level, resold at
-- the best price that should sell within 2/8/24 h. Resale speed is planned from the low end (PlanRateShare of the
-- measured rate), since the estimate can be off and your own listings slow the market.
-- The least expected profit a flip must make: 4% of the flip budget, between 2s and 10s, so a small budget still
-- gets small, safe flips.
function Core.MinFlipProfitFor(Budget)
	return Core.MinFlipProfit -- the same at any budget (MinFlipReturn guards against bad estimates)
end

-- Status for flipping: like Status, but an item also needs FlipMinHours of data (a few hours can be one buyer), sells
-- through FlipMinSellThrough ("weak seller" otherwise), has no more listed than FlipMaxCoverHours of sales ("flooded"),
-- and isn't a falling knife: lowest price FallingKnife under the 3-day median and dropping over the last snapshots (a new,
-- lower price level, not a bargain). "slow" sellers (sales in bursts, or many expiring) can be flipped too: their
-- options are marked .slow (a risk label; sell-through already lowers their expected profit).
function Core.FlipStatus(I)
	local S = Core.Status(I)
	if S ~= "good" and S ~= "slow" then return S end
	if (I.hoursSeen or 0) < Core.FlipMinHours then return "warming up" end
	if I.sellThrough and I.sellThrough < Core.FlipMinSellThrough then return "weak seller" end
	if (I.qty or 0) > Core.FlipMaxCoverHours * (I.perHour or 0) then return "flooded" end
	local Base, Lw = I.medAll or I.med, I.lows
	if I.low and Base and I.low < (1 - Core.FallingKnife) * Base and type(Lw) == "table" and #Lw >= 3
		and Lw[#Lw - 2] > Lw[#Lw - 1] and Lw[#Lw - 1] > Lw[#Lw] then
		return "falling"
	end
	return S
end

local function Chance(I) return math.max(0.05, math.min(1, I.sellThrough or 1)) end
Core.SellChance = Chance
-- Expected result of posting Qty at Price (AF Sell): the chance it sells x (what you get after the cut - what you
-- paid for those units), minus the deposit lost when it doesn't sell. Unsold units come back, so they cost only the
-- deposit. Cost nil (farmed or vendor items): the expected earnings. Rounded down to whole copper.
function Core.ExpectedPost(I, Price, Qty, Dep, Cost)
	local Ch = Chance(I)
	local Gain = Price * Qty * (1 - Core.Cut) - (Cost or 0) * Qty
	return math.floor(Ch * Gain - (1 - Ch) * (Dep or 0) + 1e-6), Ch
end
-- How fast a resale sells: measured sales, planned at PlanRateShare. Other sellers' new listings aren't subtracted:
-- most go up at or above the cheapest price (they don't land in front of you), and you re-undercut when online.
-- Subtracting them all left almost every item at zero speed. Flooded items are still skipped (Status).
local function ResaleSpeed(I)
	return (I.perHour or 0) * Core.PlanRateShare
end
-- Volatile items: the lowest price's 24 h range (lowRange24 = its 10th, 50th, 90th percentile, from the cloud data)
-- spans VolatileRange or more (90th / 10th). On real data 31% of watched items do (crates swing 5-10x in a day).
-- Backtested on 26 h of hourly lows: for these, buying above the bottom quarter of the range and waiting 6 h left the
-- lowest price at 0.975 of the buy (median; 93% didn't make 5%), against 1.00 (82%) when bought in the bottom
-- quarter. So they're flipped only at up to VolatileBuyShare up the range, and resold at no more than the range's
-- middle (the 24 h median of the lowest price), not at what buyers paid at its peaks.
Core.VolatileRange, Core.VolatileBuyShare = 1.6, 0.25
Core.QuantizedBelow = 2 -- sold per hour: under this the hourly median moves in whole-unit steps (see Core.Info)
function Core.Volatile(I)
	local R = I and I.lowRange24
	if type(R) ~= "table" or not R[1] or not R[3] or R[1] <= 0 then return false end
	return R[3] / R[1] >= Core.VolatileRange
end
-- Highest unit price a volatile item may be bought at (nil: not volatile, no limit).
function Core.VolatileBuyMax(I)
	if not Core.Volatile(I) then return nil end
	local R = I.lowRange24
	return math.floor(R[1] + Core.VolatileBuyShare * (R[3] - R[1]))
end
-- Highest resale price the data backs: what buyers paid in the last day and over the longer window (both); for a
-- volatile item also no more than the 24 h median of the lowest price; and never more than the spike cap (the
-- median hourly lowest price over the whole window, lowMed: one burst of buying doesn't raise it; see Farm.SpikeCap).
function Core.ResaleCap(I)
	local A, B = I.med24 or I.med, I.medAll or I.med
	local Cap = (A and B) and math.min(A, B) or A or B
	if Cap and Core.Volatile(I) and I.lowRange24[2] then Cap = math.min(Cap, I.lowRange24[2]) end
	local M = I.lowMed
	if Cap and type(M) == "number" and M > 0 then Cap = math.min(Cap, M) end
	return Cap
end

-- Reselling Qty bought for Cost, with Rest still listed after the purchase: 1c under what's left (you must be the
-- cheapest), never above ResaleCap. Expected profit: the price planned at UndercutHaircut, the AH cut, the chance it
-- sells (sell-through), units that don't sell valued at UnsoldValue of the resale, and the deposit lost on those.
-- Returns an option table, or nil when no price works.
local function Evaluate(I, J, Qty, Cost, Rest)
	local Top = Core.ResaleCap(I)
	if not Top or Qty <= 0 then return nil end
	local Under = Rest[1] and math.min(Rest[1][1] - 1, Top) or Top
	local Dep2 = Core.Deposit and Core.Deposit(I, Core.Durations[1], Qty) or 0
	local Floor = math.ceil((Cost + Dep2) / Qty / (1 - Core.Cut)) + 1
	local H, Idx, Price, Fill = Core.ChooseDuration(J, Qty, Floor, Rest, Under)
	if not H then return nil end
	local Ch = Chance(I)
	local Dep = Core.Deposit and Core.Deposit(I, H, Qty) or 0
	local Net = Price * Qty * (1 - Core.Cut) * Core.UndercutHaircut
	local Profit = math.floor(Net * Ch + Net * (1 - Ch) * Core.UnsoldValue - (1 - Ch) * Dep + 1e-6) - Cost
	return { qty = Qty, buyQty = Qty, cost = Cost, resell = Price, hours = H, durationIndex = Idx, fill = Fill, profit = Profit, chance = Ch }
end

-- The resale for a purchase of Qty for Cost from the data at hand (the live price check uses it). nil when the item
-- isn't a flip target any more or no resale price works.
function Core.Resale(I, Qty, Cost)
	local St = I and Core.FlipStatus(I)
	if St ~= "good" and St ~= "slow" then return nil end
	local VMax = Core.VolatileBuyMax(I)
	if VMax and Qty > 0 and Cost / Qty > VMax then return nil end -- volatile: not near its 24 h low any more
	local Rest, Left = {}, Qty
	for _, Step in ipairs(I.ladder or {}) do
		local Q = Step[2]
		if Left > 0 then local T = math.min(Left, Q); Q = Q - T; Left = Left - T end
		if Q > 0 then Rest[#Rest + 1] = { Step[1], Q } end
	end
	return Evaluate(I, setmetatable({ perHour = ResaleSpeed(I) }, { __index = I }), Qty, Cost, Rest)
end

-- Buy to sell to a vendor: every listing priced under the vendor price (cheapest first), within Cap. A sure profit
-- (vendors pay a fixed price, no AH cut, no deposit), so no sales data is needed. nil when a purchase earns under
-- MinVendorPurchase. Item = item auctions (one purchase each: each must earn it); nil = a commodity (one purchase:
-- the whole of it must earn it).
function Core.VendorDeal(Ladder, Vendor, Cap, Item)
	if not Vendor or Vendor <= 0 or type(Ladder) ~= "table" then return nil end
	Cap = Cap or math.huge
	local Qty, Cost, Profit, Top = 0, 0, 0, nil
	for _, Step in ipairs(Ladder) do
		local P, Q = Step[1], Step[2]
		if not P or P >= Vendor then break end
		if Item and Vendor - P < Core.MinVendorPurchase then break end -- (pricier auctions earn even less)
		local Take = Q
		if P > 0 and Cap < math.huge then Take = math.min(Q, math.floor((Cap - Cost) / P)) end
		if Take <= 0 then break end
		Qty, Cost, Profit, Top = Qty + Take, Cost + Take * P, Profit + Take * (Vendor - P), P
		if Take < Q then break end
	end
	if Qty == 0 or Profit < Core.MinVendorPurchase then return nil end
	return { purchases = Item and Qty or 1, vendor = true, qty = Qty, buyQty = Qty, buyUpTo = Top, cost = Cost, resell = Vendor, hours = 0, profit = Profit, chance = 1 }
end

-- Vendor to AH: buy a batch of something vendors sell and auction it. Offered when the resale (1c under the cheapest
-- listing, never above ResaleCap) after the cut beats the vendor price by VendorFlipMargin, and the batch earns
-- MinVendorPurchase (10s) once sold (.ifSold); its expected profit (.profit: sell-through, unsold units at half, the
-- deposits lost, like any flip) must make a flip's return on the cost too (FlipReturn: 10%, 20% for slow sellers). The batch is VendorFlipHours of the market's sales (fewer when
-- the budget share Cap doesn't cover it). Same item rules as flips (FlipStatus: no weak sellers, no flooded markets). The cheap
-- vendor goods' margins close within days as others notice (Fable review: Skin of Dwarven Stout, Dust of
-- Deterioration, Shiny Red Apple), so the row simply goes away when the margin does.
-- Buying at a vendor takes one click per stack (Stack: the item's stack size; nil = 1, unknown), and every click is a
-- purchase that must earn MinVendorPurchase (10s) of the expected profit (1,542 Mild Spices = 78 clicks for +13s: no).
Core.VendorFlipMargin, Core.VendorFlipHours = 0.30, 8
function Core.VendorFlip(I, Vendor, Cap, Stack)
	if not I or not Vendor or Vendor <= 0 then return nil end
	local St = Core.FlipStatus(I)
	if St ~= "good" and St ~= "slow" then return nil end
	local Qty = math.floor((I.perHour or 0) * Core.VendorFlipHours)
	if Cap and Cap < math.huge then Qty = math.min(Qty, math.floor(Cap / Vendor)) end
	if Qty < 1 then return nil end
	local Rest = {}
	for _, Step in ipairs(I.ladder or {}) do Rest[#Rest + 1] = Step end
	if not Rest[1] then return nil end -- (nothing listed: no price to undercut)
	local O = Evaluate(I, setmetatable({ perHour = ResaleSpeed(I) }, { __index = I }), Qty, Qty * Vendor, Rest)
	if not O or O.resell * (1 - Core.Cut) - Vendor < Core.VendorFlipMargin * Vendor then return nil end
	O.ifSold = math.floor(Qty * (O.resell * (1 - Core.Cut) - Vendor) + 1e-6)
	if O.ifSold < Core.MinVendorPurchase or O.profit < math.ceil(Core.FlipReturn(St) * O.cost - 1e-9) then return nil end
	local Clicks = math.ceil(Qty / math.max(1, math.floor(tonumber(Stack) or 1)))
	if O.profit < Clicks * Core.MinVendorPurchase then return nil end
	O.fromVendor, O.buyUpTo, O.slow, O.purchases = true, Vendor, St == "slow" or nil, Clicks
	return O
end

-- Waylaid Crate fair value: Favor x the Favor price + money back - the cheapest bundle that fills it, bought on the AH
-- (AF_CrateFills from the game data, AF_CrateFavor from Crates.lua). Shown for information: a backtest on 72 h of
-- hourly data (Fable review method) found no gain from using it to pick or rank crate flips (AF's crate picks
-- had no losers; keeping only those under 70% of fair value raised the return but cut the profit by half).
Core.FavorPrice = 250 -- copper per Merchant's Favor, the default of the /af favor setting
-- Cost of N units from the cheapest listings up; nil when fewer are listed.
local function LadderCost(I, N)
	local Cost, Left = 0, N
	for _, Step in ipairs(I and I.ladder or {}) do
		local T = math.min(Left, Step[2])
		Cost, Left = Cost + T * Step[1], Left - T
		if Left <= 0 then return Cost end
	end
	return nil
end
-- nil when the item isn't a crate AF knows. Otherwise { favor, source ("reported", "expected", "confirmed"), coin,
-- favorPrice, options = { { id, n, cost (nil: not enough listed) }, ... cheapest first }, fill (the cheapest
-- option), value (nil when no bundle is listed) }.
function Core.CrateValue(id, InfoFn, FavorPrice)
	local Fills = rawget(_G, "AF_CrateFills") and AF_CrateFills[id]
	local Fav = rawget(_G, "AF_CrateFavor") and AF_CrateFavor[id]
	if type(Fills) ~= "table" or type(Fav) ~= "table" then return nil end
	InfoFn = InfoFn or Core.Info
	local Out = { favor = Fav[1], source = Fav[2] or "reported", coin = Fav[3] or 0, favorPrice = FavorPrice or Core.FavorPrice, options = {} }
	for i = 1, #Fills - 1, 2 do
		local O = { id = Fills[i], n = Fills[i + 1] }
		O.cost = LadderCost(InfoFn(O.id), O.n)
		Out.options[#Out.options + 1] = O
	end
	table.sort(Out.options, function(a, b)
		if (a.cost ~= nil) ~= (b.cost ~= nil) then return a.cost ~= nil end
		if a.cost and a.cost ~= b.cost then return a.cost < b.cost end
		return a.id < b.id
	end)
	local F = Out.options[1]
	if F and F.cost then
		Out.fill = F
		Out.value = math.floor(Out.favor * Out.favorPrice + Out.coin - F.cost + 0.5)
	end
	return Out
end

-- Least return on the cost a flip needs: MinFlipReturnSlow for "slow" sellers, MinFlipReturn otherwise. Speed is an
-- item (its FlipStatus is worked out) or a status string; nil = the item isn't known, so the stricter (slow) return.
function Core.FlipReturn(Speed)
	local St = Speed
	if type(Speed) == "table" then St = Core.FlipStatus(Speed) end
	if St == "good" then return Core.MinFlipReturn end
	return Core.MinFlipReturnSlow
end

-- Least expected profit for a flip costing Cost: MinProfit, and the item's return (FlipReturn) of the cost.
function Core.FlipNeed(Cost, MinProfit, Speed)
	return math.max(MinProfit or Core.MinFlipProfit, math.ceil(Core.FlipReturn(Speed) * Cost - 1e-9))
end

-- Relax (optional): the return each option needs is lowered by this much (and no minimum profit): near misses.
function Core.FlipOptions(I, Cap, MinProfit, Relax)
	local Out = {}
	local St = Core.FlipStatus(I)
	if (St ~= "good" and St ~= "slow") or not Cap or Cap <= 0 then return Out end
	local Ladder = I.ladder
	-- Only the cheapest price levels are kept; if more listings exist above them, the last kept level can't be
	-- bought out (we wouldn't know what you'd be reselling under).
	local Known = 0
	for _, Step in ipairs(Ladder) do Known = Known + Step[2] end
	local MoreAbove = (I.qty or 0) > Known
	local J = setmetatable({ perHour = ResaleSpeed(I) }, { __index = I })
	local VMax = Core.VolatileBuyMax(I) -- volatile: only listings near the bottom of its 24 h range
	-- Never more than the cautious resale speed sells in FlipMaxHours, counting what you already hold of it.
	local MaxQty = math.floor(J.perHour * Core.FlipMaxHours) - (I.held or 0)
	local Qty, Cost = 0, 0
	for Level = 1, #Ladder do
		local P, Q = Ladder[Level][1], Ladder[Level][2]
		if VMax and P > VMax then break end
		local Take = math.min(Q, math.floor((Cap - Cost) / P), MaxQty - Qty)
		if Take <= 0 then break end
		Qty, Cost = Qty + Take, Cost + Take * P
		if Qty >= Core.MaxBuyUnits then break end -- this many to buy: not a flip (nor any bigger one)
		-- What's left after buying: the rest of this level and everything above it.
		local Rest = {}
		if Take < Q then Rest[#Rest + 1] = { P, Q - Take } end
		for j = Level + 1, #Ladder do Rest[#Rest + 1] = Ladder[j] end
		if not Rest[1] and MoreAbove then break end
		local O = Evaluate(I, J, Qty, Cost, Rest)
		local Need = Relax and math.max(0, math.ceil((Core.FlipReturn(St) - Relax) * Cost - 1e-9)) or Core.FlipNeed(Cost, MinProfit, St)
		if O and O.profit >= Need then
			O.buyUpTo, O.slow, O.volatile = P, St == "slow" or nil, VMax and true or nil
			Out[#Out + 1] = O
		end
		if Take < Q then break end
	end
	return Out
end

-- Near miss: a steady seller that isn't a flip now but came close. Its best option (any gold) under rules relaxed by
-- NearMissReturn (the return it needs lowered by that much, no minimum profit). Returns the gap (the return it needs
-- minus the best return found, 0 when only the minimum profit stopped it) and that option; nil when nothing comes
-- that close.
Core.NearMissReturn = 0.10
function Core.NearMiss(I)
	local Best, BestRet
	for _, O in ipairs(Core.FlipOptions(I, math.huge, 0, Core.NearMissReturn)) do
		local R = O.cost > 0 and O.profit / O.cost or 0
		if not BestRet or R > BestRet then Best, BestRet = O, R end
	end
	if not Best then return nil end
	return math.max(0, Core.FlipReturn(Core.FlipStatus(I)) - BestRet), Best
end

-- The best single flip for this item within its share of the budget.
function Core.Flip(I, Budget)
	local Best
	for _, O in ipairs(Core.FlipOptions(I, Budget * Core.ItemShare(Budget), Core.MinFlipProfitFor(Budget))) do
		if not Best or O.profit > Best.profit then Best = O end
	end
	return Best
end

-- The plan: at most one option per item, total cost within Budget, the most total profit. Cands = { {id, options} }.
-- Exact search over (cost, profit) combinations, keeping only the ones not beaten by a cheaper, more profitable one.
-- Returns the chosen { id, option } in buying order (best return on gold first), with .cost and .profit totals.
function Core.Plan(Cands, Budget)
	local States = { { cost = 0, profit = 0 } }
	for _, Cd in ipairs(Cands) do
		local Next = {}
		for _, St in ipairs(States) do
			Next[#Next + 1] = St
			for _, O in ipairs(Cd.options or {}) do
				local Cost = St.cost + O.cost
				if Cost <= Budget then Next[#Next + 1] = { cost = Cost, profit = St.profit + O.profit, pick = { Cd.id, O, St.pick } } end
			end
		end
		table.sort(Next, function(a, b) if a.cost ~= b.cost then return a.cost < b.cost end return a.profit > b.profit end)
		States = {}
		local Top = -1
		for _, St in ipairs(Next) do
			if St.profit > Top then States[#States + 1] = St; Top = St.profit end
		end
		-- Keep the search small: thin very long lists, always keeping the cheapest and the most profitable.
		if #States > 1500 then
			local Thin, Step = {}, #States / 1000
			for k = 1, 1000 do Thin[#Thin + 1] = States[math.floor((k - 1) * Step) + 1] end
			if Thin[#Thin] ~= States[#States] then Thin[#Thin + 1] = States[#States] end
			States = Thin
		end
	end
	local Best = States[#States]
	local Out = { cost = Best.cost, profit = Best.profit }
	local Pk = Best.pick
	while Pk do Out[#Out + 1] = { id = Pk[1], option = Pk[2] }; Pk = Pk[3] end
	table.sort(Out, function(a, b) return a.option.profit / math.max(1, a.option.cost) > b.option.profit / math.max(1, b.option.cost) end)
	return Out
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
		local Price, H, _, Sell = Core.SellPrice(I, Qty, Vendor and math.ceil(Vendor / (1 - Core.Cut)) or 1)
		if Price then
			return math.floor(Sell * Price * (1 - Core.Cut)) + (Qty - Sell) * (Vendor or 0)
		end
	end
	return Qty * (Vendor or 0)
end

-- "1g 02s 05c" style text.
-- Money in Blizzard's coin colors: "1g 02s 03c" with gold, silver and copper colored parts.
local GOLD, SILVER, COPPER = "|cffffd700", "|cffc7c7cf", "|cffeda55f"
function Core.MoneyColor(C)
	if not C then return "-" end
	C = math.floor(C + 0.5)
	-- A loss: a red minus and the amount. (Splitting a negative into coins showed -11s 94c as "88s 06c".)
	if C < 0 then return "|cffff4040-|r" .. Core.MoneyColor(-C) end
	local G, S, Cp = math.floor(C / 10000), math.floor(C / 100) % 100, C % 100
	local P = {}
	if G > 0 then P[#P + 1] = GOLD .. G .. "g|r" end
	if G > 0 then P[#P + 1] = SILVER .. string.format("%02d", S) .. "s|r"
	elseif S > 0 then P[#P + 1] = SILVER .. S .. "s|r" end
	if G > 0 or S > 0 then P[#P + 1] = COPPER .. string.format("%02d", Cp) .. "c|r"
	else P[#P + 1] = COPPER .. Cp .. "c|r" end
	return table.concat(P, " ")
end
-- A gain or loss: a green "+" before a gain, a red "-" before a loss (from MoneyColor).
function Core.MoneyDelta(C)
	if not C then return "-" end
	if math.floor(C + 0.5) > 0 then return "|cff1eff00+|r" .. Core.MoneyColor(C) end
	return Core.MoneyColor(C)
end

-- Sell to the vendor or on the auction house? Returns "Auction" or "Vendor" (nil when neither has a price).
-- Auction only when posting one earns more on average than vendoring it now: the chance it sells x (after the cut
-- - vendor price) must beat the chance it doesn't x the deposit lost (an unsold item comes back to vendor). The
-- deposit is for the duration AF Sell uses: 2 h for steady sellers, 24 h for the rest. Not a proven seller also
-- needs 1.5x the vendor price.
function Core.Recommend(I, Vendor, Price)
	Vendor = Vendor or 0
	Price = Price or (I and Core.Market(I))
	if not Price then return Vendor > 0 and "Vendor" or nil end
	local Net = Price * (1 - Core.Cut)
	if Net <= Vendor then return "Vendor" end
	local S = I and Core.Status(I)
	local Steady = S == "good" or S == "early"
	local Ch = I and Chance(I) or 1
	local H = Steady and Core.Durations[1] or Core.Durations[#Core.Durations]
	local Dep = (I and Core.Deposit and Core.Deposit(I, H, 1)) or 0
	if Ch * (Net - Vendor) <= (1 - Ch) * Dep then return "Vendor" end
	if S == "good" or S == "early" then return "Auction" end
	-- Not a proven seller: worth the AH only if it pays clearly more than the vendor (or the vendor pays nothing).
	if Vendor == 0 or Net >= 1.5 * Vendor then return "Auction" end
	return "Vendor"
end

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
