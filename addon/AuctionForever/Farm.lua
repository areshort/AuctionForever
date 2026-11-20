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
--   Env.deposit(I, H, Q)  -> deposit in copper for Q units posted for H hours, or nil when not known. Default: AF.Core.Deposit.
--   Env.vendor            -> { [item] = vendor price per unit } for reagents vendors sell. Default: AF_RecipeVendor.
--   Env.vendorSell(id)    -> what a vendor pays for one (copper), or nil when not known. Used when that beats the AH.
--   Env.recipes           -> AF_Recipes.  Env.skills -> AF_RecipeSkills.
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
		deposit = Env.deposit or (Core and Core.Deposit),
		vendor = Env.vendor or AF_RecipeVendor or {},
		recipes = Env.recipes or AF_Recipes or {},
		skills = Env.skills or AF_RecipeSkills or {},
		vendorSell = Env.vendorSell,
		cache = {},
	}
end
Farm.Env = Default

-- Fallback status when Core isn't loaded (tests): sells, not flooded or falling.
function Farm.Status(I)
	if not I then return "no data" end
	if (I.perHour or 0) <= 0 then return "slow" end
	if (I.qty or 0) > 24 * I.perHour then return "flooded" end
	if I.med24 and I.medAll and I.med24 < 0.9 * I.medAll then return "falling" end
	return "good"
end

-- Market price planned for a sale: the lower of the last-day and the longer median sold (a falling price counts at
-- its new level), else the cheapest listing; at Haircut.
function Farm.SalePrice(I)
	local A, B = I.med24 or I.med, I.medAll or I.med
	local P = (A and B) and math.min(A, B) or A or B or I.low
	if not P then return nil end
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
-- Returns expected, net when sold (after the cut), chance, rate (nil = not measured), hours, price, deposit known.
function Farm.Expected(I, S, E, Qty)
	Qty = Qty or 1
	local P, H = E.postPrice(I, S)
	if not P then return nil end
	local Rate, Ch = Farm.SellRate(I)
	local Dep = E.deposit and E.deposit(I, H, Qty)
	local Known = type(Dep) == "number"
	local Net = P * (1 - Farm.Cut) * Qty
	return Ch * Net - (1 - Ch) * (Known and Dep or 0), Net, Ch, Rate, H, P, Known
end

local EXCLUDE = { ["no data"] = "no auction data", ["warming up"] = "warming up: too few sales seen yet" }
local function StatusNotes(Row, S, I, Prefix)
	Prefix = Prefix or ""
	if S == "flooded" then Row.notes[#Row.notes + 1] = Prefix .. "flooded: more listed than a day of sales" end
	if S == "falling" then Row.notes[#Row.notes + 1] = Prefix .. "price falling" end
	if S == "slow" then Row.notes[#Row.notes + 1] = Prefix .. "slow: sells in bursts" end
	if S == "early" then Row.notes[#Row.notes + 1] = Prefix .. "early: few hours of sales" end
	if not Farm.SellRate(I) then
		Row.notes[#Row.notes + 1] = string.format("%ssell rate not measured yet: counted as %d%%", Prefix, Farm.UnknownRate * 100)
	end
end

-- One item. Row: id, status, price (AF's post price), hours, net (per unit sold, after the cut), rate (sell-through,
-- nil = not measured), chance (rate used), expected (per unit posted), salesDay (market units sold a day), crafted
-- (it has a recipe), notes, excluded (reason, nil when it ranks).
function Farm.Raw(id, Env)
	local E = Env and Env.cache and Env or Default(Env)
	local I = E.info(id)
	local S = E.status(I)
	local Row = { id = id, status = S, notes = {} }
	if not I or EXCLUDE[S] then Row.excluded = EXCLUDE[S] or "no auction data" return Row end
	local Exp, Net, Ch, Rate, H, P, DepKnown = Farm.Expected(I, S, E, 1)
	if not Exp then Row.excluded = "no price" return Row end
	Row.expected, Row.net, Row.chance, Row.rate, Row.hours, Row.price = Exp, Net, Ch, Rate, H, P
	Row.salesDay = (I.perHour or 0) * 24
	Row.crafted = E.recipes[id] ~= nil
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
		return (a.spell or a.id) < (b.spell or b.id)
	end)
	return In, Out
end
Farm.Rank = Split

-- Farm values for a list of item IDs: ranked rows (best expected each first), then the excluded ones with reasons.
function Farm.RawFarms(Ids, Env)
	local E = Default(Env)
	local Rows = {}
	for _, id in ipairs(Ids) do Rows[#Rows + 1] = Farm.Raw(id, E) end
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
-- [, cooldownSeconds, cooldownCategory] }.
--   sale     = what posting the products is expected to earn (sell-rate weighted, deposit lost when unsold)
--   profit   = products' price after the cut - mats bought (not weighted: if it sells)
--   expected = sale - mats bought (AH ladder, vendor price for vendor goods): the buy-mats ranking
--   added    = sale - what the mats would earn posted or vendored themselves - vendor goods: what crafting adds over
--              selling mats you gathered; self = sale - vendor goods (mats cost you nothing)
-- Unpriced mats: buy mats is excluded; added counts them at 0 and says so.
function Farm.Craft(Product, Recipe, Env)
	local E = Env and Env.cache and Env or Default(Env)
	local Row = { id = Product, spell = Recipe[1], skill = Recipe[2], skillName = E.skills[Recipe[2]], req = Recipe[3],
		makes = Recipe[4], teach = Recipe[6] ~= 0 and Recipe[6] or nil, yellow = Recipe[7], grey = Recipe[8],
		cooldown = Recipe[9], cdCategory = Recipe[10] ~= 0 and Recipe[10] or nil, notes = {}, reagents = {} }
	local I = E.info(Product)
	local S = E.status(I)
	Row.status = S
	if not I or EXCLUDE[S] then Row.excluded = "product: " .. (EXCLUDE[S] or "no auction data") return Row end
	local Sale, Net, Ch, Rate, H, P, DepKnown = Farm.Expected(I, S, E, Row.makes)
	if not Sale then Row.excluded = "product: no price" return Row end
	Row.price, Row.hours, Row.rate, Row.chance = P, H, Rate, Ch
	Row.net = Net / Row.makes
	local VS = E.vendorSell and E.vendorSell(Product)
	if VS and VS * Row.makes > Sale then
		Sale, Net, Row.net = VS * Row.makes, VS * Row.makes, VS
		Row.notes[#Row.notes + 1] = "the product earns more at a vendor than posted on the AH"
	end
	Row.sale = Sale
	Row.salesDay = (I.perHour or 0) * 24
	if Row.salesDay <= 0 then Row.excluded = "product: no sales" return Row end
	if Row.cooldown and Row.cooldown > 0 then
		local T = Row.cooldown >= 3600 and string.format("%.0f h", Row.cooldown / 3600)
			or string.format("%.0f min", Row.cooldown / 60)
		Row.notes[#Row.notes + 1] = "cooldown " .. T .. (Row.cdCategory and " (shared with others in its group)" or "")
	end
	local Regs = Recipe[5]
	local Cost, Mats, Vend, Missing, Unsold = 0, 0, 0, nil, nil
	for i = 1, #Regs - 1, 2 do
		local R, N = Regs[i], Regs[i + 1]
		local Each, Src = Farm.ReagentPrice(R, N, E)
		local SellV = ReagentSellValue(R, E)
		Row.reagents[#Row.reagents + 1] = { id = R, n = N, each = Each, source = Src, sell = SellV }
		if Each then Cost = Cost + Each * N else Missing = Missing or R end
		if Src == "vendor" then Vend = Vend + Each * N
		elseif SellV then Mats = Mats + SellV * N
		else Unsold = Unsold or R end
	end
	Row.vendorCost = Vend
	Row.matsValue = Mats
	Row.added = Sale - Mats - Vend
	Row.self = Sale - Vend
	if Unsold then Row.notes[#Row.notes + 1] = "a mat has no AH price (counted as 0 in value added): " .. Unsold end
	if Missing then
		Row.buyExcluded = "no price for reagent " .. Missing
	else
		Row.cost = Cost
		Row.profit = Net - Cost
		Row.expected = Sale - Cost
		if Row.expected <= 0 then Row.buyExcluded = "expected loss buying the mats" end
	end
	if not DepKnown then Row.notes[#Row.notes + 1] = "deposit not known (counted as 0)" end
	StatusNotes(Row, S, I, "product ")
	return Row
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
