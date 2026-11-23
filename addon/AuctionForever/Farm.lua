-- AuctionForever farm and craft values: what one item (or one craft) is expected to earn when you post it, weighted
-- by how often it actually sells. A high price that rarely sells isn't worth farming: expected = what you get when it
-- sells x the sell rate (sold / (sold + expired)) - the deposit lost when it doesn't.
-- Pure Lua (no game calls) so it can be tested offline. All money is in copper.
--
-- Every function takes an Env table so the numbers can come from anywhere:
--   Env.info(id)          -> item numbers like Core.Info (med, med24, medAll, low, perHour, sellThrough, ladder, ...) or
--                            nil when the item has no auction data. Default: AF.Core.Info.
--   Env.status(I)         -> "good", "early", "slow", "flooded", "falling", "warming up", "no data". Default: AF.Core.Status.
--   Env.postPrice(I, S)   -> the price and duration (hours) AF would post one at. Default: Farm.PostPrice.
--   Env.priceCap(I)       -> optional: the most a sale is valued at (what buyers actually paid, e.g. Core.ResaleCap): a
--                            lone listing far above the sales never sets the value. Default: none.
--   Env.minSalesHours     -> optional: a crafted product needs this many hours with sales to be valued on the AH.
--   Env.deposit(I, H, Q)  -> deposit in copper for Q units posted for H hours, or nil when not known. Default: AF.Core.Deposit.
--   Env.vendor            -> { [item] = vendor price per unit } for reagents vendors sell. Default: AF_RecipeVendor.
--   Env.vendorSell(id)    -> what a vendor pays for one (copper), or nil when not known. Used when that beats the AH.
--   Env.recipes           -> AF_Recipes.  Env.skills -> AF_RecipeSkills.
--   Env.classOf(id)       -> item class and subclass IDs (no server call), or nil. Default: C_Item.GetItemInfoInstant.
local _, AF = ...
AF = AF or AuctionForever or {}

local Farm = {}
AF.Farm = Farm

Farm.Cut = 0.05          -- auction house cut
Farm.Haircut = 0.97      -- fallback post price: 3% under the market price (being undercut now and then)
-- Fallback duration for the deposit lost on posts that don't sell: 2 h for steady sellers, 24 h for the rest.
Farm.SteadyHours = 2
Farm.PostHours = 24
-- Sell rate used when it isn't measured yet (no posts seen ending): a cautious coin flip, shown as "?".
Farm.UnknownRate = 0.5
Farm.MinChance = 0.05

local function Default(Env)
	Env = Env or {}
	local Core = AF.Core
	return {
		info = Env.info or (Core and Core.Info) or function() return nil end,
		status = Env.status or (Core and Core.Status) or Farm.Status,
		postPrice = Env.postPrice or Farm.PostPrice,
		priceCap = Env.priceCap,
		minSalesHours = Env.minSalesHours,
		deposit = Env.deposit or (Core and Core.Deposit),
		vendor = Env.vendor or AF_RecipeVendor or {},
		recipes = Env.recipes or AF_Recipes or {},
		skills = Env.skills or AF_RecipeSkills or {},
		vendorSell = Env.vendorSell,
		classOf = Env.classOf or Farm.ClassOf,
		cache = {},
	}
end
Farm.Env = Default

-- Item class and subclass without asking the server (GetItemInfoInstant is local data).
function Farm.ClassOf(id)
	local CI = rawget(_G, "C_Item")
	local F = CI and CI.GetItemInfoInstant
	if not F then return nil end
	local _, _, _, _, _, Class, Sub = F(id)
	return Class, Sub
end
-- Where an item comes from: "Crafted" (a recipe makes it, or a profession tool such as the Salt Shaker), "Vendor"
-- (sold by vendors: thread, flux, salt...; nothing to farm), "Gather" (gathering professions: herbs, ore and stone,
-- leather and hides, the gems mining finds, fish) or "Drop" (everything else).
Farm.GATHER_SUB = { [9] = true, [7] = true, [6] = true } -- trade goods: Herb, Metal & Stone, Leather
-- Mining gems and fishing catches (their subclasses also hold drops, so by item ID; from Forever's item data).
Farm.GATHER_IDS = {}
for _, id in ipairs({ 774, 818, 1210, 1206, 1705, 1529, 3864, 7909, 7910, 12799, 12361, 12364, 12800, 12363, -- gems
	4603, 6289, 6291, 6303, 6308, 6317, 6361, 6362, 8365, 8959, 13754, 13755, 13756, 13758, 13759, 13760, 13889, 13890,
	21071, 21153, 6358, 6359, 6522, 7973, 12238, 13422, 13757, 13888 }) do Farm.GATHER_IDS[id] = true end -- fish
function Farm.Source(id, Env)
	local E = Env and Env.cache and Env or Default(Env)
	if E.recipes[id] then return "Crafted" end
	if E.vendor[id] then return "Vendor" end
	if Farm.GATHER_IDS[id] then return "Gather" end
	local Class, Sub = E.classOf(id)
	if Class == 7 and Farm.GATHER_SUB[Sub] then return "Gather" end
	return "Drop"
end

-- Fallback status when Core isn't loaded (tests): sells, not flooded or falling.
function Farm.Status(I)
	if not I then return "no data" end
	if (I.perHour or 0) <= 0 then return "slow" end
	if (I.qty or 0) > 24 * I.perHour then return "flooded" end
	if I.med24 and I.medAll and I.med24 < 0.9 * I.medAll then return "falling" end
	return "good"
end

-- Spike guard. lowMed (from the cloud data) = the median of the hourly lowest price over the whole window, one vote
-- per hour. Both sold-price medians weigh units, so one burst of buying at a spike moves them (EZ-Thro Wrap sat at
-- 8-11s for two days, jumped to 60-98s for an evening, and both medians read 38s after); lowMed doesn't. A sale is
-- valued at no more than it. Old data files have no lowMed: no cap.
Farm.SpikeRatio = 3
function Farm.SpikeCap(I)
	local M = I and I.lowMed
	if type(M) == "number" and M > 0 then return M end
	return nil
end
-- The last day's prices (its sold median or the cheapest listing) are SpikeRatio times lowMed or more.
function Farm.Spike(I)
	local M = Farm.SpikeCap(I)
	if not M then return false end
	return math.max(I.med24 or 0, I.low or 0) >= Farm.SpikeRatio * M
end
Farm.SPIKE_NOTE = "price tripled in 24 h: valued at its usual lowest price"

-- Market price planned for a sale: the lower of the last-day and the longer median sold (a falling price counts at
-- its new level), else the cheapest listing; never above the spike cap; at Haircut.
function Farm.SalePrice(I)
	local A, B = I.med24 or I.med, I.medAll or I.med
	local P = (A and B) and math.min(A, B) or A or B or I.low
	if not P then return nil end
	local M = Farm.SpikeCap(I)
	if M and P > M then P = M end
	return P * Farm.Haircut
end
-- Fallback post price and duration (the UI passes AF Sell's own suggestion).
function Farm.PostPrice(I, S)
	return Farm.SalePrice(I), (S == "good" or S == "early") and Farm.SteadyHours or Farm.PostHours
end

-- Sell rate: measured sell-through, or nil when not known. Chance: the rate used (UnknownRate when not known).
function Farm.SellRate(I)
	local R = I and I.sellThrough
	if type(R) ~= "number" then return nil, Farm.UnknownRate end
	return R, math.max(Farm.MinChance, math.min(1, R))
end

-- Expected result of posting Qty units: chance x (price after the cut) - (1 - chance) x the deposit lost.
-- Returns expected, net when sold (after the cut), chance, rate (nil = not measured), hours, price, deposit known,
-- capped (the price was cut to Env.priceCap: what buyers paid).
function Farm.Expected(I, S, E, Qty)
	Qty = Qty or 1
	local P, H = E.postPrice(I, S)
	if not P then return nil end
	local Cap = E.priceCap and E.priceCap(I)
	local Capped
	if type(Cap) == "number" and Cap > 0 and P > Cap then P, Capped = Cap, true end
	local M = Farm.SpikeCap(I)
	if M and P > M then P, Capped = M, true end
	local Rate, Ch = Farm.SellRate(I)
	local Dep = E.deposit and E.deposit(I, H, Qty)
	local Known = type(Dep) == "number"
	local Net = P * (1 - Farm.Cut) * Qty
	return Ch * Net - (1 - Ch) * (Known and Dep or 0), Net, Ch, Rate, H, P, Known, Capped
end
local CAPPED_NOTE = "priced at what buyers paid (listed far higher)"

local EXCLUDE = { ["no data"] = "no auction data", ["warming up"] = "warming up: too few sales seen yet" }
local function StatusNotes(Row, S, I, Prefix)
	Prefix = Prefix or ""
	if S == "flooded" then Row.notes[#Row.notes + 1] = Prefix .. "flooded: more listed than a day of sales" end
	if S == "falling" then Row.notes[#Row.notes + 1] = Prefix .. "price falling" end
	if S == "slow" then Row.notes[#Row.notes + 1] = Prefix .. "slow: sells in bursts" end
	if S == "early" then Row.notes[#Row.notes + 1] = Prefix .. "early: few hours of sales" end
	if Farm.Spike(I) then Row.notes[#Row.notes + 1] = Prefix .. Farm.SPIKE_NOTE; Row.spike = true end
	if not Farm.SellRate(I) then
		Row.notes[#Row.notes + 1] = string.format("%ssell rate not measured yet: counted as %d%%", Prefix, Farm.UnknownRate * 100)
	end
end

-- One item. Row: id, status, price (AF's post price), hours, net (per unit sold, after the cut), rate (sell-through,
-- nil = not measured), chance (rate used), expected (per unit posted), salesDay (market units sold a day), crafted
-- (it has a recipe), notes, excluded (reason, nil when it ranks).
-- id: an item ID, or a suffix version's market key ("itemID:bonus"; the row's id is then the item ID, .key the key).
function Farm.Raw(id, Env)
	local E = Env and Env.cache and Env or Default(Env)
	local I = E.info(id)
	local S = E.status(I)
	local Key = type(id) == "string" and id or nil
	if Key then id = tonumber(Key:match("^(%d+)")) end
	local Row = { id = id, key = Key, status = S, notes = {} }
	if not I or EXCLUDE[S] then Row.excluded = EXCLUDE[S] or "no auction data" return Row end
	local Exp, Net, Ch, Rate, H, P, DepKnown, Capped = Farm.Expected(I, S, E, 1)
	if not Exp then Row.excluded = "no price" return Row end
	if Capped then Row.capped = true; Row.notes[#Row.notes + 1] = CAPPED_NOTE end
	Row.expected, Row.net, Row.chance, Row.rate, Row.hours, Row.price = Exp, Net, Ch, Rate, H, P
	Row.salesDay = (I.perHour or 0) * 24
	Row.crafted = E.recipes[id] ~= nil
	Row.source = Farm.Source(id, E)
	if Row.salesDay <= 0 then Row.excluded = "no sales" return Row end
	if Exp <= 0 then Row.excluded = "expected loss: deposits lost outweigh the sales" return Row end
	if not DepKnown then Row.notes[#Row.notes + 1] = "deposit not known (counted as 0)" end
	StatusNotes(Row, S, I)
	return Row
end

local function Split(Rows, Key)
	local In, Out = {}, {}
	for _, R in ipairs(Rows) do
		if R.excluded then Out[#Out + 1] = R else In[#In + 1] = R end
	end
	table.sort(In, function(a, b)
		local x, y = a[Key] or -math.huge, b[Key] or -math.huge
		if x ~= y then return x > y end
		if (a.spell or a.id) ~= (b.spell or b.id) then return (a.spell or a.id) < (b.spell or b.id) end
		return tostring(a.key or "") < tostring(b.key or "")
	end)
	return In, Out
end
Farm.Rank = Split

-- Farm values for a list of item IDs: ranked rows (best expected each first), then the excluded ones with reasons.
function Farm.RawFarms(Ids, Env)
	local E = Default(Env)
	local Rows = {}
	for _, id in ipairs(Ids) do
		Rows[#Rows + 1] = Farm.Raw(id, E)
		if Farm.Yield then Farm.Yield() end -- (set only while the UI builds the lists in the background)
	end
	return Split(Rows, "expected")
end

-- Buying Qty units from the cheapest listings up (the ladder). Returns total cost, units the ladder covers.
function Farm.BuyCost(I, Qty)
	local Cost, Got = 0, 0
	for _, Step in ipairs(I.ladder or {}) do
		local Take = math.min(Step[2], Qty - Got)
		if Take <= 0 then break end
		Cost, Got = Cost + Take * Step[1], Got + Take
	end
	return Cost, Got
end

-- What a reagent costs per unit when buying Qty: the vendor price for vendor goods, else the ladder; units the
-- ladder doesn't cover are priced at the upper sold price. Returns price each, source, units listed (AH).
function Farm.ReagentPrice(id, Qty, E)
	local V = E.vendor[id]
	if V then return V, "vendor", math.huge end
	local I = E.info(id)
	if not I then return nil, "none", 0 end
	Qty = math.max(1, Qty)
	local Cost, Got = Farm.BuyCost(I, Qty)
	local Fill = I.hi or I.med or I.low
	if Got < Qty then
		if not Fill then
			if Got == 0 then return nil, "none", 0 end
			Fill = Cost / Got
		end
		Cost = Cost + (Qty - Got) * Fill
	end
	return Cost / Qty, "ah", Got
end

-- Units of an item listed now (the whole ladder).
local function Listed(I)
	local N = 0
	for _, Step in ipairs(I and I.ladder or {}) do N = N + Step[2] end
	return N
end
Farm.Listed = Listed
Farm.LOSS = "expected loss buying the mats"

-- What a reagent would earn if you posted it instead of crafting (expected, sell-rate weighted) or vendored it,
-- whichever is more; nil when neither is known.
local function ReagentSellValue(id, E)
	if E.vendor[id] then return nil end
	local I = E.info(id)
	local S = E.status(I)
	local Exp = (I and S ~= "no data") and Farm.Expected(I, S, E, 1) or nil
	local V = E.vendorSell and E.vendorSell(id)
	if V and V > 0 and (not Exp or V > Exp) then return V end
	return Exp
end

-- One recipe. Recipe = { spell, skillLine, skillReq, makes, {reagent, count, ...}, teachItem, yellow, grey
-- [, cooldownSeconds, cooldownCategory] }. Mats are bought for one craft: the AH ladder (vendor goods at the vendor
-- price); matCrafts = how many crafts the mats listed now allow (math.huge: vendor goods only).
-- Two ways to sell what it makes (route):
--   "AH":     ahExpected = what posting the products is expected to earn (sell-rate weighted, deposit lost when
--             unsold) - mats; ahProfit = products' price after the cut - mats (if it sells).
--   "Vendor": vendorProfit = vendor price x makes - mats: a sure sale (no cut, no deposit), only when the mats listed
--             now cover a craft.
-- The route with the higher expected profit wins: expected / profit / rate (1 for the vendor) follow it.
--   added = best sale - what the mats would earn posted or vendored themselves - vendor goods: what crafting adds over
--           selling mats you gathered; self = best sale - vendor goods (mats cost you nothing).
-- Unpriced mats: buying them is excluded; added counts them at 0 and says so.
function Farm.Craft(Product, Recipe, Env)
	local E = Env and Env.cache and Env or Default(Env)
	local Row = { id = Product, spell = Recipe[1], skill = Recipe[2], skillName = E.skills[Recipe[2]], req = Recipe[3],
		makes = Recipe[4], teach = Recipe[6] ~= 0 and Recipe[6] or nil, yellow = Recipe[7], grey = Recipe[8],
		cooldown = Recipe[9], cdCategory = Recipe[10] ~= 0 and Recipe[10] or nil, notes = {}, reagents = {}, source = "Crafted" }
	local I = E.info(Product)
	local S = E.status(I)
	Row.status = S
	-- Selling on the AH: needs auction data with sales.
	local AHWhy, Sale, Net, DepKnown
	if not I or EXCLUDE[S] then AHWhy = "product: " .. (EXCLUDE[S] or "no auction data")
	elseif E.minSalesHours and (I.hoursWithSales or 0) < E.minSalesHours then AHWhy = "product: too few hours with sales"
	else
		local Ch, Rate, H, P, Capped
		Sale, Net, Ch, Rate, H, P, DepKnown, Capped = Farm.Expected(I, S, E, Row.makes)
		if not Sale then AHWhy = "product: no price"
		else
			if Capped then Row.capped = true; Row.notes[#Row.notes + 1] = "product " .. CAPPED_NOTE end
			Row.price, Row.hours, Row.rate, Row.chance = P, H, Rate, Ch
			Row.net = Net / Row.makes
			Row.salesDay = (I.perHour or 0) * 24
			if Row.salesDay <= 0 then AHWhy = "product: no sales" end
		end
	end
	if AHWhy then Sale, Net = nil, nil end
	local VS = E.vendorSell and E.vendorSell(Product)
	if VS and VS <= 0 then VS = nil end
	Row.vendorSell = VS
	if not Sale and not VS then Row.excluded = AHWhy return Row end
	Row.salesDay = Row.salesDay or 0
	if Row.cooldown and Row.cooldown > 0 then
		local T = Row.cooldown >= 3600 and string.format("%.0f h", Row.cooldown / 3600)
			or string.format("%.0f min", Row.cooldown / 60)
		Row.notes[#Row.notes + 1] = "cooldown " .. T .. (Row.cdCategory and " (shared with others in its group)" or "")
	end
	local Regs = Recipe[5]
	local Cost, Mats, Vend, Missing, Unsold, MatCrafts = 0, 0, 0, nil, nil, math.huge
	for i = 1, #Regs - 1, 2 do
		local R, N = Regs[i], Regs[i + 1]
		local Each, Src = Farm.ReagentPrice(R, N, E)
		local SellV = ReagentSellValue(R, E)
		Row.reagents[#Row.reagents + 1] = { id = R, n = N, each = Each, source = Src, sell = SellV }
		if Each then Cost = Cost + Each * N else Missing = Missing or R end
		if Src == "vendor" then Vend = Vend + Each * N
		else
			MatCrafts = math.min(MatCrafts, math.floor(Listed(E.info(R)) / N))
			if SellV then Mats = Mats + SellV * N else Unsold = Unsold or R end
		end
	end
	Row.matCrafts = MatCrafts
	Row.vendorCost = Vend
	Row.matsValue = Mats
	local Best = math.max(Sale or 0, VS and VS * Row.makes or 0)
	if VS and VS * Row.makes > (Sale or 0) and Sale then
		Row.notes[#Row.notes + 1] = "the product earns more at a vendor than posted on the AH"
	end
	Row.sale = Best
	Row.added = Best - Mats - Vend
	Row.self = Best - Vend
	if Unsold then Row.notes[#Row.notes + 1] = "a mat has no AH price (counted as 0 in value added): " .. Unsold end
	if Missing then
		Row.buyExcluded = "no price for reagent " .. Missing
		Row.route = Sale and "AH" or "Vendor"
	else
		Row.cost = Cost
		if Sale then Row.ahProfit, Row.ahExpected = Net - Cost, Sale - Cost end
		if VS and MatCrafts >= 1 then Row.vendorProfit = VS * Row.makes - Cost end
		if Row.vendorProfit and (not Row.ahExpected or Row.vendorProfit > Row.ahExpected) then
			Row.route, Row.profit, Row.expected = "Vendor", Row.vendorProfit, Row.vendorProfit
		elseif Row.ahExpected then
			Row.route, Row.profit, Row.expected = "AH", Row.ahProfit, Row.ahExpected
		end
		if not Row.expected then Row.buyExcluded = AHWhy or "not enough mats listed"
		elseif Row.expected <= 0 then Row.buyExcluded = Farm.LOSS end
	end
	if not Row.expected and not Sale then Row.excluded = AHWhy return Row end
	if Row.route == "Vendor" then Row.vendorRoute = true end
	if Sale and not DepKnown then Row.notes[#Row.notes + 1] = "deposit not known (counted as 0)" end
	if Sale then StatusNotes(Row, S, I, "product ") end
	return Row
end

-- Buying the mats for N crafts of one recipe row (Farm.Craft), for AF Buy. N is the most crafts that:
--   the mats listed now allow (matCrafts);
--   the product's sales support within Opts.hours (AH route: Opts.share of the measured sales per hour, less what
--   you already hold; the vendor route has no such limit, only Opts.maxCrafts);
--   cost no more than Opts.cap (one item's share of the budget);
--   still pay for the last craft (mats get dearer up the price ladders).
-- Selling on the AH is judged more strictly than the Farm view does: the product needs Opts.minSalesHours hours with
-- sales, and its post price is capped at Opts.resaleCap(I) (what buyers actually paid): a lone listing far above
-- the sales (2 Woolen Boots listed at 9g, sold at 6s) isn't a price you can sell at. When that makes the vendor pay
-- more, the plan sells to the vendor.
-- Like flips, only products whose status is in Opts.ahStatus (e.g. good / slow; not "flooded": new listings far
-- outpacing sales) are sold on the AH; otherwise the vendor route if it pays, else nil, that status.
-- Cooldown recipes: at most the crafts the cooldown allows within Opts.hours, after Opts.cooldownLeft(row) seconds
-- still to wait (the game's cooldown on the recipe spell); nil, "cooldown", seconds left when it won't be ready in time.
-- Returns nil when not even one craft fits, or the plan's expected profit is under Opts.need(cost, row).
-- The plan: { craft, crafts, makes, units, cost (AH mats + vendor goods), profit (expected), route, resell (per
-- unit: post price or vendor price), saleEach (expected per craft), mats = { {id, qty, upTo, cost} } (AH, in recipe
-- order, only what must be bought), vendorGoods = { {id, qty, cost} }, vendorCost, list (the shopping list: one entry
-- per reagent and source, { id, qty, source = "AH" / "Vendor" / "Owned" / "Bank", each (vendor price), upTo (AH: the
-- most to pay each), cost }, grouped by source in that order, recipe order within a group) }.
-- Per craft: craftSale (what one craft is expected to bring: the AH sale after the cut and sell rate, or the vendor
-- price), craftCost (its mats at the plan's average price each; a mat you hold at today's cheapest listing),
-- craftProfit. Each AH mat (mats and list) has a target: the most to pay per unit for one craft to still clear its
-- bar (Opts.ret(route, Row): the return it needs; the AH route defaults to 10%, the vendor route to 0), with the
-- other mats at their planned average price: (craftSale / (1 + return) - the other mats) / the count of this mat.
-- Opts.force: a plan of at least one craft even when none fits today (to show what to pay); overTarget = why:
-- "over budget" (one craft's mats cost more than your budget share) or "over target" (no craft clears its bar).
-- Opts.held(id) / Opts.bank(id): units of a reagent in your bags / your bank. They're used first (bags, then bank):
-- only the rest is bought, the plan's cost counts only what's bought, and the mats listed plus what you hold bound N.
local function UpTo(I, Qty)
	local Got, Top = 0, nil
	for _, Step in ipairs(I and I.ladder or {}) do
		if Got >= Qty then break end
		Got, Top = Got + Step[2], Step[1]
	end
	return Top
end
function Farm.CraftPlan(Row, Opts, Env)
	local E = Env and Env.cache and Env or Default(Env)
	Opts = Opts or {}
	local Loss = Row and Row.buyExcluded == Farm.LOSS and Opts.force -- (forced: show the targets anyway)
	if not Row or Row.excluded or (Row.buyExcluded and not Loss) or not Row.expected or not Row.cost or not Row.route then return nil end
	local I = E.info(Row.id)
	local VSum = (Row.matCrafts or 0) >= 1 and Row.vendorSell and Row.vendorSell * Row.makes or nil
	local Vendor = Row.route == "Vendor"
	local Each = Vendor and VSum or (Row.ahExpected + Row.cost)
	local Price, Capped, Blocked = Row.price, Row.capped, nil
	if not Vendor then
		if Opts.ahStatus and not Opts.ahStatus[Row.status] then Each, Blocked = nil, Row.status end
		if Opts.minSalesHours and (not I or (I.hoursWithSales or 0) < Opts.minSalesHours) then Each = nil end
		local Top = Each and Opts.resaleCap and I and Opts.resaleCap(I)
		if Top and Price and Price > Top then
			local E2 = setmetatable({ postPrice = function(I2, S)
				local P, H = E.postPrice(I2, S)
				if P and P > Top then P = Top end
				return P, H
			end }, { __index = E })
			Each, Price, Capped = (Farm.Expected(I, Row.status, E2, Row.makes)), Top, true
		end
		if VSum and (not Each or VSum > Each) then Vendor, Each = true, VSum end
	end
	if not Each or Each <= 0 then return nil, Blocked end
	local Held = {}
	local InBags, InBank = {}, {}
	for _, R in ipairs(Row.reagents) do
		InBags[R.id] = Opts.held and Opts.held(R.id) or 0
		InBank[R.id] = Opts.bank and Opts.bank(R.id) or 0
		Held[R.id] = InBags[R.id] + InBank[R.id]
	end
	local Max = math.huge
	for _, R in ipairs(Row.reagents) do
		if R.source ~= "vendor" then Max = math.min(Max, math.floor((Listed(E.info(R.id)) + Held[R.id]) / R.n)) end
	end
	if not Vendor then
		local Units = (I and I.perHour or 0) * (Opts.share or 1) * (Opts.hours or 8) - (I and I.held or 0)
		Max = math.min(Max, math.floor(Units / Row.makes))
	end
	local CdLeft
	if (Row.cooldown or 0) > 0 then
		local Window = (Opts.hours or 8) * 3600
		CdLeft = Opts.cooldownLeft and Opts.cooldownLeft(Row) or 0
		if CdLeft >= Window then return nil, "cooldown", CdLeft end
		Max = math.min(Max, 1 + math.floor((Window - CdLeft) / Row.cooldown))
	end
	Max = math.min(Max, Opts.maxCrafts or 1000)
	if Max < 1 then return nil, Blocked end
	local function Buy(R, N) return math.max(0, R.n * N - Held[R.id]) end
	local function Cost(N)
		local C = 0
		for _, R in ipairs(Row.reagents) do
			if R.source == "vendor" then C = C + R.each * Buy(R, N)
			else C = C + (Farm.BuyCost(E.info(R.id), Buy(R, N))) end
		end
		return C
	end
	local Cap = Opts.cap or math.huge
	-- Both limits only tighten as N grows (cost rises, the last craft's mats never get cheaper): binary search.
	local function Fits(N)
		local C = Cost(N)
		return C <= Cap and C - Cost(N - 1) <= Each
	end
	local Lo, Hi = 0, Max
	while Lo < Hi do
		local Mid = math.floor((Lo + Hi + 1) / 2)
		if Fits(Mid) then Lo = Mid else Hi = Mid - 1 end
	end
	local N = Lo
	local Forced
	if N < 1 then
		if not Opts.force then return nil, Blocked end
		-- Why no craft fits: one craft's mats cost more than your budget share, or than it brings.
		N, Forced = 1, Cost(1) > Cap and "over budget" or "over target"
	end
	local Mats, Goods, VCost = {}, {}, 0
	local Group = { AH = {}, Vendor = {}, Owned = {}, Bank = {} }
	for _, R in ipairs(Row.reagents) do
		local Q = Buy(R, N)
		local FromBags = math.min(R.n * N - Q, InBags[R.id])
		local FromBank = R.n * N - Q - FromBags
		if FromBags > 0 then table.insert(Group.Owned, { id = R.id, qty = FromBags, source = "Owned", cost = 0 }) end
		if FromBank > 0 then table.insert(Group.Bank, { id = R.id, qty = FromBank, source = "Bank", cost = 0 }) end
		if Q > 0 then
			if R.source == "vendor" then
				Goods[#Goods + 1] = { id = R.id, qty = Q, cost = R.each * Q }
				VCost = VCost + R.each * Q
				table.insert(Group.Vendor, { id = R.id, qty = Q, source = "Vendor", each = R.each, cost = R.each * Q })
			else
				local I = E.info(R.id)
				-- upTo: the price of the last ladder level the plan buys from. The Buy flow cancels a mat whose live
				-- price is above it, so it's the most to pay each.
				local M = { id = R.id, qty = Q, upTo = UpTo(I, Q), cost = (Farm.BuyCost(I, Q)) }
				Mats[#Mats + 1] = M
				table.insert(Group.AH, { id = R.id, qty = Q, source = "AH", upTo = M.upTo, cost = M.cost })
			end
		end
	end
	local List = {}
	for _, G in ipairs({ "AH", "Vendor", "Owned", "Bank" }) do
		for _, X in ipairs(Group[G]) do List[#List + 1] = X end
	end
	local Total = Cost(N)
	local Profit = math.floor(Each * N - Total + 1e-6)
	local Need = Opts.need and Opts.need(Total, Row) or 0
	if Profit < Need and not Opts.force then return nil, Blocked end
	if Profit < Need and not Forced then Forced = "over target" end
	-- Per craft, and each AH mat's target price.
	local UnitP = {}
	for _, R in ipairs(Row.reagents) do
		if R.source == "vendor" then
			UnitP[R.id] = R.each
		else
			local Q = Buy(R, N)
			local RI = E.info(R.id)
			if Q > 0 then UnitP[R.id] = Farm.BuyCost(RI, Q) / Q
			else UnitP[R.id] = (RI and RI.ladder and RI.ladder[1] and RI.ladder[1][1]) or (RI and RI.low) or 0 end
		end
	end
	local PerCraft = 0
	for _, R in ipairs(Row.reagents) do PerCraft = PerCraft + UnitP[R.id] * R.n end
	local Route = Vendor and "Vendor" or "AH"
	local Ret = Opts.ret and Opts.ret(Route, Row) or (Vendor and 0 or 0.10)
	local Allowed = Each / (1 + Ret)
	local Target = {}
	for _, R in ipairs(Row.reagents) do
		if R.source ~= "vendor" then Target[R.id] = math.max(0, math.floor((Allowed - (PerCraft - UnitP[R.id] * R.n)) / R.n + 1e-6)) end
	end
	for _, M in ipairs(Mats) do M.target = Target[M.id] end
	for _, X in ipairs(List) do if X.source == "AH" then X.target = Target[X.id] end end
	return { craft = true, craftSale = math.floor(Each + 1e-6), craftCost = math.floor(PerCraft + 0.5), craftProfit = math.floor(Each - PerCraft + 1e-6),
		overTarget = Forced, crafts = N, makes = Row.makes, units = N * Row.makes, cost = Total, profit = Profit,
		route = Vendor and "Vendor" or "AH", resell = Vendor and Row.vendorSell or Price, hours = Row.hours, chance = Vendor and 1 or Row.chance,
		saleEach = Each, mats = Mats, vendorGoods = Goods, vendorCost = VCost, list = List, buyQty = N, buyUpTo = 0, capped = Capped,
		sales = I and I.sales, salesHours = I and I.hoursWithSales, cooldown = Row.cooldown, cooldownLeft = CdLeft }
end

-- Every recipe in Env.recipes whose product has auction data. Returns the buy-mats ranking (expected a craft), the
-- value-added ranking (added a craft), and every row (with .excluded / .buyExcluded reasons). Filter(row) -> false
-- drops a recipe (e.g. only professions you have).
function Farm.Crafts(Env, Filter)
	local E = Default(Env)
	local All = {}
	for Product, List in pairs(E.recipes) do
		for _, Recipe in ipairs(List) do
			local R = Farm.Craft(Product, Recipe, E)
			if not Filter or Filter(R) then All[#All + 1] = R end
			if Farm.Yield then Farm.Yield() end
		end
	end
	local Buy, Added = {}, {}
	for _, R in ipairs(All) do
		if not R.excluded then
			if not R.buyExcluded then Buy[#Buy + 1] = R end
			if R.added > 0 then Added[#Added + 1] = R end
		end
	end
	Buy = (Split(Buy, "expected"))
	Added = (Split(Added, "added"))
	return Buy, Added, All
end
