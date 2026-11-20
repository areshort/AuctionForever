-- AuctionForever farm and craft values: what you would actually net per day from farming an item and selling it,
-- and what each craft in AF_Recipes (Recipes.lua) earns when you buy the mats or gather them yourself.
-- Pure Lua (no game calls) so it can be tested offline. All money is in copper.
--
-- Every function takes an Env table so the numbers can come from anywhere:
--   Env.info(id)          -> item numbers like Core.Info (med, med24, medAll, low, qty, perHour, newHour, sellThrough,
--                            ladder, ...) or nil when the item has no auction data. Default: AF.Core.Info.
--   Env.status(I)         -> "good", "early", "slow", "flooded", "falling", "warming up", "no data". Default: AF.Core.Status.
--   Env.deposit(I, H, Q)  -> deposit in copper for Q units posted for H hours, or nil when not known. Default: AF.Core.Deposit.
--   Env.vendor            -> { [item] = vendor price per unit } for reagents vendors sell. Default: AF_RecipeVendor.
--   Env.vendorSell(id)    -> what a vendor pays for one (copper), or nil when not known. Used when that beats the AH.
--   Env.recipes           -> AF_Recipes.  Env.skills -> AF_RecipeSkills.
--   Env.rate(id)          -> units an hour YOU gather of an item (e.g. from AF Sessions), or nil when not known.
--   Env.farmHours         -> hours a day you farm (with rate: caps the units a day at what you can gather). Default 2.
local _, AF = ...
AF = AF or AuctionForever or {}

local Farm = {}
AF.Farm = Farm

Farm.Cut = 0.05          -- auction house cut
Farm.Haircut = 0.97      -- sale price planned 3% under the market price (being undercut now and then)
-- Your share of an item's sales when you farm it and keep posting. Buyers take the cheapest listing first and sellers
-- keep undercutting each other, so the sales go roughly to whoever keeps stock at the front, in proportion to how much
-- each side brings. The others bring newHour units an hour, the buyers take perHour; when you bring at least what the
-- market takes, your part is about perHour / (perHour + newHour). newHour counts every new listing, reposts of
-- expired or undercut stock too, so it overstates competition; MinShare keeps a crowded market from going to zero
-- (you still sell whenever you're the cheapest), MaxShare keeps it cautious (Core.PlanRateShare) when nobody competes.
Farm.MinShare = 0.10
Farm.MaxShare = 0.75
Farm.UnknownShare = 0.50 -- new listings not measured yet
Farm.FloodPenalty = 0.5  -- flooded (more listed than a day of sales): you also have the stock in front to clear
-- Duration used for the deposit lost on posts that don't sell: 2 h for steady sellers (AF Sell posts those short),
-- 24 h for the rest (like Core.Recommend).
Farm.SteadyHours = 2
Farm.PostHours = 24
Farm.MinChance = 0.05
Farm.FarmHours = 2       -- hours a day of farming assumed when your gather rate is known

local function Default(Env)
	Env = Env or {}
	local Core = AF.Core
	return {
		info = Env.info or (Core and Core.Info) or function() return nil end,
		status = Env.status or (Core and Core.Status) or Farm.Status,
		deposit = Env.deposit or (Core and Core.Deposit),
		vendor = Env.vendor or AF_RecipeVendor or {},
		recipes = Env.recipes or AF_Recipes or {},
		skills = Env.skills or AF_RecipeSkills or {},
		rate = Env.rate,
		vendorSell = Env.vendorSell,
		farmHours = Env.farmHours or Farm.FarmHours,
		cache = {},
	}
end
Farm.Env = Default

-- Fallback status when Core isn't loaded (tests): enough sales and not flooded/falling.
function Farm.Status(I)
	if not I then return "no data" end
	if (I.perHour or 0) <= 0 then return "slow" end
	if (I.qty or 0) > 24 * I.perHour then return "flooded" end
	if I.med24 and I.medAll and I.med24 < 0.9 * I.medAll then return "falling" end
	return "good"
end

-- Share of the item's sales you can expect (see Farm.MinShare above).
function Farm.Share(I)
	local P, N = I.perHour or 0, I.newHour
	if P <= 0 then return 0 end
	if not N then return Farm.UnknownShare end
	return math.max(Farm.MinShare, math.min(Farm.MaxShare, P / (P + N)))
end

-- Price a unit sells for: the lower of the last-day and the longer median sold (so a falling price counts at its new
-- level), else the cheapest listing; planned at Haircut.
function Farm.SalePrice(I)
	local A, B = I.med24 or I.med, I.medAll or I.med
	local P = (A and B) and math.min(A, B) or A or B or I.low
	if not P then return nil end
	return P * Farm.Haircut
end

-- What one sold unit nets you: sale price after the AH cut, minus the deposits lost on posts that don't sell (with a
-- sell-through of 60%, every sold unit carries 0.4/0.6 of a lost deposit). S = the item's status (picks the post
-- duration). Returns net, deposit known (bool).
function Farm.NetUnit(I, E, S)
	local P = Farm.SalePrice(I)
	if not P then return nil end
	local Ch = math.max(Farm.MinChance, math.min(1, I.sellThrough or 1))
	local H = (S == "good" or S == "early") and Farm.SteadyHours or Farm.PostHours
	local Dep = E and E.deposit and E.deposit(I, H, 1)
	local Known = type(Dep) == "number"
	return P * (1 - Farm.Cut) - (Known and Dep or 0) * (1 - Ch) / Ch, Known
end

-- Units a day you can expect to sell: the market's sales x your share (halved when flooded).
function Farm.SalesPerDay(I, S)
	local U = (I.perHour or 0) * 24 * Farm.Share(I)
	if S == "flooded" then U = U * Farm.FloodPenalty end
	return U
end

local EXCLUDE = { ["no data"] = "no auction data", ["warming up"] = "warming up: too few sales seen yet" }

-- One item's farm value. Row: id, status, price (market), net (per unit after cut and deposits), share, perDay (units
-- you can sell a day), value (copper a day), crafted (it has a recipe), notes, excluded (reason, nil when it ranks).
-- Without your gather rate, value is what the market lets you sell a day (the most farming it can pay for); with
-- Env.rate it is capped at what you gather in Env.farmHours, and goldPerHour = net x your rate (capped by sales).
function Farm.Raw(id, Env)
	local E = Env and Env.cache and Env or Default(Env)
	local I = E.info(id)
	local S = E.status(I)
	local Row = { id = id, status = S, notes = {} }
	if not I or EXCLUDE[S] then Row.excluded = EXCLUDE[S] or "no auction data" return Row end
	local Net, DepKnown = Farm.NetUnit(I, E, S)
	if not Net then Row.excluded = "no price" return Row end
	Row.price, Row.net, Row.share = Farm.SalePrice(I) / Farm.Haircut, Net, Farm.Share(I)
	Row.perDay = Farm.SalesPerDay(I, S)
	Row.crafted = E.recipes[id] ~= nil
	if Row.perDay <= 0 then Row.value = 0 Row.excluded = "no sales" return Row end
	local Rate = E.rate and E.rate(id)
	if Rate and Rate > 0 then
		Row.rate = Rate
		Row.goldPerHour = math.max(0, Net) * math.min(Rate, Row.perDay / 24)
		Row.perDay = math.min(Row.perDay, Rate * E.farmHours)
	end
	Row.value = math.max(0, Net) * Row.perDay
	if Net <= 0 then Row.excluded = "deposits lost cost more than it sells for" return Row end
	if not DepKnown then Row.notes[#Row.notes + 1] = "deposit not known (counted as 0)" end
	if S == "flooded" then Row.notes[#Row.notes + 1] = "flooded: sales halved" end
	if S == "falling" then Row.notes[#Row.notes + 1] = "price falling: last-day price used" end
	if S == "slow" then Row.notes[#Row.notes + 1] = "slow: sells in bursts" end
	if S == "early" then Row.notes[#Row.notes + 1] = "early: few hours of sales" end
	if not I.newHour then Row.notes[#Row.notes + 1] = "competition not measured (share 50%)" end
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
		return (a.spell or a.id) < (b.spell or b.id)
	end)
	return In, Out
end
Farm.Rank = Split

-- Farm values for a list of item IDs: ranked rows (best gold a day first), then the excluded ones with reasons.
function Farm.RawFarms(Ids, Env)
	local E = Default(Env)
	local Rows = {}
	for _, id in ipairs(Ids) do Rows[#Rows + 1] = Farm.Raw(id, E) end
	return Split(Rows, "value")
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
-- ladder doesn't cover are priced at the market (median) price. Returns price each, source, units available (AH).
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

-- What a reagent would net you if you sold it instead of crafting: the AH net or the vendor price, whichever is more
-- (nil when neither is known). Items with a high vendor price can net less than nothing on the AH (deposits lost).
local function ReagentSellValue(id, E)
	if E.vendor[id] then return nil end
	local I = E.info(id)
	local S = E.status(I)
	local Net = (I and S ~= "no data") and Farm.NetUnit(I, E, S) or nil
	local V = E.vendorSell and E.vendorSell(id)
	if V and V > 0 and (not Net or V > Net) then return V end
	return Net
end

-- One recipe. Recipe = { spell, skillLine, skillReq, makes, {reagent, count, ...}, teachItem, yellow, grey
-- [, cooldownSeconds, cooldownCategory] }.
-- A day of crafts = what the product's sales take (your share) / makes, capped by the cooldown (per character).
-- Buy mats: profit = what the products net - the mats bought (AH ladder for a day's crafts, vendor price for vendor
-- goods); crafts a day further capped by the mats listed on the AH.
-- Gather mats yourself: added = what the products net - what those mats would net if sold - vendor goods bought,
-- i.e. what crafting adds over selling the mats; self = what the products net - vendor goods (all you get when the
-- mats cost you nothing). Unpriced mats: buy mats is excluded; added counts them at 0 and says so.
function Farm.Craft(Product, Recipe, Env)
	local E = Env and Env.cache and Env or Default(Env)
	local Row = { id = Product, spell = Recipe[1], skill = Recipe[2], skillName = E.skills[Recipe[2]], req = Recipe[3],
		makes = Recipe[4], teach = Recipe[6] ~= 0 and Recipe[6] or nil, yellow = Recipe[7], grey = Recipe[8],
		cooldown = Recipe[9], cdCategory = Recipe[10] ~= 0 and Recipe[10] or nil, notes = {}, reagents = {} }
	local I = E.info(Product)
	local S = E.status(I)
	Row.status = S
	if not I or EXCLUDE[S] then Row.excluded = "product: " .. (EXCLUDE[S] or "no auction data") return Row end
	local Net, DepKnown = Farm.NetUnit(I, E, S)
	if not Net then Row.excluded = "product: no price" return Row end
	Row.net, Row.price = Net, Farm.SalePrice(I) / Farm.Haircut
	local VS = E.vendorSell and E.vendorSell(Product)
	if VS and VS > Net then
		Row.net, Net = VS, VS
		Row.notes[#Row.notes + 1] = "the product sells better to a vendor than on the AH"
	end
	Row.crafts = Farm.SalesPerDay(I, S) / Row.makes
	if Row.crafts <= 0 then Row.excluded = "product: no sales" return Row end
	if Row.cooldown and Row.cooldown > 0 and 86400 / Row.cooldown < Row.crafts then
		Row.crafts = 86400 / Row.cooldown
		local T = Row.cooldown >= 3600 and string.format("%.0f h", Row.cooldown / 3600)
			or string.format("%.0f min", Row.cooldown / 60)
		Row.notes[#Row.notes + 1] = "cooldown " .. T .. (Row.cdCategory and " (shared with others in its group)" or "")
	end
	local Gross = Net * Row.makes
	local Regs = Recipe[5]
	local Cost, Mats, Vend, Missing, Unsold = 0, 0, 0, nil, nil
	local Cap = Row.crafts
	for i = 1, #Regs - 1, 2 do
		local R, N = Regs[i], Regs[i + 1]
		local Each, Src, Avail = Farm.ReagentPrice(R, N * math.max(1, Row.crafts), E)
		local SellV = ReagentSellValue(R, E)
		Row.reagents[#Row.reagents + 1] = { id = R, n = N, each = Each, source = Src, sell = SellV }
		if Each then Cost = Cost + Each * N else Missing = Missing or R end
		if Src == "vendor" then Vend = Vend + Each * N
		elseif SellV then Mats = Mats + SellV * N
		else Unsold = Unsold or R end
		if Src == "ah" then Cap = math.min(Cap, Avail / N) end
	end
	Row.vendorCost = Vend
	Row.matsValue = Mats
	Row.added = Gross - Mats - Vend
	Row.addedPerDay = Row.added * Row.crafts
	Row.self = Gross - Vend
	Row.selfPerDay = Row.self * Row.crafts
	if Unsold then Row.notes[#Row.notes + 1] = "a mat has no AH price (counted as 0 in value added): " .. Unsold end
	if Missing then
		Row.buyExcluded = "no price for reagent " .. Missing
	else
		Row.cost = Cost
		Row.profit = Gross - Cost
		Row.buyCrafts = Cap
		Row.profitPerDay = Row.profit * Cap
		if Cap < Row.crafts then Row.notes[#Row.notes + 1] = "mats on the AH limit crafts" end
		if Row.profit <= 0 then Row.buyExcluded = "mats cost more than the product nets" end
	end
	if not DepKnown then Row.notes[#Row.notes + 1] = "deposit not known (counted as 0)" end
	if S == "flooded" then Row.notes[#Row.notes + 1] = "product flooded: sales halved" end
	if S == "falling" then Row.notes[#Row.notes + 1] = "product price falling: last-day price used" end
	if S == "slow" then Row.notes[#Row.notes + 1] = "product slow: sells in bursts" end
	return Row
end

-- Every recipe in Env.recipes whose product has auction data. Returns buy-mats ranking (profit a day), value-added
-- ranking (added a day), and every row (with .excluded / .buyExcluded reasons). Filter(row) -> false drops a recipe
-- (e.g. only professions you have).
function Farm.Crafts(Env, Filter)
	local E = Default(Env)
	local All = {}
	for Product, List in pairs(E.recipes) do
		for _, Recipe in ipairs(List) do
			local R = Farm.Craft(Product, Recipe, E)
			if not Filter or Filter(R) then All[#All + 1] = R end
		end
	end
	local Buy, Added = {}, {}
	for _, R in ipairs(All) do
		if not R.excluded then
			if not R.buyExcluded then Buy[#Buy + 1] = R end
			if R.added > 0 then Added[#Added + 1] = R end
		end
	end
	Buy = (Split(Buy, "profitPerDay"))
	Added = (Split(Added, "addedPerDay"))
	return Buy, Added, All
end
