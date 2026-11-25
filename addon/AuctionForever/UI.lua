-- AuctionForever window, minimap button, tooltips and farming sessions.
local _, AF = ...
local Core = AF.Core
local L = {}

local ROWS = 14
local ROW_H = 22
local TABS = { "Farm", "Flip", "Sessions" }

-- Saved data -----------------------------------------------------------------------------------------------------
local function Char()
	AuctionForeverChar = AuctionForeverChar or {}
	local C = AuctionForeverChar
	C.sessions = C.sessions or {}
	return C
end
local function Account()
	AuctionForeverDB = AuctionForeverDB or {}
	AuctionForeverDB.minimapAngle = AuctionForeverDB.minimapAngle or 220
	return AuctionForeverDB
end

-- Item helpers ---------------------------------------------------------------------------------------------------
local Pending = {}
local function NameCache()
	AuctionForeverDB = AuctionForeverDB or {}
	AuctionForeverDB.names = AuctionForeverDB.names or {}
	return AuctionForeverDB.names
end
-- Saved per item: { name, quality, vendor price, stack size }, learned whenever the game has the item loaded,
-- so lists never wait on the game for an item seen before. The cloud file ships name, vendor price and quality.
local function Remember(id)
	local Name, _, Quality, _, _, _, _, Stack, _, _, Sell = C_Item.GetItemInfo(id)
	if not Name then return nil end
	local Cache = NameCache()
	local C = Cache[id]
	if not C or C[1] ~= Name or C[2] ~= Quality or C[3] ~= Sell or C[4] ~= Stack then Cache[id] = { Name, Quality, Sell, Stack } end
	return Name, Quality
end
-- Shorter item names for list rows (the tooltip shows the full name; sorting uses it): recipe items lose their type
-- prefix (the icon shows the type) and "Enchant " becomes "Ench ". Only a prefix at the very start is dropped, and
-- only the recipe kinds found in Forever's item names (not "Libram", "Codex" etc.: those are real items).
L.RECIPE_PREFIXES = { "Pattern: ", "Plans: ", "Recipe: ", "Formula: ", "Schematic: ", "Blueprint: ", "Manual: " }
function L.ShortName(Name)
	if type(Name) ~= "string" then return Name end
	for _, P in ipairs(L.RECIPE_PREFIXES) do
		if Name:sub(1, #P) == P then Name = Name:sub(#P + 1) break end
	end
	return (Name:gsub("%f[%a]Enchant ", "Ench "))
end
local function Shipped(id)
	local D = AuctionForeverData
	return type(D) == "table" and type(D.info) == "table" and D.info[id] or nil
end
-- The data file's vendor price. The game data API doesn't know about 3,000 listed items: newer data files write nil
-- for them, older ones 0, so a 0 counts only for items the file names. nil = not known (not "sells for nothing").
local function ShippedVendor(id)
	local I = Shipped(id)
	if not I or not I[1] then return nil end
	if I[1] > 0 then return I[1] end
	local D = AuctionForeverData
	local Named = type(D) == "table" and type(D.names) == "table" and D.names[id]
	if Named and Named ~= "" then return 0 end
	return nil
end
local function ItemName(id)
	local Name, Quality = Remember(id)
	local Cache = NameCache()
	if Name then return Name, Quality end
	if not Pending[id] then
		Pending[id] = true
		if C_Item.RequestLoadItemDataByID then C_Item.RequestLoadItemDataByID(id) end
	end
	local C = Cache[id]
	if C then return C[1], C[2] end
	local D = AuctionForeverData
	local ShippedName = type(D) == "table" and type(D.names) == "table" and D.names[id]
	if ShippedName then local I = Shipped(id); return ShippedName, I and I[2] or 1 end
	return "|cff808080loading...|r", 1
end
-- Remember a name the client just loaded (preloads included, not only rows drawn on screen).
local function LearnName(id)
	if id then Remember(id) end
end
-- Ask the server for names the lists will need, a few at a time, so they're ready when the window opens.
function L.Preload(Ids)
	local i = 0
	local function Batch()
		local Done = 0
		while i < #Ids and Done < 20 do
			i = i + 1
			local id = Ids[i]
			if C_Item.GetItemInfo(id) then LearnName(id)
			elseif not Pending[id] then
				Pending[id] = true
				if C_Item.RequestLoadItemDataByID then C_Item.RequestLoadItemDataByID(id) end
				Done = Done + 1
			end
		end
		if i < #Ids then C_Timer.After(0.2, Batch) end
	end
	Batch()
end
local function Icon(id)
	local _, _, _, _, Tex = C_Item.GetItemInfoInstant(id)
	return Tex or 134400
end
-- Does the item stack? The stack size is only known once the game has loaded the item, so until then decide from
-- its type, which the game always knows: weapons and armor don't stack, trade goods, consumables etc. do.
local function Stacks(id)
	local Max = C_Item.GetItemMaxStackSizeByID and C_Item.GetItemMaxStackSizeByID(id)
	if Max then return Max > 1 end
	local _, _, _, _, _, ClassID = C_Item.GetItemInfoInstant(id)
	if not ClassID then return false end
	return ClassID ~= 2 and ClassID ~= 4 -- 2 = weapon, 4 = armor
end
-- "commodity" or "item" from the cloud data (exact: it comes from the auction data), nil if not known yet.
local function Kind(id)
	local I = Shipped(id)
	if I and I[3] ~= nil then return I[3] == 1 and "commodity" or "item" end
	return nil
end
-- Can it be flipped? Commodities only (gear is one-off listings with random stats); items the cloud data doesn't
-- know yet are judged by type.
local function Flippable(id)
	local K = Kind(id)
	if K then return K == "commodity" end
	return Stacks(id)
end
-- Vendor price: the game's, the names cache's, then the data file's; nil when none knows it (the item isn't loaded
-- yet and the data file doesn't name it). Vendor() is that or 0, for amounts and estimates only; decisions that
-- compare with the vendor price use VendorKnown and wait when it's nil.
local function VendorKnown(id)
	local _, _, _, _, _, _, _, _, _, _, Sell = C_Item.GetItemInfo(id)
	if Sell then return Sell end
	local C = NameCache()[id]
	if C and C[3] then return C[3] end
	return ShippedVendor(id)
end
local function Vendor(id) return VendorKnown(id) or 0 end
L.VendorKnown = function(id) return VendorKnown(id) end
-- A suffix version's name ending ("of the Whale"), from its market key; nil for a plain item.
function L.SuffixName(Key)
	local _, Bon = Core.SplitKey(Key)
	if not Bon then return nil end
	local Parts = {}
	for B in Bon:gmatch("[^:]+") do
		local N = AF_Suffix and AF_Suffix[tonumber(B)]
		if N then Parts[#Parts + 1] = N end
	end
	return #Parts > 0 and table.concat(Parts, " ") or "(other version)"
end
-- An item's name for a market key: a suffix version gets its suffix ("Wolf Rider's Belt of the Whale").
function L.KeyName(Key)
	local id = Core.SplitKey(Key)
	local Name, Quality = ItemName(id)
	local Suf = L.SuffixName(Key)
	if Suf and type(Name) == "string" and not Name:find(Suf, 1, true) then Name = Name .. " " .. Suf end
	return Name, Quality
end
L.ItemName, L.Icon, L.Vendor, L.Stacks = function(id) return ItemName(id) end, function(id) return Icon(id) end, function(id) return Vendor(id) end, function(id) return Stacks(id) end
L.Kind, L.Flippable = function(id) return Kind(id) end, function(id) return Flippable(id) end

-- Real deposits from the game for commodities (others: estimated below), so post durations weigh the
-- deposit lost when a post doesn't sell. Remembered per item/duration/quantity.
local DepositCache = {}
-- Gear and other single items (and anything while the auction house is closed): the deposit is an estimate, a
-- share of the vendor price per hour posted (seen in game: 24 h = 3x the vendor price). Forever's minimum deposit
-- is 1 copper a post (not 1 silver), so cheap items cost next to nothing to post.
Core.DepositPerHour = 3 / 24
Core.MinDeposit = 1
local function EstimatedDeposit(I, H, Qty)
	return math.max(Core.MinDeposit, math.floor(Vendor(I.id) * Core.DepositPerHour * H) * (Qty or 1))
end
Core.Deposit = function(I, H, Qty)
	if not (I and I.id) then return 0 end
	local AH = rawget(_G, "C_AuctionHouse") -- not there until the auction house UI exists
	if not (AH and AH.CalculateCommodityDeposit) or Kind(I.id) ~= "commodity" then return EstimatedDeposit(I, H, Qty) end
	local Idx
	for i, D in ipairs(Core.Durations) do if D == H then Idx = i end end
	if not Idx then return 0 end
	-- The deposit is per unit, so ask the game once per item and duration (for 100, to keep the copper rounding
	-- small) and scale. Asking for every stack size the planner tries made opening AF Buy lag.
	local K = I.id .. ":" .. Idx
	if DepositCache[K] == nil then
		local Ok, D = pcall(AH.CalculateCommodityDeposit, I.id, Idx, 100)
		if not (Ok and type(D) == "number") then return 0 end
		DepositCache[K] = D / 100
	end
	return math.floor(DepositCache[K] * Qty + 0.5)
end
local STATUS_COLOR = { early = "|cffffd100", good = "|cff1eff00", ["warming up"] = "|cff9d9d9d", slow = "|cffff8040", flooded = "|cffff8040", falling = "|cffff8040", ["no data"] = "|cff9d9d9d" }
local function StatusText(S) return (STATUS_COLOR[S] or "|cffffffff") .. S .. "|r" end
L.StatusText = StatusText

-- Farm tab ---------------------------------------------------------------------------------------------------------
-- Four views from Farm.lua: Gather (herbs, ore, leather, gems, fish nobody crafts), Drop (everything else nobody
-- crafts: Uncommon+ items, and trade goods at any quality), Craft (every recipe in Recipes.lua) and All (all of them
-- in one list: a crafted item shows once, as its best craft row, or as a plain sell row when no craft pays).
-- Worked out when the view opens and reused until the data or a scan changes (thousands of items: never per redraw).
-- Ranked by expected gold a unit (or a craft): what it gets when it sells x its sell rate - the deposit lost when it
-- doesn't, so a high price that rarely sells doesn't come first.
local Farm = AF.Farm
L.FarmView = "all"      -- or "gather" / "drop" / "craft"
L.CraftAll = false      -- false: only your professions (when the game tells us which you have)
local RawCache, GatherCache, DropCache, CraftCache, AllCache
local function DataKey()
	local D = AuctionForeverData
	return string.format("%d:%d", AF.Scan and AF.Scan.Version or 0, type(D) == "table" and D.time or 0)
end
-- Vendor price without asking the game (thousands of unloaded items would flood the server): names cache, then the
-- data file's shipped info.
local function KnownVendor(id)
	local C = NameCache()[id]
	if C and C[3] then return C[3] end
	return ShippedVendor(id)
end
-- Item quality without asking the game: the names cache, then the shipped data; 1 (common) when not known.
local function QualityOf(id)
	local C = NameCache()[id]
	if C and C[2] then return C[2] end
	local I = Shipped(id)
	return I and I[2] or 1
end
L.QualityOf = QualityOf
-- Crafted items get a gray "(c)" after their name in the lists.
function L.CraftedMark(id) return (AF_Recipes and AF_Recipes[id]) and " |cff9d9d9d(c)|r" or "" end
-- Deposit estimate for the farm lists (the same share of the vendor price as EstimatedDeposit); nil = not known.
local function FarmDeposit(I, H, Qty)
	local V = I and I.id and KnownVendor(I.id)
	if not V then return nil end
	return math.max(Core.MinDeposit, math.floor(V * Core.DepositPerHour * H)) * (Qty or 1)
end
-- Core.Info once per item per computation (a reagent is used by many recipes).
local function FarmEnv()
	local Memo = {}
	return {
		info = function(id)
			local I = Memo[id]
			if I == nil then I = Core.Info(id) or false; Memo[id] = I end
			return I or nil
		end,
		status = Core.Status,
		-- AF Sell's own suggestion for one unit (price, duration); the market price when it has none.
		postPrice = function(I, S)
			local P, H = Core.SellPrice(I, 1, 1)
			if P then return P, H end
			return Farm.PostPrice(I, S)
		end,
		deposit = FarmDeposit,
		vendorSell = KnownVendor,
		-- like AF Buy's craft plans: a sale is valued at most at what buyers paid (a lone high listing doesn't count),
		-- and a crafted product needs a couple of hours with sales
		priceCap = Core.ResaleCap,
		minSalesHours = L.CraftMinSalesHours,
	}
end
L.FarmEnv = FarmEnv
-- Gear (weapons, armor) isn't something you farm to sell by the stack: left out of Gather.
local function IsGear(id)
	local _, _, _, _, _, ClassID = C_Item.GetItemInfoInstant(id)
	if ClassID then return ClassID == 2 or ClassID == 4 end
	return Kind(id) == "item"
end
L.IsGear = IsGear
-- Sort rows by Get(row), highest first (Asc: lowest first). Rows without a value go last either way.
local function SortBy(Rows, Get, Asc)
	local K = {}
	for _, R in ipairs(Rows) do K[R] = Get(R) end
	table.sort(Rows, function(a, b)
		local x, y = K[a], K[b]
		if x ~= y then
			if x == nil then return false end
			if y == nil then return true end
			if Asc then return x < y end
			return x > y
		end
		if a.id ~= b.id then return a.id < b.id end
		return (a.spell or 0) < (b.spell or 0)
	end)
end
L.SortBy = SortBy
-- Tiers by percentile rank of the score (expected earnings: price x sell rate) within the list: S = top 10%,
-- A = next 20% (70-90th percentile), B = 40-70th, C = 20-40th, D = bottom 20%. A score of 0 or less (or none) is
-- always D. Equal scores share a tier. Marked once per list build.
L.TIERS = { { "S", 0.10, "|cffa335ee", "top 10%" }, { "A", 0.30, "|cff1eff00", "top 10-30%" }, { "B", 0.60, "|cffffd100", "top 30-60%" },
	{ "C", 0.80, "|cffff4040", "top 60-80%" }, { "D", math.huge, "|cff9d9d9d", "bottom 20%" } }
local TIER_INFO = {}
for _, T in ipairs(L.TIERS) do TIER_INFO[T[1]] = T end
local function MarkTiers(Rows, Get)
	local N = #Rows
	local V = {}
	for _, R in ipairs(Rows) do V[#V + 1] = { R, Get(R) } end
	table.sort(V, function(a, b)
		local x, y = a[2] or -math.huge, b[2] or -math.huge
		return x > y
	end)
	local Prev, PrevTier
	for i, P in ipairs(V) do
		local R, X = P[1], P[2]
		local Tier
		if not X or X <= 0 then Tier = "D"
		elseif X == Prev then Tier = PrevTier
		else
			local Above = (i - 1) / N -- share of the list ranked above this row
			for _, T in ipairs(L.TIERS) do if Above < T[2] then Tier = T[1] break end end
		end
		R.tier, R.score = Tier, X
		Prev, PrevTier = X, Tier
	end
end
L.MarkTiers = MarkTiers
function L.TierText(Tier)
	local T = TIER_INFO[Tier or "D"]
	return T[3] .. T[1] .. "|r"
end
-- A name to sort by without asking the game (saved names, then the data file's names, then the ID).
local function SortName(id)
	local C = NameCache()[id]
	if C and C[1] then return C[1] end
	local D = AuctionForeverData
	local N = type(D) == "table" and type(D.names) == "table" and D.names[id]
	return N or ("Item " .. id)
end
L.SortName = SortName
-- Every item with auction data (gear too), best expected first, each with its source (Gather / Drop / Crafted);
-- excluded ones (warming up, no sales...) are left out.
local function RawAll()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return {} end
	local Key = DataKey()
	if not (RawCache and RawCache.key == Key) then
		local Ids, Keys = {}, {}
		for _, K in ipairs(Core.AllKeys()) do if type(K) == "number" then Ids[#Ids + 1] = K else Keys[#Keys + 1] = K end end
		table.sort(Ids)
		table.sort(Keys)
		for _, K in ipairs(Keys) do Ids[#Ids + 1] = K end -- (suffix versions: each its own row)
		local Rows = Farm.RawFarms(Ids, FarmEnv())
		local NoGear = {}
		for _, R in ipairs(Rows) do
			R.gear = IsGear(R.id)
			if not R.gear then NoGear[#NoGear + 1] = R end
		end
		RawCache = { key = Key, rows = Rows, noGear = NoGear }
	end
	return RawCache.rows, RawCache.noGear
end
-- The quick scan list and the name preload use the top of this: every item but gear (crafted ones too).
function L.FarmRows() return select(2, RawAll()) or {} end
-- Uncommon or better, or a trade good (cloth, meat, elemental, enchanting mats...: farmed at any quality).
local function DropWorthy(R)
	if QualityOf(R.id) >= 2 then return true end
	local Class = Farm.ClassOf(R.id)
	return Class == 7
end
L.DropWorthy = DropWorthy
local function SourceRows(Cache, Source, Keep)
	local Raw = RawAll()
	if not (Cache and Cache.src == Raw) then
		local Rows = {}
		for _, R in ipairs(Raw) do if R.source == Source and (not Keep or Keep(R)) then Rows[#Rows + 1] = R end end
		MarkTiers(Rows, function(R) return R.expected end)
		Cache = { src = Raw, rows = Rows }
	end
	return Cache
end
-- Gather view: herbs, ore and stone, leather and hides, mining gems and fish that no recipe makes.
function L.GatherRows() GatherCache = SourceRows(GatherCache, "Gather") return GatherCache.rows end
-- Drop view: what's left (gear too), Uncommon+ or trade goods.
function L.DropRows() DropCache = SourceRows(DropCache, "Drop", DropWorthy) return DropCache.rows end

-- Forever's professions come with a second skill line each (SkillLine.ParentSkillLineID): either may be the known one.
local PROF_CHILD = { [171] = 2937, [164] = 2938, [185] = 2939, [333] = 2940, [202] = 2941, [129] = 2942, [165] = 2945,
	[186] = 2946, [197] = 2948, [40] = 2988 }
-- Your professions and ranks: { [skillLine] = rank }, or nil when the game doesn't say (then all are shown).
function L.MyProfessions()
	local SI = rawget(_G, "C_SkillInfo") -- not every client has it
	local Get = SI and SI.GetSkillLineInfoByID
	if not Get then return nil end
	local Out, Any = {}, false
	for Line in pairs(AF_RecipeSkills or {}) do
		for _, id in ipairs({ Line, PROF_CHILD[Line] }) do
			local Ok, Info = pcall(Get, id)
			if Ok and type(Info) == "table" and (Info.rank or 0) > 0 then
				Out[Line] = math.max(Out[Line] or 0, Info.rank)
				Any = true
			end
		end
	end
	return Any and Out or nil
end
-- The Craft view's cache key: the data, and the professions it's filtered to. Returns key, Mine, Filtered.
local function CraftKey()
	local Mine = L.MyProfessions()
	local Filtered = (not L.CraftAll) and Mine ~= nil
	local PKey = "all"
	if Filtered then
		local T = {}
		for Line, Rank in pairs(Mine) do T[#T + 1] = Line .. "=" .. Rank end
		table.sort(T)
		PKey = table.concat(T, ",")
	end
	return DataKey() .. ":" .. PKey, Mine, Filtered
end
-- Craft view: recipes that pay one way or the other (buy mats profit, or value added over selling your mats).
function L.CraftRows()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" or not AF_Recipes then return {} end
	local Key, Mine, Filtered = CraftKey()
	L.ProfessionsKnown = Mine ~= nil
	if not (CraftCache and CraftCache.key == Key) then
		local _, _, All = Farm.Crafts(FarmEnv(), Filtered and function(R) return Mine[R.skill] ~= nil end or nil)
		local Rows = {}
		for _, R in ipairs(All) do
			R.myRank = Mine and Mine[R.skill]
			if not R.excluded and ((not R.buyExcluded and (R.expected or 0) > 0) or (R.added or 0) > 0) then Rows[#Rows + 1] = R end
		end
		SortBy(Rows, function(R) return not R.buyExcluded and R.expected or nil end)
		MarkTiers(Rows, function(R) return not R.buyExcluded and R.expected or nil end)
		CraftCache = { key = Key, rows = Rows }
	end
	L.CraftFiltered = Filtered
	return CraftCache.rows
end
-- Craft plans for AF Buy -----------------------------------------------------------------------------------------
-- Do you know a recipe? In this order:
--   "spell":  the game says you know the recipe's spell (IsPlayerSpell / C_SpellBook.IsSpellKnown);
--   "window": what your profession window showed the last time you opened it (saved per character);
--   "rank":   neither knows: your profession rank is at least the recipe's required rank (trainer recipes need 0).
-- Returns known, how, your rank in that profession (nil when you don't have it or the game doesn't say).
function L.RecipeKnown(Spell, Line, Req, Mine)
	local Rank = Mine and Mine[Line]
	local IPS, SB = rawget(_G, "IsPlayerSpell"), rawget(_G, "C_SpellBook")
	local Ok, Yes = false, false
	if IPS then Ok, Yes = pcall(IPS, Spell) end
	if not (Ok and Yes) and SB and SB.IsSpellKnown then Ok, Yes = pcall(SB.IsSpellKnown, Spell) end
	if Ok and Yes then return true, "spell", Rank end
	local C = Char()
	local Seen = C.recipes and C.recipes[Spell]
	if Seen ~= nil then return Seen, "window", Rank end
	if Rank and Rank >= (Req or 0) then return true, "rank", Rank end
	return false, Mine and "rank" or nil, Rank
end
-- A profession window is open: remember which of AF's recipes you have learned (C_TradeSkillUI.GetRecipeInfo only
-- answers for the open profession).
function L.LearnRecipes()
	local TS = rawget(_G, "C_TradeSkillUI")
	if not (TS and TS.GetRecipeInfo and AF_Recipes) then return end
	local C = Char()
	C.recipes = C.recipes or {}
	local N = 0
	for _, List in pairs(AF_Recipes) do
		for _, Rc in ipairs(List) do
			local Ok, Info = pcall(TS.GetRecipeInfo, Rc[1])
			if Ok and type(Info) == "table" and Info.learned ~= nil then
				if C.recipes[Rc[1]] ~= (Info.learned and true or false) then N = N + 1 end
				C.recipes[Rc[1]] = Info.learned and true or false
			end
		end
	end
	if N > 0 then L.RecipeVersion = (L.RecipeVersion or 0) + 1 end
end
-- AF Buy's "Show all recipes" box (off: only recipes you know).
function L.ShowAllRecipes() return Account().allRecipes == true end
L.CraftMinSalesHours = 2 -- a product sold in fewer separate hours than this isn't sold on the AH by a craft plan
function L.SetShowAllRecipes(On) Account().allRecipes = On and true or nil end
-- Craft plans: buy the mats on the AH, craft, sell the products (AH or vendor). One row per product (its best
-- recipe), shaped like a flip target row: { id, craft = recipe row, info, flip = plan (Farm.CraftPlan), known,
-- knownHow, rank }. Only recipes you know (L.RecipeKnown) unless Show all recipes is on; only commodity mats (AF buys
-- them like commodity flips). N crafts fit one item's share of the flip budget, like a flip.
local CraftPlanCache
-- Seconds until a recipe spell is off cooldown (0 = ready or not known): C_Spell.GetSpellCooldown, else the old
-- GetSpellCooldown; the global cooldown (1.5 s or less) doesn't count. Any error or hidden value: 0.
function L.SpellCooldownLeft(Spell)
	local Ok, Left = pcall(function()
		local St, D
		local CS = rawget(_G, "C_Spell")
		if CS and CS.GetSpellCooldown then
			local Info = CS.GetSpellCooldown(Spell)
			if type(Info) == "table" then St, D = Info.startTime, Info.duration end
		else
			local G = rawget(_G, "GetSpellCooldown")
			if G then St, D = G(Spell) end
		end
		if type(St) == "number" and type(D) == "number" and D > 1.5 and St > 0 then return math.max(0, St + D - GetTime()) end
		return 0
	end)
	return Ok and Left or 0
end
-- The last bag you carry: the backpack is 0, the four bags 1-4, then the reagent (crafting) bag, 5 on Forever
-- (NUM_TOTAL_EQUIPPED_BAG_SLOTS = NUM_BAG_SLOTS + NUM_REAGENTBAG_SLOTS; Enum.BagIndex.ReagentBag). C_Container
-- reads it like any other bag.
function L.LastBag()
	local N = rawget(_G, "NUM_TOTAL_EQUIPPED_BAG_SLOTS")
	if type(N) == "number" and N >= 4 then return N end
	local E = rawget(_G, "Enum")
	local R = type(E) == "table" and type(E.BagIndex) == "table" and E.BagIndex.ReagentBag
	return type(R) == "number" and R or 4
end
-- Units of each item in your bags (backpack, four bags and the reagent bag), plus a signature that changes when
-- they do.
function L.BagCounts()
	local Out, Sig = {}, 0
	local C = rawget(_G, "C_Container")
	if not (C and C.GetContainerNumSlots and C.GetContainerItemInfo) then return Out, Sig end
	for Bag = 0, L.LastBag() do
		for Slot = 1, C.GetContainerNumSlots(Bag) or 0 do
			local Info = C.GetContainerItemInfo(Bag, Slot)
			if Info and Info.itemID then
				local N = Info.stackCount or 1
				Out[Info.itemID] = (Out[Info.itemID] or 0) + N
				Sig = (Sig + Info.itemID * 7919 + N * (Bag * 37 + Slot)) % 2147483647
			end
		end
	end
	return Out, Sig
end
-- Units of an item in your bank (the client knows them away from the bank too): all you have minus what you carry.
function L.BankCount(id)
	local C = rawget(_G, "C_Item")
	local Count = C and C.GetItemCount
	if not Count then return 0 end
	local Ok, All, Carried = pcall(function() return Count(id, true), Count(id) end)
	if not Ok or type(All) ~= "number" or type(Carried) ~= "number" then return 0 end
	return math.max(0, All - Carried)
end
-- Shopping list sources: an icon and the word. AH: a pile of coins, Vendor: a bag (both from Interface\Icons; the
-- minimap tracking / gossip icons aren't referenced by the client's UI code, so they weren't used); Owned (in your
-- bags) and Bank: a green check mark (the checkbox check, tinted green); Farm (not sold anywhere): orange word.
L.SOURCE_ORDER = { "AH", "Vendor", "Owned", "Bank", "Farm" }
L.SOURCE_ICON = {
	AH = "|TInterface\\Icons\\INV_Misc_Coin_02:14:14:0:0:64:64:5:59:5:59|t ",
	Vendor = "|TInterface\\Icons\\Inv_misc_bag_08:14:14:0:0:64:64:5:59:5:59|t ",
	Owned = "|TInterface\\Buttons\\UI-CheckBox-Check:14:14:0:0:32:32:0:32:0:32:30:255:0|t |cff1eff00",
	Bank = "|TInterface\\Buttons\\UI-CheckBox-Check:14:14:0:0:32:32:0:32:0:32:30:255:0|t |cff1eff00",
	Farm = "|cffff8000",
}
function L.SourceText(Src)
	local Pre = L.SOURCE_ICON[Src] or ""
	return Pre .. Src .. (Pre:find("|c", 1, true) and "|r" or "")
end
-- A shopping list in source order (AH, Vendor, Owned, Bank, Farm), keeping the given order within a source.
function L.BySource(List)
	local Out = {}
	for _, Src in ipairs(L.SOURCE_ORDER) do
		for _, E in ipairs(List or {}) do if E.source == Src then Out[#Out + 1] = E end end
	end
	local Known = {}
	for _, Src in ipairs(L.SOURCE_ORDER) do Known[Src] = true end
	for _, E in ipairs(List or {}) do if not Known[E.source] then Out[#Out + 1] = E end end -- (anything else last)
	return Out
end
-- One shopping list line: "<count> x <name>  <source>  <price>  (<total>)". AH: "up to <the most to pay each>"
-- with the total at listed prices; Vendor: the vendor price each; Owned / Bank: "-".
function L.ShoppingLine(E)
	local Price, Total
	if E.source == "AH" then
		Price, Total = "up to " .. Core.MoneyColor(E.upTo or 0), "(" .. Core.MoneyColor(E.cost or 0) .. ")"
	elseif E.source == "Vendor" then
		Price, Total = Core.MoneyColor(E.each or 0), "(" .. Core.MoneyColor(E.cost or 0) .. ")"
	else
		Price, Total = "-", ""
	end
	return (string.format("%d x %s  %s  %s  %s", E.qty, (ItemName(E.id)), L.SourceText(E.source), Price, Total):gsub("%s+$", ""))
end
-- The compact one-line version: "Mats: 40 Silk Cloth (AH, up to 2s 81c), 20 Coarse Thread (Vendor)", at most Max
-- entries, then "+N more".
function L.MatsLine(List, Max)
	Max = Max or 3
	local Parts = {}
	List = L.BySource(List)
	for i, E in ipairs(List) do
		if i > Max then Parts[#Parts + 1] = "+" .. (#List - Max) .. " more" break end
		local Src = E.source == "AH" and ("AH, up to " .. Core.MoneyColor(E.upTo or 0)) or E.source
		Parts[#Parts + 1] = string.format("%d %s (%s)", E.qty, (ItemName(E.id)), Src)
	end
	return "Mats: " .. (#Parts > 0 and table.concat(Parts, ", ") or "-")
end
-- KnownOnly: only recipes you know, whatever Show all recipes says (the login brief).
function L.CraftTargets(KnownOnly)
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" or not AF_Recipes then return {} end
	local Budget = L.FlipBudget()
	local All = not KnownOnly and L.ShowAllRecipes()
	local Held, BagSig = L.BagCounts()
	-- (the minute is in the key: cooldowns run out; the bags: what you hold isn't bought)
	local Key = string.format("%s:%d:%s:%d:%d:%d", DataKey(), Budget, tostring(All), L.RecipeVersion or 0, math.floor(GetTime() / 60), BagSig)
	if CraftPlanCache and CraftPlanCache.key == Key then return CraftPlanCache.rows end
	local Mine = L.MyProfessions()
	local MinProfit = Core.MinFlipProfitFor(Budget)
	local Env = FarmEnv()
	local Opts = { cap = Budget * Core.ItemShare(Budget), share = Core.PlanRateShare, hours = Core.FlipMaxHours,
		resaleCap = Core.ResaleCap, minSalesHours = L.CraftMinSalesHours,
		-- sold on the AH only when it's a steady seller, like a flip (not flooded, warming up...)
		ahStatus = { good = true, slow = true },
		cooldownLeft = function(Row) return L.SpellCooldownLeft(Row.spell) end,
		-- the return one craft needs, for each mat's target price: like a flip's (the vendor route: any profit)
		ret = function(Route, Row) return Route == "Vendor" and 0 or Core.FlipReturn(Row.status) end,
		held = function(id) return Held[id] or 0 end,
		bank = function(id) return L.BankCount(id) end,
		-- the same bar as a flip: the vendor route is a sure sale (like a vendor buy), the AH route needs the return
		need = function(Cost, Row)
			if Row.route == "Vendor" then return Core.MinVendorProfit end
			return Core.FlipNeed(Cost, MinProfit, Row.status)
		end }
	local Best = {}
	local _, _, Rows = Farm.Crafts(Env)
	for _, R in ipairs(Rows) do
		if Farm.Yield then Farm.Yield() end
		-- (with Show all, also recipes that lose money at today's listings: shown "over target" with each mat's target)
		if not R.excluded and ((not R.buyExcluded and (R.expected or 0) > 0) or (All and R.buyExcluded == Farm.LOSS)) then
			local Known, How, Rank = L.RecipeKnown(R.spell, R.skill, R.req, Mine)
			if Known or All then
				local Ok = true
				for _, Rg in ipairs(R.reagents) do if Rg.source ~= "vendor" and not Flippable(Rg.id) then Ok = false end end
				local P, Why, Left
				if Ok then P, Why, Left = Farm.CraftPlan(R, Opts, Env) end
				-- On cooldown past the planning window: only with Show all, as the plan it will be (Buy greyed).
				if not P and Why == "cooldown" and All then
					P = Farm.CraftPlan(R, setmetatable({ cooldownLeft = function() return 0 end }, { __index = Opts }), Env)
					if P then P.onCooldown = Left end
				elseif not P and Why and All then
					-- Not sold on the AH because of its status (flooded...): with Show all, the plan it would be (no Buy).
					P = Farm.CraftPlan(R, setmetatable({ ahStatus = false }, { __index = Opts }), Env)
					if P then P.blocked = Why end
				elseif not P and All then
					-- No craft pays at today's listings: with Show all, one craft and each mat's target (no Buy).
					P = Farm.CraftPlan(R, setmetatable({ force = true }, { __index = Opts }), Env)
					if P then P.blocked = P.overTarget or "over target" end
				end
				if P then
					local B = Best[R.id]
					if not B or P.profit > B.flip.profit then
						Best[R.id] = { id = R.id, craft = R, info = Env.info(R.id), flip = P, best = P, now = { [P] = true },
							plan = false, known = Known, knownHow = How, rank = Rank }
					end
				end
			end
		end
	end
	local Out = {}
	for _, E in pairs(Best) do Out[#Out + 1] = E end
	table.sort(Out, function(a, b) if a.flip.profit ~= b.flip.profit then return a.flip.profit > b.flip.profit end return a.id < b.id end)
	CraftPlanCache = { key = Key, rows = Out }
	return Out
end

-- All view: Gather + Drop + one row per crafted item (its best craft row; a plain sell row, Kind "Crafted", when no
-- craft pays or its profession is filtered out: nothing you hold goes missing; common crafted gear left out), tiered
-- over the combined list. Each row is a view of the cached row with its own tier (the same row has another tier in
-- its own view).
local function AllScore(R) if R.spell then return not R.buyExcluded and R.expected or nil end return R.expected end
function L.AllRows()
	local G, Dr, C = L.GatherRows(), L.DropRows(), L.CraftRows()
	local Raw = RawAll()
	if not (AllCache and AllCache.g == G and AllCache.d == Dr and AllCache.c == C and AllCache.raw == Raw) then
		local Rows, BestCraft = {}, {}
		for _, R in ipairs(G) do Rows[#Rows + 1] = setmetatable({}, { __index = R }) end
		for _, R in ipairs(Dr) do Rows[#Rows + 1] = setmetatable({}, { __index = R }) end
		for _, R in ipairs(C) do
			local B = BestCraft[R.id]
			if not B or (AllScore(R) or -math.huge) > (AllScore(B) or -math.huge) then BestCraft[R.id] = R end
		end
		for _, R in pairs(BestCraft) do Rows[#Rows + 1] = setmetatable({}, { __index = R }) end
		for _, R in ipairs(Raw) do
			if R.source == "Crafted" and not BestCraft[R.id] and not (R.gear and QualityOf(R.id) < 2) then
				Rows[#Rows + 1] = setmetatable({}, { __index = R })
			end
		end
		SortBy(Rows, AllScore)
		MarkTiers(Rows, AllScore)
		AllCache = { g = G, d = Dr, c = C, raw = Raw, rows = Rows }
	end
	return AllCache.rows
end
-- Are the Farm lists (L.AllRows) worked out for the current data, without working anything out?
function L.ListsReady()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return true end
	if not (RawCache and RawCache.key == DataKey() and AllCache and AllCache.raw == RawCache.rows) then return false end
	if not (GatherCache and GatherCache.src == RawCache.rows and DropCache and DropCache.src == RawCache.rows) then return false end
	if AF_Recipes and not (CraftCache and CraftCache.key == CraftKey() and AllCache.c == CraftCache.rows) then return false end
	return true
end
-- Working out the Farm lists (every item in the data, every recipe) takes about a second. Done on the spot, that
-- froze the game 5 s after every /reload (the name preload) and on the first tooltip after each scan (its Tier
-- line). Here it runs in the background, a few ms a frame: the same code (Farm.Yield pauses its loops), the same rows.
-- Background jobs run one at a time, in order, each in a coroutine that pauses at Farm.Yield (the loops over the
-- data: Farm.RawFarms, Farm.Crafts, the flip and craft plans, the brief's new items) once the frame's budget is used.
-- Farm.Yield is only set while a job runs: the same code called directly never pauses.
L.BG_BUDGET = 0.004
local Jobs = {} -- { co, done = { fn, ... }, key, quiet, fail }
local BGDeadline
local BGFrame = CreateFrame("Frame")
L.BackgroundFrame = BGFrame
local function BGYield()
	local J = Jobs[1]
	if J and coroutine.running() == J.co and GetTimePreciseSec() > BGDeadline then coroutine.yield() end
end
local function BGStep(self)
	local J = Jobs[1]
	if not J then self:SetScript("OnUpdate", nil) return end
	BGDeadline = GetTimePreciseSec() + L.BG_BUDGET
	Farm.Yield = BGYield
	local Res = { coroutine.resume(J.co) }
	Farm.Yield = nil
	if Res[1] and coroutine.status(J.co) ~= "dead" then return end
	table.remove(Jobs, 1)
	if not Jobs[1] then self:SetScript("OnUpdate", nil) end
	if not Res[1] then
		if not J.quiet then print("|cffffd100AuctionForever:|r background error: " .. tostring(Res[2])) end
		if J.fail then J.fail(Res[2]) end
		return
	end
	for _, Fn in ipairs(J.done) do Fn(unpack(Res, 2)) end
end
-- Queue Fn as a background job; OnDone(Fn's results) when it's finished. Key: joins a queued job with the same key.
-- Quiet: no chat message on an error; OnFail(error) instead.
function L.Background(Fn, OnDone, Key, Quiet, OnFail)
	if Key then
		for _, J in ipairs(Jobs) do
			if J.key == Key then if OnDone then J.done[#J.done + 1] = OnDone end return end
		end
	end
	Jobs[#Jobs + 1] = { co = coroutine.create(Fn), done = { OnDone }, key = Key, quiet = Quiet, fail = OnFail }
	BGFrame:SetScript("OnUpdate", BGStep)
end
-- Start (or join) the background build of the Farm lists; OnDone (optional) runs when they're ready.
function L.BuildListsLater(OnDone) L.Background(function() L.AllRows() end, OnDone, "lists") end
function L.BuildingLists()
	for _, J in ipairs(Jobs) do if J.key == "lists" then return true end end
	return false
end
function L.BackgroundBusy() return Jobs[1] ~= nil end
-- A background job that's asked for again while it runs (a scan's live updates, every 2 s; each finished scan):
-- one runs, and at most one more is kept to run after it, with the newest request. Fn's results go to OnDone.
-- Without this every request would queue its own seconds-long job (or join one that started on older data).
local Once = {}
function L.LaterOnce(Name, Fn, OnDone)
	local C = Once[Name]
	if not C then C = {}; Once[Name] = C end
	if C.running then C.again = { Fn, OnDone } return end
	C.running = true
	local function Next()
		C.running = false
		local A = C.again
		C.again = nil
		if A then L.LaterOnce(Name, A[1], A[2]) end
	end
	L.Background(Fn, function(...) if OnDone then OnDone(...) end; Next() end, nil, true, Next)
end
function L.FarmData()
	local V = L.FarmView
	if V == "craft" then return L.CraftRows() elseif V == "gather" then return L.GatherRows() elseif V == "drop" then return L.DropRows() end
	return L.AllRows()
end
function L.SetFarmView(View) L.FarmView = View; L.Load() end
function L.ToggleCraftAll() L.CraftAll = not L.CraftAll; L.Load() end

local function Money(C) return C and Core.MoneyColor(C) or "-" end
-- Sell rate (sold / (sold + expired)) as a colored percent: green 70%+, yellow 40%+, red 20%+, gray below; "?" when
-- not measured yet.
function L.RateText(Rate)
	if type(Rate) ~= "number" then return "|cff9d9d9d?|r" end
	local Pct = math.floor(Rate * 100 + 0.5)
	local Color = Pct >= 70 and "|cff1eff00" or Pct >= 40 and "|cffffd100" or Pct >= 20 and "|cffff4040" or "|cff9d9d9d"
	return Color .. Pct .. "%|r"
end
-- Tooltip lines for a Farm row (added under the item's own tooltip): short labels only.
function L.FarmTooltip(E, Tip)
	Tip = Tip or GameTooltip
	local function Line(Label, Value) Tip:AddLine(Label .. ": " .. Value, 1, 1, 1, true) end
	Tip:AddLine(" ")
	Tip:AddLine("AuctionForever", 1, 0.82, 0)
	if E.tier then local T = TIER_INFO[E.tier] Line("Tier", T[3] .. E.tier .. "|r") end
	local Craft = E.spell ~= nil
	Line("Expected", Craft and Core.MoneyDelta(E.expected) or Money(E.expected))
	Line("Sell rate", E.vendorRoute and "|cff1eff00vendor|r" or L.RateText(E.rate))
	Line("Sales/day", string.format("%.0f", E.salesDay or 0))
	Line("Source", Craft and ("Crafted (" .. ((AF_RecipeSkills and AF_RecipeSkills[E.skill]) or "?") .. ")") or (E.source or "?"))
	if E.spike then
		local I = Core.Info(E.key or E.id)
		Tip:AddLine("Price tripled in 24 h: valued at its usual lowest price" .. (I and Farm.SpikeCap(I) and (" (" .. Money(Farm.SpikeCap(I)) .. ")") or ""), 1, 0.5, 0.25, true)
	end
	if not Craft then return end
	local Held = L.BagCounts()
	local Lines = {}
	for _, Rg in ipairs(E.reagents or {}) do
		local Src = (Held[Rg.id] or 0) >= Rg.n and "Owned" or L.BankCount(Rg.id) >= Rg.n and "Bank"
			or Rg.source == "vendor" and "Vendor" or Rg.source == "ah" and "AH" or "Farm"
		Lines[#Lines + 1] = { source = Src, text = string.format("  %dx %s  %s  %s", Rg.n, (ItemName(Rg.id)), L.SourceText(Src),
			(Src == "Owned" or Src == "Bank") and "-" or Money(Rg.each)) }
	end
	for _, X in ipairs(L.BySource(Lines)) do Tip:AddLine(X.text, 0.8, 0.8, 0.8) end
	if E.buyExcluded then Line("Profit/craft", "-") else Line("Profit/craft", Core.MoneyDelta(E.profit) .. " (" .. (E.route or "AH") .. ")"
		.. (E.route == "AH" and E.worstProfit and ("   worst 10%: " .. Core.MoneyDelta(E.worstProfit)) or "")) end
	if not E.buyExcluded and E.route == "AH" and E.worstLoss then
		Tip:AddLine("Loses in the cheapest tenth of hours (the product at its 24 h 10th-percentile low): a lucky price, not a steady margin", 1, 0.5, 0.25, true)
	end
	if (E.vendorProfit or 0) > 0 then Line("Sell to vendor", Core.MoneyDelta(E.vendorProfit) .. " a craft") end
	if E.matCrafts and E.matCrafts < math.huge then Line("Mats on AH", E.matCrafts .. " crafts") end
end

-- Lists ----------------------------------------------------------------------------------------------------------
-- Flip budget for this auction house visit: your gold minus MinKeep, measured when you opened the AH or when
-- your gold went up since (sales, mail). Purchases count against it, so it doesn't halve again after every buy.
local BudgetBase
function L.ResetBudget() BudgetBase = GetMoney() end
function L.FlipBudget()
	local Now = GetMoney()
	if not BudgetBase or Now > BudgetBase then BudgetBase = Now end
	return math.max(0, Core.Budget(BudgetBase) - (BudgetBase - Now))
end

-- AF Buy's list: the best plan for your budget first (in buying order), then other flips that don't fit it.
-- Worked out when AF Buy opens (or after a purchase), and reused until your budget or your data changes.
local PlanCache
-- Everything AF Buy lists: the plan, other flips you can do now, then targets that need more gold.
function L.FlipTargets()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return {} end
	local Budget = L.FlipBudget()
	local Key = string.format("%d:%d:%d", Budget, AF.Scan and AF.Scan.Version or 0, D.time or 0)
	if PlanCache and PlanCache.key == Key then L.LastPlan = PlanCache.plan return PlanCache.rows end
	local Out = {}
	local Cap = Budget * Core.ItemShare(Budget)
	local MinProfit = Core.MinFlipProfitFor(Budget)
	local Cands, Info, Ids = {}, {}, {}
	for id in pairs(D.items) do
		if Flippable(id) then
			local I = Core.Info(id)
			Ids[#Ids + 1] = id
			Info[id] = I
			local O = Core.FlipOptions(I, Cap, MinProfit)
			if #O > 0 then Cands[#Cands + 1] = { id = id, options = O } end
		end
		if Farm.Yield then Farm.Yield() end -- (a background job: see L.Background)
	end
	-- Listings under the vendor price (any item, gear too): a sure profit, so they may use the whole budget.
	local CandOf = {}
	for _, Cd in ipairs(Cands) do CandOf[Cd.id] = Cd end
	local LowAt
	for i, Name in ipairs(D.fields or {}) do if Name == "low" then LowAt = i end end
	local Fresh = type(AuctionForeverDB) == "table" and AuctionForeverDB.fresh and AuctionForeverDB.fresh.items
	local VendorAll = {}
	-- Random-suffix gear: a vendor pays the same for every version, so here the versions' listings are one ladder
	-- (the purchase takes the cheapest auction of the item, whatever its suffix).
	local VIds = {}
	for id in pairs(D.items) do VIds[id] = true end
	for id in pairs(type(D.sfx) == "table" and D.sfx or {}) do VIds[id] = true end
	for id in pairs(VIds) do
		if Farm.Yield then Farm.Yield() end
		local Raw = D.items[id]
		local Low = LowAt and type(Raw) == "table" and Raw[LowAt] or nil
		local F = Fresh and Fresh[id]
		if F and F[1] and (not Low or F[1] < Low) then Low = F[1] end
		local Vers = type(D.sfx) == "table" and D.sfx[id]
		if Vers and not Info[id] then
			local Lad = {}
			for _, VI in ipairs(Raw and { Core.Info(id) } or {}) do for _, St in ipairs(VI.ladder or {}) do Lad[#Lad + 1] = St end end
			for B in pairs(Vers) do
				local VI = Core.Info(id .. ":" .. B)
				for _, St in ipairs(VI and VI.ladder or {}) do Lad[#Lad + 1] = St end
				local VF = Fresh and Fresh[id .. ":" .. B]
				local VL = (VF and VF[1]) or (VI and VI.low)
				if VL and (not Low or VL < Low) then Low = VL end
			end
			table.sort(Lad, function(a, b) return a[1] < b[1] end)
			Info[id] = setmetatable({ ladder = Lad }, { __index = Core.Info(id) or {} })
		end
		if Low then
			-- The data file's vendor price first: asking the game for thousands of unloaded items floods the server.
			local V = KnownVendor(id) -- (unknown: no vendor deal; never asks the game, see above)
			if V and V > 0 and Low < V then
				local I = Info[id] or Core.Info(id)
				Info[id] = I
				local Item = not Flippable(id) -- (not a commodity: one purchase per auction)
				local All = I and Core.VendorDeal(I.ladder, V, nil, Item)
				if All then
					VendorAll[#VendorAll + 1] = { id, All }
					local O = All.cost <= Budget and All or Core.VendorDeal(I.ladder, V, Budget, Item)
					if O then
						if not CandOf[id] then CandOf[id] = { id = id, options = {} }; Cands[#Cands + 1] = CandOf[id] end
						table.insert(CandOf[id].options, O)
					end
				end
			end
		end
	end
	-- Vendor to AH (Core.VendorFlip): goods vendors sell, bought at the vendor in a batch of 8 h of sales and auctioned.
	for id, V in pairs(AF_RecipeVendor or {}) do
		if Farm.Yield then Farm.Yield() end
		if D.items[id] then
			local I = Info[id] or Core.Info(id)
			Info[id] = I
			local O = I and Core.VendorFlip(I, V, Cap, C_Item.GetItemMaxStackSizeByID and C_Item.GetItemMaxStackSizeByID(id))
			if O then
				if not CandOf[id] then CandOf[id] = { id = id, options = {} }; Cands[#Cands + 1] = CandOf[id] end
				table.insert(CandOf[id].options, O)
			end
		end
	end
	local Plan = Core.Plan(Cands, Budget)
	-- Every row knows: the cheapest way in (start) and the gold that takes (need), and the most profitable way
	-- (best) and its gold (bestNeed). Options within your budget now are in .now.
	local Rows = {}
	local function Row(id)
		local R = Rows[id]
		if not R then R = { id = id, info = Info[id] or Core.Info(id), now = {} }; Rows[id] = R end
		return R
	end
	local function Consider(R, O)
		-- Vendor buys may use the whole budget: the gold needed is the cost plus what's always kept.
		local Need = O.vendor and (O.cost + Core.MinKeep) or Core.GoldFor(O.cost)
		if not R.start or Need < R.need then R.start, R.need = O, Need end
		-- Gold for the cheapest way in by the gold rule (need is lowered to your gold when you can buy it anyway).
		if not R.minGold or Need < R.minGold then R.minGold = Need end
		if not R.best or O.profit > R.best.profit then R.best, R.bestNeed = O, Need end
	end
	for _, Cd in ipairs(Cands) do
		local R = Row(Cd.id)
		for _, O in ipairs(Cd.options) do R.now[O] = true; Consider(R, O) end
		-- Reachable now: you have the gold, whatever the gold rule says for the cheapest option.
		R.need = math.min(R.need, GetMoney())
	end
	-- Near misses for the quick scan: worked out here, in the same pass over the flippable items (and cached with the
	-- plan), so finding them costs no second pass over every item and no item info from the game.
	local Near = {}
	for _, id in ipairs(Ids) do
		local All = Core.FlipOptions(Info[id], math.huge, MinProfit)
		if #All == 0 and not CandOf[id] then
			local Gap = Core.NearMiss(Info[id])
			if Gap then Near[#Near + 1] = { id = id, gap = Gap } end
		end
		if #All > 0 then
			local R = Row(id)
			for _, O in ipairs(All) do
				Consider(R, O)
				-- Fits one item's share of your budget: buyable now, even if only this any-gold search found it.
				if O.cost <= Cap then R.now[O] = true; R.need = math.min(R.need, GetMoney()) end
			end
		end
	end
	for _, VA in ipairs(VendorAll) do Consider(Row(VA[1]), VA[2]) end
	local InPlan = {}
	for _, P in ipairs(Plan) do
		InPlan[P.id] = true
		local R = Row(P.id)
		R.flip, R.plan = P.option, true
		Out[#Out + 1] = R
	end
	local Rest = {}
	for id, R in pairs(Rows) do
		if not InPlan[id] then
			R.plan = false
			local BestNow
			for O in pairs(R.now) do if not BestNow or O.profit > BestNow.profit then BestNow = O end end
			R.flip = BestNow or R.start
			Rest[#Rest + 1] = R
		end
	end
	-- After the plan: what you could buy now (most profit first), then what needs more gold (least gold first).
	table.sort(Rest, function(a, b)
		local An, Bn = a.now[a.flip] or false, b.now[b.flip] or false
		if An ~= Bn then return An end
		if An then return a.flip.profit > b.flip.profit end
		if a.need ~= b.need then return a.need < b.need end
		return a.flip.profit > b.flip.profit
	end)
	for _, E in ipairs(Rest) do Out[#Out + 1] = E end
	L.LastPlan = { cost = Plan.cost, profit = Plan.profit, count = #Plan, budget = Budget }
	table.sort(Near, function(a, b) if a.gap ~= b.gap then return a.gap < b.gap end return a.id < b.id end)
	PlanCache = { key = Key, rows = Out, plan = L.LastPlan, near = Near }
	return Out
end
-- Steady sellers that aren't flips but came within Core.NearMissReturn of the return they need, closest first:
-- { id, gap }. A quick scan looks them up so new flip targets show up between full scans.
function L.NearMisses()
	L.FlipTargets()
	return PlanCache and PlanCache.near or {}
end
-- Only the flips you can do with your gold now (the Flips list, price checks).
function L.FlipRows()
	local All = L.FlipTargets()
	if PlanCache and PlanCache.rows == All and PlanCache.now then return PlanCache.now end
	local Now = {}
	for _, E in ipairs(All) do if E.plan or (E.now and E.now[E.flip]) then Now[#Now + 1] = E end end
	if PlanCache and PlanCache.rows == All then PlanCache.now = Now end
	return Now
end

-- Missed flips (measuring how long flip chances last): after every finished full or quick scan, the flips AF Buy
-- would show you now are logged in AuctionForeverDB.flipLog as { id, price (buy up to), qty, profit, firstSeen,
-- lastSeen, goneAt, bought }. A logged flip still offered at the same or a lower price on a later scan gets a new
-- lastSeen; one that isn't offered any more gets goneAt (bought = you bought some of it since it was first seen).
-- Only runs when a scan you started finishes; never on a timer.
L.FlipLogMax = 300
function L.LogFlips(Now)
	local DB = Account()
	DB.flipLog = type(DB.flipLog) == "table" and DB.flipLog or {}
	local Log = DB.flipLog
	local Cur = {}
	for _, R in ipairs(L.FlipRows()) do
		local F = R.flip
		if F and not F.vendor and not F.fromVendor and F.buyUpTo then Cur[R.id] = F end
	end
	local Open = {}
	for _, E in ipairs(Log) do
		if not E[7] then
			local F = Cur[E[1]]
			if F and F.buyUpTo <= E[2] then
				E[6] = Now
				Open[E[1]] = true
			else
				E[7] = Now
				for _, B in ipairs(type(DB.buys) == "table" and DB.buys or {}) do
					if B[2] == E[1] and B[1] >= E[5] and B[1] <= Now then E[8] = true break end
				end
			end
		end
	end
	for id, F in pairs(Cur) do
		if not Open[id] then Log[#Log + 1] = { id, F.buyUpTo, F.buyQty or F.qty or 0, F.profit or 0, Now, Now } end
	end
	while #Log > L.FlipLogMax do table.remove(Log, 1) end
end

-- "/af missed": how long logged flips lasted before someone else took them.
function L.MissedSummary()
	local Log = type(AuctionForeverDB) == "table" and type(AuctionForeverDB.flipLog) == "table" and AuctionForeverDB.flipLog or {}
	local Gone, Lasted, ByItem, Bought = 0, {}, {}, 0
	for _, E in ipairs(Log) do
		if E[7] then
			if E[8] then Bought = Bought + 1
			else
				Gone = Gone + 1
				Lasted[#Lasted + 1] = (E[6] or E[5]) - E[5]
				local B = ByItem[E[1]] or { id = E[1], n = 0, profit = 0 }
				B.n, B.profit = B.n + 1, B.profit + (E[4] or 0)
				ByItem[E[1]] = B
			end
		end
	end
	local Lines = { string.format("Missed flips: %d logged, %d gone before you bought (%d you bought), %d still open.", #Log, Gone, Bought, #Log - Gone - Bought) }
	if #Lasted > 0 then
		table.sort(Lasted)
		local M = (#Lasted + 1) / 2
		local Med = (Lasted[math.floor(M)] + Lasted[math.ceil(M)]) / 2
		Lines[#Lines + 1] = string.format("Gone ones were still there for %d min (median) after first seen, until the scan before they vanished.", math.floor(Med / 60 + 0.5))
	end
	local Top = {}
	for _, B in pairs(ByItem) do Top[#Top + 1] = B end
	table.sort(Top, function(a, b) if a.profit ~= b.profit then return a.profit > b.profit end return a.id < b.id end)
	for i = 1, math.min(5, #Top) do
		local B = Top[i]
		Lines[#Lines + 1] = string.format("  %s: %d missed, %s expected profit", ItemName(B.id), B.n, Core.MoneyColor(B.profit))
	end
	return Lines
end

-- Why the Flip list is empty, in one line.
function L.FlipEmptyReason()
	local Budget = L.FlipBudget()
	if Budget <= 0 then return "No flip budget left: everything over " .. Core.MoneyColor(Core.MinKeep) .. " is used up for this visit." end
	local Head = string.format("Flip budget %s (your gold, keeping %s; up to %s per item).\n", Core.MoneyColor(Budget), Core.MoneyColor(Core.MinKeep), Core.MoneyColor(Budget * Core.ItemShare(Budget)))
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return "No auction data yet: scan at the auction house." end
	local N = {}
	for id in pairs(D.items) do
		local S = Core.FlipStatus(Core.Info(id))
		N[S] = (N[S] or 0) + 1
	end
	if (N.good or 0) == 0 then
		return Head .. string.format("No flips yet: no item has %d+ hours of steady sales data (%d warming up).\nThe cloud data and your scans add more every hour.", Core.FlipMinHours, N["warming up"] or 0)
	end
	return Head .. string.format("%d steady sellers, but none has a listing cheap enough to\nflip for %s+ expected profit (and a %d%%+ return, %d%%+ for slow sellers) within that budget right now.", N.good, Core.MoneyColor(Core.MinFlipProfitFor(Budget)), math.floor(Core.MinFlipReturn * 100 + 0.5), math.floor(Core.MinFlipReturnSlow * 100 + 0.5))
end

-- Items a quick scan looks up: flip candidates, sellable bag items, top farm reagents, fast sellers still warming up.
L.QuickCap, L.NearMissCount = 55, 10
function L.QuickList()
	local Out, Seen = {}, {}
	-- The other groups keep their old 45 between them; the near misses get the last 10 (cap 55).
	local function Add(id, Cap, Count, Total)
		if Count[1] >= Cap or Seen[id] or #Out >= (Total or L.QuickCap - L.NearMissCount) then return end
		Seen[id] = true; Out[#Out + 1] = id; Count[1] = Count[1] + 1
	end
	local C = { 0 }
	for _, R in ipairs(L.FlipRows()) do Add(R.id, 15, C) end
	C = { 0 }
	local NumSlots = C_Container and C_Container.GetContainerNumSlots
	if NumSlots then
		for Bag = 0, L.LastBag() do
			for Slot = 1, NumSlots(Bag) or 0 do
				local Info = C_Container.GetContainerItemInfo(Bag, Slot)
				if Info and Info.itemID and not Info.isBound and Core.Info(Info.itemID) then Add(Info.itemID, 15, C) end
			end
		end
	end
	C = { 0 }
	for _, R in ipairs(L.FarmRows()) do if R.status == "good" then Add(R.id, 10, C) end end
	C = { 0 }
	local D = AuctionForeverData
	if type(D) == "table" and type(D.items) == "table" then
		local Warm = {}
		for id in pairs(D.items) do
			local I = Core.Info(id)
			if Core.Status(I) == "warming up" and (I.qty or 0) > 0 and Stacks(id) then Warm[#Warm + 1] = { id, (I.qty or 0) * (Core.Market(I) or 0) } end
		end
		table.sort(Warm, function(x, y) return x[2] > y[2] end)
		for _, W in ipairs(Warm) do Add(W[1], 10, C) end
	end
	C = { 0 }
	for _, N in ipairs(L.NearMisses()) do Add(N.id, L.NearMissCount, C, L.QuickCap) end
	return Out
end

-- Farming sessions -----------------------------------------------------------------------------------------------
local Session = {}
AF.Session = Session

function Session.Current()
	local C = Char()
	return C.current
end
function Session.New()
	local C = Char()
	if C.current and (C.current.secs or 0) > 0 then table.insert(C.sessions, 1, C.current) end
	C.current = { start = time(), secs = 0, items = {}, money = 0, zone = GetRealZoneText and GetRealZoneText() or "" }
	return C.current
end
function Session.Start()
	local S = Session.Current() or Session.New()
	if not S.runningSince then S.runningSince = GetTime() end
	if (S.zone or "") == "" and GetRealZoneText then S.zone = GetRealZoneText() end
end
function Session.Stop()
	local S = Session.Current()
	if S and S.runningSince then
		S.secs = (S.secs or 0) + (GetTime() - S.runningSince)
		S.runningSince = nil
	end
end
function Session.Running()
	local S = Session.Current()
	return S and S.runningSince ~= nil
end
function Session.Seconds(S)
	if not S then return 0 end
	return (S.secs or 0) + (S.runningSince and (GetTime() - S.runningSince) or 0)
end
function Session.Clear()
	local C = Char()
	C.sessions, C.current = {}, nil
end
-- Gold a session's loot would bring now (items at what they'd sell for, after the cut) plus money looted.
function Session.Value(S)
	local V = S.money or 0
	for id, N in pairs(S.items or {}) do
		V = V + Core.LootValue(Core.Info(id), N, Vendor(id))
	end
	return V
end
function Session.AddItem(id, N)
	local S = Session.Current()
	if not (S and S.runningSince) then return end
	S.items[id] = (S.items[id] or 0) + N
end
function Session.AddMoney(C)
	local S = Session.Current()
	if not (S and S.runningSince) then return end
	S.money = (S.money or 0) + C
end
-- Called at logout: a running clock is stopped so time offline doesn't count.
function Session.Pause() Session.Stop() end

-- Loot and money messages ("You receive loot: %s." / "You receive loot: %sx%d." / "You loot 5 Silver").
local function Pattern(Fmt)
	local P = Fmt:gsub("([%(%)%.%%%+%-%*%?%[%]%^%$])", "%%%1")
	P = P:gsub("%%%%s", "(.+)"):gsub("%%%%d", "(%%d+)")
	return "^" .. P .. "$"
end
L.LootPatterns = {}
L.MoneyParts = {}
function L.BuildPatterns()
	L.LootPatterns = {}
	if LOOT_ITEM_SELF_MULTIPLE then L.LootPatterns[#L.LootPatterns + 1] = Pattern(LOOT_ITEM_SELF_MULTIPLE) end
	if LOOT_ITEM_SELF then L.LootPatterns[#L.LootPatterns + 1] = Pattern(LOOT_ITEM_SELF) end
	L.MoneyParts = {}
	for _, Pair in ipairs({ { GOLD_AMOUNT, 10000 }, { SILVER_AMOUNT, 100 }, { COPPER_AMOUNT, 1 } }) do
		if Pair[1] then L.MoneyParts[#L.MoneyParts + 1] = { (Pair[1]:gsub("%%d", "(%%d+)")), Pair[2] } end
	end
end
function L.ParseLoot(Msg)
	for _, P in ipairs(L.LootPatterns) do
		local Link, N = Msg:match(P)
		if Link then
			local id = tonumber(Link:match("item:(%d+)"))
			if id then return id, tonumber(N) or 1 end
		end
	end
end
function L.ParseMoney(Msg)
	local C = 0
	for _, Part in ipairs(L.MoneyParts) do
		local N = Msg:match(Part[1])
		if N then C = C + tonumber(N) * Part[2] end
	end
	return C
end

-- Window ---------------------------------------------------------------------------------------------------------
local Frame
local Rows = {}
local Data, Offset, Tab = {}, 0, 1
local Columns = {
	-- All: gather and craft rows together. Kind = Gather or the profession; Gold each = net each (gather) or profit a
	-- craft (buying the mats); Expected = expected each / expected a craft, the default sort.
	all = { { "Item", 180, "name" }, { "Tier", 28, "tier" }, { "Kind", 74, "kind" }, { "Gold each", 68, "gold" },
		{ "Sell rate", 50, "rate" }, { "Expected", 74, "expected" }, { "Sales/day", 54, "salesDay" }, { "Your gold/hr", 66, "mine" } },
	-- Gather: Expected each (net each x sell rate - deposit lost) is the default sort; Sales/day = the whole market's.
	gather = { { "Item", 196, "name" }, { "Tier", 28, "tier" }, { "Net each", 66, "net" }, { "Sell rate", 50, "rate" },
		{ "Expected each", 74, "expected" }, { "Sales/day", 54, "salesDay" }, { "Your gold/hr", 66, "mine" }, { "Status", 56, "status" } },
	drop = { { "Item", 196, "name" }, { "Tier", 28, "tier" }, { "Net each", 66, "net" }, { "Sell rate", 50, "rate" },
		{ "Expected each", 74, "expected" }, { "Sales/day", 54, "salesDay" }, { "Your gold/hr", 66, "mine" }, { "Status", 56, "status" } },
	-- Craft: Expected/craft (products x sell rate - deposit lost - mats bought) is the default sort.
	craft = { { "Item", 180, "name" }, { "Tier", 28, "tier" }, { "Profession", 66, "skill" }, { "Profit/craft", 68, "profit" },
		{ "Sell rate", 50, "rate" }, { "Expected/craft", 78, "expected" }, { "Sales/day", 54, "salesDay" }, { "Added each", 68, "added" } },
	[2] = { { "Item", 190 }, { "Profit", 80 }, { "Buy", 110 }, { "Resell", 80 }, { "Sells/hr", 60 }, { "Time", 40 }, { "Status", 50 } },
}

local function MyGoldPerHour(id)
	local Secs, Items = 0, 0
	for _, S in ipairs(Char().sessions) do
		if S.items and S.items[id] then Secs, Items = Secs + (S.secs or 0), Items + S.items[id] end
	end
	local Cur = Session.Current()
	if Cur and Cur.items and Cur.items[id] then Secs, Items = Secs + Session.Seconds(Cur), Items + Cur.items[id] end
	if Secs < 60 then return nil end
	return Core.LootValue(Core.Info(id), Items, Vendor(id)) / (Secs / 3600)
end

-- Column sort per list for this session (default: expected, highest first). Click a header: highest first; again:
-- lowest first.
local FarmSort = { all = { key = "expected" }, gather = { key = "expected" }, drop = { key = "expected" }, craft = { key = "expected" } }
local SORT_GET = {
	name = function(R) return SortName(R.id) end,
	net = function(R) return R.net end,
	rate = function(R) if R.vendorRoute then return 1 end return R.chance end, -- not measured: sorts at the rate it's counted at
	expected = function(R) return not R.buyExcluded and R.expected or nil end,
	tier = function(R) return R.score end, -- the tier's score: expected earnings
	salesDay = function(R) return R.salesDay end,
	mine = function(R) if R.spell then return nil end return MyGoldPerHour(R.id) end,
	kind = function(R) if R.spell then return AF_RecipeSkills and AF_RecipeSkills[R.skill] or "?" end return R.source or "?" end,
	gold = function(R) if R.spell then return not R.buyExcluded and R.profit or nil end return R.net end,
	status = function(R) return R.status end,
	skill = function(R) return AF_RecipeSkills and AF_RecipeSkills[R.skill] or "" end,
	profit = function(R) return not R.buyExcluded and R.profit or nil end,
	added = function(R) return (R.added or 0) > 0 and R.added or nil end,
}
function L.FarmSortState(View) local S = FarmSort[View or L.FarmView] return S.key, S.asc == true end
-- The Farm list in the chosen column order: a sorted copy (the cached list keeps gold-a-day order for the quick scan).
local SortedCache
local function SortedFarm(Rows)
	local S = FarmSort[L.FarmView]
	if SortedCache and SortedCache.src == Rows and SortedCache.key == S.key and SortedCache.asc == S.asc then return SortedCache.rows end
	local Out = {}
	for i, R in ipairs(Rows) do Out[i] = R end
	SortBy(Out, SORT_GET[S.key] or SORT_GET.expected, S.asc)
	SortedCache = { src = Rows, key = S.key, asc = S.asc, rows = Out }
	return Out
end
-- A header click: sort by that column, highest first; the same column again flips the order. Back to the top.
function L.SortFarmColumn(i)
	if Tab ~= 1 then return end
	local C = Columns[L.FarmView][i]
	if not (C and C[3]) then return end
	local S = FarmSort[L.FarmView]
	if S.key == C[3] then S.asc = not S.asc else S.key, S.asc = C[3], false end
	L.Load()
end

local function SetCells(Row, Values)
	for i, Cell in ipairs(Row.Cells) do
		Cell:SetText(Values[i] or "")
	end
end

local function LayoutHeader()
	local Cols = Columns[Tab == 1 and L.FarmView or Tab]
	for i, H in ipairs(Frame.Headers) do
		local C = Cols and Cols[i]
		H:SetShown(C ~= nil)
		if C then
			local Mark = ""
			if Tab == 1 and C[3] and FarmSort[L.FarmView].key == C[3] then Mark = FarmSort[L.FarmView].asc and " ^" or " v" end
			H.Label:SetText(C[1] .. Mark)
			H:EnableMouse(Tab == 1 and C[3] ~= nil)
		end
	end
	local X = 34
	for i, H in ipairs(Frame.Headers) do
		local C = Cols and Cols[i]
		if C then
			H:ClearAllPoints(); H:SetPoint("TOPLEFT", Frame.Inset, "TOPLEFT", X, -6); H:SetSize(C[2], 16)
			for _, R in ipairs(Rows) do
				R.Cells[i]:ClearAllPoints(); R.Cells[i]:SetPoint("LEFT", R, "LEFT", X - 6, 0); R.Cells[i]:SetWidth(C[2])
			end
			X = X + C[2] + 6
		end
	end
end

function L.Refresh()
	if not (Frame and Frame:IsShown()) then return end
	local Age = Core.DataAge()
	local Watched = Core.HoursWatched() or 0
	local Basis = Watched <= 0 and "  |cffff8040waiting for the first hour of sales|r"
		or (Watched < Core.EarlyHours and string.format("  |cffffd100early: %.0f h of sales|r", Watched))
		or string.format("  %.0f h of sales", Watched)
	local Fresh = AuctionForeverDB and AuctionForeverDB.fresh
	local ScanText = ""
	if Fresh and Fresh.time then
		local M = math.floor((time() - Fresh.time) / 60)
		ScanText = "your scan " .. (M < 120 and (M .. " min") or (math.floor(M / 60) .. " h")) .. " ago   "
		if Watched <= 0 then Basis = "" end
	end
	Frame.Age:SetText(ScanText .. (Age and (string.format("cloud data %s old", Age < 1 and (math.floor(Age * 60) .. " min") or (string.format("%.1f h", Age))) .. Basis)
		or (ScanText ~= "" and "" or "no data yet: scan at the auction house, or start AuctionForever Sync and /reload")))
	if Age and Age > 3 then Frame.Age:SetTextColor(1, 0.5, 0.25) else Frame.Age:SetTextColor(0.8, 0.8, 0.8) end
	local Sessions = Tab == 3
	Frame.List:SetShown(not Sessions)
	Frame.SessionPane:SetShown(Sessions)
	if Sessions then L.RefreshSessions() return end
	LayoutHeader()
	if Frame.Bar then Offset = AF.Trade.SyncBar(Frame.Bar, Offset, #Data) end
	L.RefreshFarmBar()
	for i, R in ipairs(Rows) do
		local E = Data[i + Offset]
		R:SetShown(E ~= nil)
		if E then
			local Name, Quality = L.KeyName(E.key or E.id)
			local Color = ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[Quality or 1]
			R.Icon:SetTexture(Icon(E.id))
			R.id = E.id
			local I = E.info
			local NameText = (Color and Color.hex or "|cffffffff") .. L.ShortName(Name) .. "|r" .. L.CraftedMark(E.id)
			R.entry = E
			-- Craft rows sold to a vendor: a yellow "V" before the profession, "vendor" as the sell rate.
			local function Prof(E2)
				return (E2.vendorRoute and "|cffffd100V|r " or "") .. ((AF_RecipeSkills and AF_RecipeSkills[E2.skill]) or "?")
			end
			local RateCell = E.vendorRoute and "|cff1eff00vendor|r" or L.RateText(E.rate)
			if Tab == 1 and L.FarmView == "all" then
				local Craft = E.spell ~= nil
				local Buy = Craft and not E.buyExcluded and E.profit
				local Mine = not Craft and MyGoldPerHour(E.id)
				SetCells(R, { NameText, L.TierText(E.tier), Craft and Prof(E) or (E.source or "?"),
					Craft and (Buy and Core.MoneyDelta(E.profit) or "-") or Core.MoneyColor(E.net), RateCell,
					Craft and (Buy and Core.MoneyDelta(E.expected) or "-") or Core.MoneyColor(E.expected), string.format("%.0f", E.salesDay or 0),
					Mine and Core.MoneyColor(Mine) or "-" })
			elseif Tab == 1 and E.spell then
				local Buy = not E.buyExcluded and E.profit
				SetCells(R, { NameText, L.TierText(E.tier), Prof(E), Buy and Core.MoneyDelta(E.profit) or "-", RateCell,
					Buy and Core.MoneyDelta(E.expected) or "-", string.format("%.0f", E.salesDay or 0),
					(E.added or 0) > 0 and Core.MoneyDelta(E.added) or "-" })
			elseif Tab == 1 then
				local Mine = MyGoldPerHour(E.id)
				SetCells(R, { NameText, L.TierText(E.tier), Core.MoneyColor(E.net), L.RateText(E.rate), Core.MoneyColor(E.expected),
					string.format("%.0f", E.salesDay or 0), Mine and Core.MoneyColor(Mine) or "-", StatusText(E.status) })
			else
				local F = E.flip
				SetCells(R, { NameText, Core.MoneyDelta(F.profit), F.buyQty .. " at up to " .. Core.MoneyColor(F.buyUpTo),
					Core.MoneyColor(F.resell), string.format("%.0f", I.perHour or 0), F.hours .. " h", StatusText("good") })
			end
		end
	end
	Frame.Empty:SetShown(#Data == 0)
	if #Data == 0 then
		local Text = "Nothing to show yet."
		if Tab == 2 then Text = L.FlipEmptyReason()
		elseif Tab == 1 and (L.FarmView == "craft" or L.FarmView == "all") and L.CraftFiltered then
			Text = "No paying crafts for your professions in the data yet. Click \"My professions\" to see all." end
		Frame.Empty:SetText(Text)
	end
end

function L.RefreshSessions()
	local P = Frame.SessionPane
	local S = Session.Current()
	local Secs = Session.Seconds(S)
	P.Clock:SetText(string.format("%d:%02d:%02d", Secs / 3600, (Secs % 3600) / 60, Secs % 60))
	local Running = Session.Running()
	P.State:SetText(Running and "|cff1eff00Timer running|r" or "|cffff6040Timer stopped|r")
	P.Toggle:SetText(Running and "Stop timer" or "Start timer")
	local V = S and Session.Value(S) or 0
	P.Gold:SetText("This session: " .. Core.MoneyColor(V) .. (Secs >= 60 and ("   (" .. Core.MoneyColor(V / (Secs / 3600)) .. " per hour)") or ""))
	local Parts = {}
	if S then
		for id, N in pairs(S.items) do Parts[#Parts + 1] = (ItemName(id)) .. " x" .. N end
		table.sort(Parts)
		if (S.money or 0) > 0 then Parts[#Parts + 1] = "money " .. Core.MoneyColor(S.money) end
	end
	P.Loot:SetText(#Parts > 0 and ("Looted: " .. table.concat(Parts, ", ")) or "Looted: nothing yet")
	local Lines = {}
	for i, Old in ipairs(Char().sessions) do
		if i > 10 then break end
		local OSecs = Old.secs or 0
		local OV = Session.Value(Old)
		Lines[#Lines + 1] = string.format("%s   %s   %d min   %s   %s/hr", date("%b %d %H:%M", Old.start or 0), Old.zone or "?",
			math.floor(OSecs / 60), Core.MoneyColor(OV), OSecs >= 60 and Core.MoneyColor(OV / (OSecs / 3600)) or "-")
	end
	P.History:SetText(#Lines > 0 and table.concat(Lines, "\n") or "No finished sessions yet.")
end

function L.ShownRows() return Data end -- the rows the list shows, in order (tests)
function L.Load()
	if Tab == 1 then Data = SortedFarm(L.FarmData()) elseif Tab == 2 then Data = L.FlipRows() else Data = {} end
	Offset = 0
	L.Refresh()
end

function L.SelectTab(i)
	Tab = i
	PanelTemplates_SetTab(Frame, i)
	L.Load()
end

-- Farm controls: shown on the Farm tab only; the current view's button is greyed out.
function L.RefreshFarmBar()
	local FB = Frame and Frame.FarmBar
	if not FB then return end
	FB:SetShown(Tab == 1)
	if Tab ~= 1 then return end
	local View = L.FarmView
	local Craft = View == "craft" or View == "all" -- craft rows shown: the professions filter applies
	FB.All:SetEnabled(View ~= "all")
	FB.Gather:SetEnabled(View ~= "gather")
	FB.Drop:SetEnabled(View ~= "drop")
	FB.Craft:SetEnabled(View ~= "craft")
	FB.Prof:SetShown(Craft)
	FB.Prof:SetText(L.CraftAll and "All professions" or "My professions")
	local Note = "Expected = sale x sell rate - lost deposits. Click a column to sort."
	if Craft and not L.CraftAll and not L.ProfessionsKnown then Note = "Professions not known yet: showing all. " .. Note end
	FB.Note:SetText(Note)
end

local function SavePosition()
	local Point, _, RelPoint, X, Y = Frame:GetPoint(1)
	Char().pos = { Point, RelPoint, X, Y }
end

function L.CreateWindow()
	if Frame then return Frame end
	Frame = CreateFrame("Frame", "AuctionForeverFrame", UIParent, "ButtonFrameTemplate")
	ButtonFrameTemplate_HidePortrait(Frame)
	Frame:SetSize(720, 470)
	Frame:SetTitle("AuctionForever")
	Frame:SetFrameStrata("HIGH")
	Frame:SetToplevel(true)
	Frame:SetClampedToScreen(true)
	Frame:SetMovable(true)
	Frame:EnableMouse(true)
	Frame:RegisterForDrag("LeftButton")
	Frame:SetScript("OnDragStart", function(self) if IsShiftKeyDown() then self:StartMoving() end end)
	Frame:SetScript("OnDragStop", function(self) self:StopMovingOrSizing(); SavePosition() end)
	local Pos = Char().pos
	if Pos then Frame:SetPoint(Pos[1], UIParent, Pos[2], Pos[3], Pos[4]) else Frame:SetPoint("CENTER") end
	tinsert(UISpecialFrames, "AuctionForeverFrame") -- Escape closes it

	Frame.Age = Frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	Frame.Age:SetPoint("TOPRIGHT", -30, -6)

	for i, Name in ipairs(TABS) do
		local T = CreateFrame("Button", "AuctionForeverFrameTab" .. i, Frame, "PanelTabButtonTemplate")
		T:SetID(i)
		T:SetText(Name)
		if i == 1 then T:SetPoint("TOPLEFT", Frame, "BOTTOMLEFT", 12, 2) else T:SetPoint("LEFT", Frame.Tabs[i - 1], "RIGHT", 4, 0) end
		T:SetScript("OnClick", function(self) L.SelectTab(self:GetID()) end)
		PanelTemplates_TabResize(T, 0)
	end
	PanelTemplates_SetNumTabs(Frame, #TABS)

	-- List pane
	Frame.List = CreateFrame("Frame", nil, Frame.Inset)
	Frame.List:SetAllPoints()
	-- Column headers: buttons (click to sort the Farm lists), the text in .Label.
	Frame.Headers = {}
	for i = 1, 8 do
		local H = CreateFrame("Button", nil, Frame.List)
		H:SetSize(80, 16)
		H.Label = H:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
		H.Label:SetPoint("LEFT", H, "LEFT", 0, 0)
		H.Label:SetJustifyH("LEFT")
		H:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
		H:SetScript("OnClick", function() L.SortFarmColumn(i) end)
		Frame.Headers[i] = H
	end
	for r = 1, ROWS do
		local R = CreateFrame("Button", nil, Frame.List)
		R:SetSize(664, ROW_H)
		R:SetPoint("TOPLEFT", Frame.Inset, "TOPLEFT", 6, -24 - (r - 1) * ROW_H)
		R:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
		R.Icon = R:CreateTexture(nil, "ARTWORK")
		R.Icon:SetSize(18, 18)
		R.Icon:SetPoint("LEFT", 2, 0)
		R.Cells = {}
		for c = 1, 8 do
			local FS = R:CreateFontString(nil, "OVERLAY", c == 1 and "GameFontHighlight" or "GameFontHighlightSmall")
			FS:SetJustifyH("LEFT")
			FS:SetWordWrap(false)
			R.Cells[c] = FS
		end
		R:SetScript("OnEnter", function(self)
			if not self.id then return end
			GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
			GameTooltip:SetItemByID(self.id)
			if Tab == 1 and self.entry then L.FarmTooltip(self.entry) end
			GameTooltip:Show()
		end)
		R:SetScript("OnLeave", function() GameTooltip:Hide() end)
		Rows[r] = R
	end
	Frame.Rows = Rows
	Frame.Empty = Frame.List:CreateFontString(nil, "OVERLAY", "GameFontDisable")
	Frame.Empty:SetPoint("CENTER", Frame.Inset, "CENTER")
	Frame.List:EnableMouseWheel(true)
	Frame.List:SetScript("OnMouseWheel", function(_, Delta)
		Offset = math.max(0, math.min(math.max(0, #Data - ROWS), Offset - Delta * 3))
		L.Refresh()
	end)
	-- Scroll bar and "1-14 of N", like AF Buy / AF Sell.
	if AF.Trade and AF.Trade.ScrollBar then
		Frame.Bar = AF.Trade.ScrollBar(Frame.List, 676, -24, function(V) Offset = V; L.Refresh() end)
	end
	-- Farm controls under the list: Gather / Craft, your professions or all, sort, and what "per day" means.
	local FB = CreateFrame("Frame", nil, Frame.List)
	FB:SetPoint("BOTTOMLEFT", Frame.Inset, "BOTTOMLEFT", 6, 4)
	FB:SetSize(690, 24)
	Frame.FarmBar = FB
	local function FarmBtn(Text, X, W, OnClick, Tip)
		local B = CreateFrame("Button", nil, FB, "UIPanelButtonTemplate")
		B:SetSize(W, 22); B:SetText(Text); B:SetPoint("LEFT", FB, "LEFT", X, 0); B:SetScript("OnClick", OnClick)
		B:SetScript("OnEnter", function(self)
			GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
			GameTooltip:AddLine(self:GetText())
			GameTooltip:AddLine(Tip, 1, 1, 1, true)
			GameTooltip:Show()
		end)
		B:SetScript("OnLeave", function() GameTooltip:Hide() end)
		return B
	end
	FB.All = FarmBtn("All", 0, 40, function() L.SetFarmView("all") end, "Everything in one list, ranked by expected earnings.")
	FB.Gather = FarmBtn("Gather", 44, 60, function() L.SetFarmView("gather") end, "Herbs, ore, leather, gems and fish.")
	FB.Drop = FarmBtn("Drop", 108, 50, function() L.SetFarmView("drop") end, "Mob drops: Uncommon+ items and trade goods.")
	FB.Craft = FarmBtn("Craft", 162, 52, function() L.SetFarmView("craft") end, "Recipes: profit buying the mats (AH or vendor sale).")
	FB.Prof = FarmBtn("My professions", 218, 110, function() L.ToggleCraftAll() end, "Your professions' recipes, or all.")
	FB.Note = FB:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	FB.Note:SetPoint("LEFT", FB, "LEFT", 334, 0)
	FB.Note:SetWidth(354)
	FB.Note:SetJustifyH("LEFT")

	-- Sessions pane
	local P = CreateFrame("Frame", nil, Frame.Inset)
	P:SetAllPoints()
	Frame.SessionPane = P
	P.Clock = P:CreateFontString(nil, "OVERLAY", "GameFontNormalHuge")
	P.Clock:SetPoint("TOPLEFT", 16, -16)
	P.State = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.State:SetPoint("TOPLEFT", P.Clock, "BOTTOMLEFT", 0, -4)
	P.Gold = P:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	P.Gold:SetPoint("TOPLEFT", P.State, "BOTTOMLEFT", 0, -10)
	local function Btn(Text, X, OnClick)
		local B = CreateFrame("Button", nil, P, "UIPanelButtonTemplate")
		B:SetSize(120, 26)
		B:SetText(Text)
		B:SetPoint("TOPLEFT", 16 + X, -110)
		B:SetScript("OnClick", OnClick)
		return B
	end
	P.Toggle = Btn("Start timer", 0, function() if Session.Running() then Session.Stop() else Session.Start() end L.RefreshSessions() end)
	Btn("New session", 130, function() Session.Stop(); Session.New(); L.RefreshSessions() end)
	Btn("Clear sessions", 260, function() StaticPopup_Show("AUCTIONFOREVER_CLEAR_SESSIONS") end)
	P.Loot = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.Loot:SetPoint("TOPLEFT", 16, -146)
	P.Loot:SetWidth(670)
	P.Loot:SetJustifyH("LEFT")
	local HistTitle = P:CreateFontString(nil, "OVERLAY", "GameFontNormal")
	HistTitle:SetPoint("TOPLEFT", 16, -200)
	HistTitle:SetText("Past sessions")
	P.History = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.History:SetPoint("TOPLEFT", HistTitle, "BOTTOMLEFT", 0, -6)
	P.History:SetJustifyH("LEFT")
	P.Ticker = 0
	P:SetScript("OnUpdate", function(self, Elapsed)
		self.Ticker = self.Ticker + Elapsed
		if self.Ticker >= 1 then self.Ticker = 0; L.RefreshSessions() end
	end)

	Frame:SetScript("OnShow", function() L.Load() end)
	Frame:Hide()
	PanelTemplates_SetTab(Frame, 1)
	return Frame
end

function L.Toggle(TabIndex)
	L.CreateWindow()
	if Frame:IsShown() and (not TabIndex or TabIndex == Tab) then Frame:Hide() return end
	Tab = TabIndex or Tab
	PanelTemplates_SetTab(Frame, Tab)
	if Frame:IsShown() then L.Load() else Frame:Show() end
end

-- AuctionForever tabs in the auction house (AF Buy, AF Sell, AuctionForever) ------------------------------------
-- Built without writing to Blizzard's tab list or display modes (that would taint the auction house and get
-- purchases blocked): our own tab buttons, owned by our own frame, and panels laid over the content area that hide
-- whenever one of the other tabs is clicked.
local AH = { Pages = {} }
local function SelectedBlizzTab()
	local i = AuctionHouseFrame.selectedTab
	return i and AuctionHouseFrame.Tabs and AuctionHouseFrame.Tabs[i]
end
local function Ours(C)
	if C == AH.Holder then return true end
	for _, Pg in ipairs(AH.Pages) do if C == Pg.Tab or C == Pg.Panel then return true end end
	return false
end
local function TabRow()
	-- Every visible tab-like button on the bottom row (Blizzard's and other add-ons'), ours excluded.
	local Row, Buy = {}, AuctionHouseFrame.BuyTab
	local Top = Buy and Buy:GetTop()
	if not Top then return Row end
	local function Walk(F, Depth)
		for _, C in ipairs({ F:GetChildren() }) do
			if not Ours(C) then
				if C:IsShown() and C:GetObjectType() == "Button" and C:GetTop()
					and math.abs(C:GetTop() - Top) < 4 and (C:GetLeft() or 0) >= (Buy:GetLeft() or 0) - 1 then
					Row[#Row + 1] = C
				elseif Depth < 2 then Walk(C, Depth + 1) end
			end
		end
	end
	Walk(AuctionHouseFrame, 0)
	return Row
end
local function PlaceTab()
	local Buy = AuctionHouseFrame.BuyTab
	if not (Buy and Buy:GetLeft() and AH.Pages[1]) then return end
	local Right = Buy:GetRight()
	for _, B in ipairs(TabRow()) do if (B:GetRight() or 0) > Right then Right = B:GetRight() end end
	for i, Pg in ipairs(AH.Pages) do
		Pg.Tab:ClearAllPoints()
		if i == 1 then
			Pg.Tab:SetPoint("LEFT", Buy, "LEFT", Right - Buy:GetLeft() + 3, 0) -- standard tabs sit 3 px apart
		else
			Pg.Tab:SetPoint("LEFT", AH.Pages[i - 1].Tab, "RIGHT", 3, 0)
		end
	end
end
function L.ShowAHPage(Index)
	for i, Pg in ipairs(AH.Pages) do
		if i == Index then Pg.Panel:Show(); PanelTemplates_SelectTab(Pg.Tab)
		else
			if Pg.Panel:IsShown() and Pg.OnHide then Pg.OnHide(Pg.Panel) end
			Pg.Panel:Hide(); PanelTemplates_DeselectTab(Pg.Tab)
		end
	end
	local Sel = SelectedBlizzTab()
	if Sel then PanelTemplates_DeselectTab(Sel) end
	local Pg = AH.Pages[Index]
	if Pg and Pg.OnShow then Pg.OnShow(Pg.Panel) end
end
function L.ShowAHPanel() L.ShowAHPage(AH.ScanIndex) end
function L.HideAHPanel()
	local Any = false
	for _, Pg in ipairs(AH.Pages) do
		if Pg.Panel:IsShown() then
			Any = true
			if Pg.OnHide then Pg.OnHide(Pg.Panel) end
		end
		Pg.Panel:Hide()
		PanelTemplates_DeselectTab(Pg.Tab)
	end
	if not Any then return end
	local Sel = SelectedBlizzTab()
	if Sel then PanelTemplates_SelectTab(Sel) end
end
local function HookRowButtons()
	for _, B in ipairs(TabRow()) do
		if not AH.Hooked[B] then AH.Hooked[B] = true; B:HookScript("OnClick", function() L.HideAHPanel() end) end
	end
end
-- A tab on the auction house row with its own panel. Returns the panel (Trade.lua builds AF Buy and AF Sell with it).
function L.NewAHPage(Text, TabName, PanelName, OnShow, OnHide, OnRefresh)
	local Index = #AH.Pages + 1
	local Tab = CreateFrame("Button", TabName, AH.Holder, "PanelTabButtonTemplate")
	Tab:SetText(Text)
	PanelTemplates_TabResize(Tab, 20, nil, 60)
	PanelTemplates_DeselectTab(Tab)
	Tab:SetScript("OnClick", function() PlaySound(SOUNDKIT and SOUNDKIT.IG_CHARACTER_INFO_TAB or 841); L.ShowAHPage(Index) end)
	Tab:SetPoint("TOPLEFT", AuctionHouseFrame, "BOTTOMRIGHT", -150, 2)
	local P = CreateFrame("Frame", PanelName, AuctionHouseFrame)
	P:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPLEFT", 4, -58)
	P:SetPoint("BOTTOMRIGHT", AuctionHouseFrame, "BOTTOMRIGHT", -4, 28)
	-- Above Blizzard's sell frame item box and Post button (fixed frameLevel 350), below its dialog overlay (1000).
	P:SetFrameLevel(math.max(AuctionHouseFrame:GetFrameLevel() + 60, 400))
	P:EnableMouse(true)
	local Bg = P:CreateTexture(nil, "BACKGROUND")
	Bg:SetAllPoints()
	Bg:SetColorTexture(0.06, 0.06, 0.06, 1)
	local Inset = CreateFrame("Frame", nil, P, "InsetFrameTemplate")
	Inset:SetAllPoints()
	-- Cover the strip above the page (right of the portrait), where Blizzard's last page would show its own sub-tabs
	-- and refresh button.
	local Cover = CreateFrame("Frame", nil, P)
	Cover:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPLEFT", 62, -22)
	Cover:SetPoint("BOTTOMRIGHT", P, "TOPRIGHT", 0, 0)
	Cover:EnableMouse(true)
	local CoverBg = Cover:CreateTexture(nil, "BACKGROUND")
	CoverBg:SetAllPoints()
	CoverBg:SetColorTexture(0.06, 0.06, 0.06, 1)
	P.Cover = Cover
	if OnRefresh then
		-- Round refresh button at the top right, where Blizzard's pages have theirs.
		-- Blizzard's own refresh button (sharp atlas art); the old 32px texture only if the template is missing.
		local Ok, R = pcall(CreateFrame, "Button", nil, Cover, "RefreshButtonTemplate")
		if not Ok or not R then
			R = CreateFrame("Button", nil, Cover)
			R:SetNormalTexture("Interface\\Buttons\\UI-RefreshButton")
			R:SetPushedTexture("Interface\\Buttons\\UI-RefreshButton-Down")
			R:SetHighlightTexture("Interface\\Buttons\\ButtonHilight-Square", "ADD")
		end
		R:SetSize(26, 26)
		R:SetPoint("TOPRIGHT", AuctionHouseFrame, "TOPRIGHT", -12, -27)
		R:SetFrameLevel(Cover:GetFrameLevel() + 5)
		R:SetScript("OnClick", OnRefresh)
		R:SetScript("OnEnter", function(self)
			GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
			GameTooltip:AddLine("Refresh prices")
			GameTooltip:AddLine("Re-checks the current auction house prices for the items listed here.", 1, 1, 1, true)
			GameTooltip:Show()
		end)
		R:SetScript("OnLeave", function() GameTooltip:Hide() end)
		P.Refresh = R
	end
	P:Hide()
	AH.Pages[Index] = { Tab = Tab, Panel = P, OnShow = OnShow, OnHide = OnHide }
	return P, Tab
end
function L.CreateAHTab()
	if AH.Holder or not AuctionHouseFrame then return end
	AH.Hooked = {}
	AH.Holder = CreateFrame("Frame", nil, AuctionHouseFrame) -- owns the tabs, so they aren't added to Blizzard's Tabs
	AH.Holder:SetSize(1, 1)
	AH.Holder:SetPoint("TOPLEFT")
	if AF.Trade then AF.Trade.Build() end -- AF Buy, AF Sell

	local P, Tab = L.NewAHPage("AuctionForever", "AuctionForeverAHTab", "AuctionForeverAHPanel", function() L.RefreshAHPanel() end)
	PanelTemplates_TabResize(Tab, 20, nil, 70)
	AH.Panel, AH.Tab, AH.ScanIndex = P, Tab, #AH.Pages

	P.Title = P:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
	P.Title:SetPoint("TOPLEFT", 20, -18)
	P.Title:SetText("AuctionForever")
	P.Data = P:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	P.Data:SetPoint("TOPLEFT", P.Title, "BOTTOMLEFT", 0, -10)
	P.Data:SetJustifyH("LEFT")
	local function Btn(Text, X, Y, W, OnClick, Tip)
		local B = CreateFrame("Button", nil, P, "UIPanelButtonTemplate")
		B:SetSize(W, 26); B:SetText(Text); B:SetPoint("TOPLEFT", X, Y); B:SetScript("OnClick", OnClick)
		B:SetScript("OnEnter", function(self)
			GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
			GameTooltip:AddLine(Text)
			for _, Ln in ipairs(Tip) do GameTooltip:AddLine(Ln, 1, 1, 1, true) end
			GameTooltip:Show()
		end)
		B:SetScript("OnLeave", function() GameTooltip:Hide() end)
		return B
	end
	P.Quick = Btn("Quick Scan", 20, -90, 140, function() AF.Scan.Quick(); L.RefreshAHPanel() end,
		{ "Fast: current lowest price and stock for every item, in a few requests (the same method as Auctionator's scan).",
		  "Doesn't measure sales by itself; full scans and the cloud data do that." })
	P.Full = Btn("Full Scan", 170, -90, 140, function() AF.Scan.Start(); L.RefreshAHPanel() end,
		{ "Reads every listing in the auction house: fresh prices for everything, and sales measured for every item.",
		  "The server may allow this only once every 15 min." })
	P.Open = Btn("Open lists", 320, -90, 140, function() L.Toggle(1) end, { "Opens the AuctionForever window (Farm, Flip and Sessions)." })
	P.QuickInfo = P:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	P.QuickInfo:SetPoint("TOPLEFT", 20, -124)
	P.QuickInfo:SetJustifyH("LEFT")
	-- Progress bar shown while a scan runs (same spot as the line above).
	local Bar = CreateFrame("StatusBar", nil, P)
	Bar:SetPoint("TOPLEFT", 20, -122)
	Bar:SetSize(440, 18)
	Bar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar")
	Bar:SetStatusBarColor(0.1, 0.6, 0.1)
	Bar:SetMinMaxValues(0, 1)
	local BarBg = Bar:CreateTexture(nil, "BACKGROUND")
	BarBg:SetAllPoints()
	BarBg:SetColorTexture(0, 0, 0, 0.6)
	Bar.Text = Bar:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	Bar.Text:SetPoint("CENTER")
	Bar:Hide()
	P.Bar = Bar
	P.Tick, P.Cool = 0, 0
	P:SetScript("OnUpdate", function(self, Elapsed)
		self.Tick = self.Tick + Elapsed
		if self.Tick < 0.1 then return end
		self.Tick = 0
		if AF.Scan.Busy() then L.ScanProgress()
		elseif AF.Scan.FullCooldown() > 0 then
			self.Cool = (self.Cool or 0) + 1
			if self.Cool >= 50 then self.Cool = 0; L.RefreshAHPanel() end -- countdown on the button, every 5 s
		end
	end)
	P.Result = P:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	P.Result:SetPoint("TOPLEFT", 20, -150)
	P.Result:SetWidth(740)
	P.Result:SetJustifyH("LEFT")

	AH.Holder:SetScript("OnShow", function() C_Timer.After(0, function() PlaceTab(); HookRowButtons() end) end)
	AH.Holder:SetScript("OnHide", function() L.HideAHPanel() end)
	hooksecurefunc(AuctionHouseFrame, "SetDisplayMode", function() L.HideAHPanel() end)
	C_Timer.After(0, function() PlaceTab(); HookRowButtons() end)
end
function L.RefreshAHPanel()
	if not (AH.Panel and AH.Panel:IsShown()) then return end
	local P = AH.Panel
	local Parts = {}
	local Age, Watched = Core.DataAge(), Core.HoursWatched() or 0
	Parts[#Parts + 1] = Age and string.format("Cloud data: %s old, %.1f h of sales measured.", Age < 1 and (math.floor(Age * 60) .. " min") or string.format("%.1f h", Age), Watched) or "Cloud data: none yet (start AuctionForever Sync, then /reload)."
	local Fresh = AuctionForeverDB and AuctionForeverDB.fresh
	if Fresh and Fresh.time then Parts[#Parts + 1] = string.format("Your last full scan: %d min ago.", math.floor((time() - Fresh.time) / 60)) end
	P.Data:SetText(table.concat(Parts, "   "))
	local Busy = AF.Scan.Busy()
	local Cool = AF.Scan.FullCooldown()
	P.Quick:SetEnabled(not Busy); P.Full:SetEnabled(not Busy and Cool <= 0)
	P.Full:SetText(Cool > 0 and string.format("Full Scan (%d min)", math.ceil(Cool / 60)) or "Full Scan")
	if not Busy then P.QuickInfo:SetText("Quick Scan: fresh prices for everything.  Full Scan: also measures sales (scan 15+ min apart).") end
	P.Result:SetText(AF.Scan.LastResult or "No scan yet this session.")
end
-- A quick scan read more items (throttled): refresh AF Buy / AF Sell with them.
function L.ScanLive()
	if AF.Trade and AF.Trade.OnScanLive then AF.Trade.OnScanLive() end
end
function L.ScanProgress()
	if AF.Trade and AF.Trade.OnScanProgress then AF.Trade.OnScanProgress() end
	if not (AH.Panel and AH.Panel:IsShown()) then return end
	local P = AH.Panel
	local Text, F = AF.Scan.Status()
	if not Text then return end
	P.Quick:SetEnabled(false); P.Full:SetEnabled(false)
	P.QuickInfo:Hide()
	P.Bar:Show()
	P.Bar.Text:SetText(Text)
	P.Bar:SetStatusBarColor(0.1, 0.6, 0.1)
	P.Bar:SetValue(F or 0)
end
function L.ScanDone()
	if AF.Trade and AF.Trade.OnScanDone then AF.Trade.OnScanDone() end
	if AH.Panel then AH.Panel.Bar:Hide(); AH.Panel.QuickInfo:Show() end
	L.RefreshAHPanel()
	-- The open AuctionForever window: its list is worked out again from the new data in the background (every item
	-- and recipe: seconds of work, a freeze when done on the spot), then shown.
	if Frame and Frame:IsShown() then
		L.LaterOnce("window", function() if Tab == 1 then L.FarmData() elseif Tab == 2 then L.FlipRows() end end,
			function() if Frame:IsShown() then L.Load() end end)
	end
end

StaticPopupDialogs["AUCTIONFOREVER_CLEAR_SESSIONS"] = {
	text = "Delete all recorded farming sessions?",
	button1 = YES or "Yes", button2 = NO or "No",
	OnAccept = function() Session.Clear(); L.RefreshSessions() end,
	timeout = 0, whileDead = true, hideOnEscape = true,
}

-- Minimap button -------------------------------------------------------------------------------------------------
local function PlaceMinimapButton(B)
	local A = math.rad(Account().minimapAngle)
	local R = (Minimap:GetWidth() / 2) + 5
	B:ClearAllPoints()
	B:SetPoint("CENTER", Minimap, "CENTER", math.cos(A) * R, math.sin(A) * R)
end
function L.CreateMinimapButton()
	local B = CreateFrame("Button", "AuctionForeverMinimapButton", Minimap)
	B:SetSize(31, 31)
	B:SetFrameStrata("MEDIUM")
	B:SetFrameLevel(8)
	B:RegisterForClicks("LeftButtonUp", "RightButtonUp")
	B:RegisterForDrag("LeftButton")
	B:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
	local Bg = B:CreateTexture(nil, "BACKGROUND")
	Bg:SetSize(20, 20); Bg:SetPoint("TOPLEFT", 7, -5)
	Bg:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
	local Ic = B:CreateTexture(nil, "ARTWORK")
	Ic:SetSize(17, 17); Ic:SetPoint("TOPLEFT", 7, -6)
	Ic:SetTexture("Interface\\Icons\\INV_Misc_Coin_02")
	local Border = B:CreateTexture(nil, "OVERLAY")
	Border:SetSize(53, 53); Border:SetPoint("TOPLEFT")
	Border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
	B:SetScript("OnClick", function(_, Button) L.Toggle(Button == "RightButton" and 2 or 1) end)
	B:SetScript("OnDragStart", function(self)
		self:SetScript("OnUpdate", function()
			local MX, MY = Minimap:GetCenter()
			local CX, CY = GetCursorPosition()
			local S = Minimap:GetEffectiveScale()
			Account().minimapAngle = math.deg(math.atan2(CY / S - MY, CX / S - MX))
			PlaceMinimapButton(self)
		end)
	end)
	B:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
	B:SetScript("OnEnter", function(self)
		GameTooltip:SetOwner(self, "ANCHOR_LEFT")
		GameTooltip:AddLine("AuctionForever")
		GameTooltip:AddLine("Click: farm list   Right-click: flips", 1, 1, 1)
		GameTooltip:AddLine("Drag: move this button", 0.7, 0.7, 0.7)
		GameTooltip:Show()
	end)
	B:SetScript("OnLeave", function() GameTooltip:Hide() end)
	PlaceMinimapButton(B)
	return B
end

-- Tooltips -------------------------------------------------------------------------------------------------------
-- When your data on this item was last checked: your latest scan or lookup of it, else the cloud data.
local function CheckedAt(id)
	local S = AuctionForeverDB
	local F = S and S.fresh and S.fresh.items and S.fresh.items[id]
	local T = F and (F[4] or S.fresh.time) or nil
	local D = AuctionForeverData
	local C = type(D) == "table" and D.time or nil
	if T and C then return math.max(T, C) end
	return T or C
end
-- A small warning icon when the price data is over an hour old (or its age is unknown); nothing otherwise.
local STALE_TIP = 3600
local function StaleMark(T)
	if T and time() - T <= STALE_TIP then return "" end
	return " |TInterface\\DialogFrame\\UI-Dialog-Icon-AlertNew:0|t"
end
-- The AH price to show: the target price AuctionForever would post at, from your latest data (no live check);
-- items it can't rate yet show the recent selling price.
local function TargetPrice(I)
	if not I then return nil end
	local S = Core.Status(I)
	if S == "good" or S == "early" then
		local Price = Core.SellPrice(I, 1)
		if Price then return Price end
	end
	return Core.Market(I)
end
L.TargetPrice = TargetPrice

-- What to do with an item you hold: the one decision the tooltip's Rec line, the bag icons and AF Sell share.
-- Returns Rec, the vendor price, the AH target price, and Why (for "Keep" / "-"):
--   "Keep"    soulbound (Bound: can't go on the auction house) or on your keep list
--   "-"       a quest item, or nothing pays for it (no AH data and no vendor price)
--   "Auction" / "Vendor"  Core.Recommend: the AH after the cut against the vendor price, weighed by the chance it
--             sells and the deposit lost when it doesn't; a seller without steady data needs 1.5x the vendor price
--   nil       the vendor price isn't known yet (item not loaded; asked for): decided once it is
-- AF Sell lists what this says "Auction" for first, then "Vendor" (marked), then the rest (Trade.BuildQueue).
function L.SellAdvice(id, Key, Bound)
	local Keep = type(AuctionForeverDB) == "table" and type(AuctionForeverDB.keep) == "table" and AuctionForeverDB.keep
	if Bound then return "Keep", nil, nil, "soulbound" end
	if Keep and Keep[id] then return "Keep", nil, nil, "keep list" end
	local _, _, _, _, _, ClassID = C_Item.GetItemInfoInstant(id)
	if ClassID == 12 then return "-", nil, nil, "quest item" end
	local I = Core.Info(Key or id)
	local Target = TargetPrice(I)
	local V = VendorKnown(id)
	if V == nil then
		if C_Item.RequestLoadItemDataByID then C_Item.RequestLoadItemDataByID(id) end
		return nil, nil, Target
	end
	if not I then
		if V > 0 then return "Vendor", V, nil end
		return "-", V, nil, "nothing pays for it"
	end
	return Core.Recommend(I, V, Target) or (V > 0 and "Vendor" or "-"), V, Target
end

-- The item's Farm tier (S/A/B/C/D): its expected earnings each (net x sell rate - deposit lost, as the Farm lists
-- work it out) ranked against the Farm All list, with MarkTiers' cut-offs. nil when it isn't known (no data, still
-- warming up, no sales measured).
local TierScores
function L.ItemTier(Key)
	-- (not worked out on the spot: the lists are built in the background, no tier until they're ready)
	if not L.ListsReady() then L.BuildListsLater() return nil end
	local R = Farm.Raw(Key, FarmEnv())
	local X = R.expected
	if R.excluded then
		if X and X <= 0 then return "D" end
		return nil
	end
	if not X then return nil end
	if X <= 0 then return "D" end
	local Rows = L.AllRows()
	if not (TierScores and TierScores.rows == Rows) then
		local S = {}
		for _, Rw in ipairs(Rows) do local Sc = Rw.score or Rw.expected; if Sc then S[#S + 1] = Sc end end
		TierScores = { rows = Rows, scores = S }
	end
	local Above, N = 0, #TierScores.scores
	for _, Sc in ipairs(TierScores.scores) do if Sc > X then Above = Above + 1 end end
	if N == 0 then return nil end
	for _, T in ipairs(L.TIERS) do if Above / N < T[2] then return T[1] end end
	return "D"
end

-- The tooltip's lines under "AuctionForever": Tier, Vendor, AH, Rec and Source. Count (Shift held, a stack of more
-- than one): Vendor, AH and Rec's delta for the whole stack, labeled "(x20)", or "(x20 in bags)" when the count is
-- what you carry (InBags). Key: the hovered item's market (a suffix version's own, see Core.LinkKey); a version with
-- no data shows no AH value, never another version's. Bound: the hovered item is soulbound.
function L.TooltipLines(id, Count, InBags, Key, Bound)
	local I = Core.Info(Key or id)
	local V = VendorKnown(id) -- nil: not known yet (shown as such)
	if not I and (V or 0) <= 0 then return nil end
	local Target = TargetPrice(I)
	local N = (Count and Count > 1) and math.floor(Count) or 1
	local Tag = N > 1 and string.format(" (x%d%s)", N, InBags and " in bags" or "") or ""
	local Rec, _, _, Why = L.SellAdvice(id, Key, Bound)
	local RecText = Rec or "-"
	if (Rec == "Auction" or Rec == "Vendor") and Target and V then
		-- Per unit: the AH price after the 5% cut minus what a vendor pays (times the stack).
		RecText = Rec .. "  " .. Core.MoneyDelta((math.floor(Target * (1 - Core.Cut)) - V) * N)
	elseif Why then
		RecText = RecText .. " (" .. Why .. ")"
	end
	local Ok, Tier = pcall(L.ItemTier, Key or id)
	local AHText = Target and (Core.MoneyColor(Target * N) .. StaleMark(CheckedAt(id))) or "no data"
	if not Target and Core.GearInfo(id) then
		-- Gear with no market data: an estimate from similar gear, marked as one (or plainly no price).
		local E = Core.GearEstimate(id, V)
		AHText = E and string.format("~%s (est. from %d similar)", Core.MoneyColor(E.price * N), E.n) or "no price"
	end
	local Out = {
		{ "Tier", (Ok and Tier) and L.TierText(Tier) or "-" },
		{ "Vendor" .. Tag, (V == nil and "not known yet") or (V > 0 and Core.MoneyColor(V * N)) or "-" },
		{ "AH" .. Tag, AHText },
		{ "Rec" .. Tag, RecText },
		{ "Source", AF.Farm.Source(id) },
	}
	if I and AF.Farm.Spike(I) then
		Out[#Out + 1] = { "|cffff8040Warning|r", "|cffff8040price tripled in 24 h|r (usual " .. Core.MoneyColor(AF.Farm.SpikeCap(I)) .. ")" }
	end
	for _, Ln in ipairs(L.CrateLines(id)) do Out[#Out + 1] = Ln end
	return Out
end
-- Merchant's Favor price for crate values: the /af favor setting, else Core.FavorPrice.
function L.FavorPrice()
	local P = Account().favorPrice
	return type(P) == "number" and P > 0 and P or Core.FavorPrice
end
-- A typed price in copper: "250" (copper), "2.5s", "2s50c", "0.1g"; nil when it isn't one.
function L.ParsePrice(S)
	S = tostring(S or ""):lower():gsub("%s+", "")
	if S == "" then return nil end
	if S:match("^%d+%.?%d*$") then return math.floor(tonumber(S) + 0.5) end
	if (S:gsub("%d+%.?%d*[gsc]", "")) ~= "" then return nil end
	local Total = 0
	for N, U in S:gmatch("(%d+%.?%d*)([gsc])") do Total = Total + tonumber(N) * (U == "g" and 10000 or U == "s" and 100 or 1) end
	return math.floor(Total + 0.5)
end
-- "/af favor 2.5s" (or 250, 2s50c...): set it; "/af favor" alone: show it.
function L.FavorCommand(Msg)
	local Arg = Msg:match("^favor%s*(.*)$") or ""
	local P = Arg ~= "" and L.ParsePrice(Arg) or nil
	if Arg ~= "" and P and P > 0 then Account().favorPrice = P end
	if Arg ~= "" and not (P and P > 0) then print("|cffffd100AuctionForever:|r usage: /af favor 2.5s (the price of one Merchant's Favor)") return end
	print("|cffffd100AuctionForever:|r Merchant's Favor valued at " .. Core.MoneyColor(L.FavorPrice()) .. " for crate fair values.")
end
-- Tooltip lines for a Waylaid Crate: its fair value, the Favor it gives, and every bundle that fills it (cheapest
-- first, as listed now). {} for other items.
function L.CrateLines(id)
	local CV = Core.CrateValue(id, nil, L.FavorPrice())
	if not CV then return {} end
	local Out = {
		{ "Fair value", CV.value and Core.MoneyDelta(CV.value) or "no bundle listed" },
		{ "Favor", string.format("%d (%s) x %s", CV.favor, CV.source, Core.MoneyColor(CV.favorPrice)) .. (CV.coin > 0 and (" + " .. Core.MoneyColor(CV.coin)) or "") },
		{ "Fill (any one)", "" },
	}
	for i, O in ipairs(CV.options) do
		Out[#Out + 1] = { string.format("  %d %s", O.n, (L.ItemName(O.id))), (O.cost and Core.MoneyColor(O.cost) or "not enough listed") .. (i == 1 and O.cost and " (cheapest)" or "") }
	end
	return Out
end
-- Is the hovered item soulbound? A bag slot is asked directly; otherwise the tooltip's own "Soulbound" line.
function L.TooltipBound(Tip, TData)
	local Ok, Info = pcall(function() return Tip.GetPrimaryTooltipInfo and Tip:GetPrimaryTooltipInfo() end)
	local Args = Ok and type(Info) == "table" and Info.getterName == "GetBagItem" and Info.getterArgs
	local IL = rawget(_G, "ItemLocation")
	if type(Args) == "table" and IL and C_Item.IsBound then
		local Ok2, Yes = pcall(function() return C_Item.IsBound(IL:CreateFromBagAndSlot(Args[1], Args[2])) end)
		if Ok2 then return Yes == true end
	end
	local Word = rawget(_G, "ITEM_SOULBOUND") or "Soulbound"
	for _, Ln in ipairs(type(TData) == "table" and type(TData.lines) == "table" and TData.lines or {}) do
		if type(Ln) == "table" and Ln.leftText == Word then return true end
	end
	return false
end
-- The hovered stack's size, from what the tooltip shows: the game's getter (a bag slot, loot, mail), else the
-- tooltip owner (a bag button, or any item button that keeps its count). nil when it doesn't say.
function L.TooltipStack(Tip)
	local Ok, Info = pcall(function() return Tip.GetPrimaryTooltipInfo and Tip:GetPrimaryTooltipInfo() end)
	local Get = Ok and type(Info) == "table" and Info.getterName
	local Args = Ok and type(Info) == "table" and Info.getterArgs
	local CC = rawget(_G, "C_Container")
	if Get == "GetBagItem" and type(Args) == "table" and CC and CC.GetContainerItemInfo then
		local Ok2, S = pcall(CC.GetContainerItemInfo, Args[1], Args[2])
		if Ok2 and type(S) == "table" and S.stackCount then return S.stackCount end
	elseif Get == "GetLootItem" and type(Args) == "table" and rawget(_G, "GetLootSlotInfo") then
		local Ok2, _, _, Q = pcall(rawget(_G, "GetLootSlotInfo"), Args[1])
		if Ok2 and type(Q) == "number" then return Q end
	elseif Get == "GetInboxItem" and type(Args) == "table" and rawget(_G, "GetInboxItem") then
		local Ok2, _, _, _, Q = pcall(rawget(_G, "GetInboxItem"), Args[1], Args[2])
		if Ok2 and type(Q) == "number" then return Q end
	end
	local Ok3, Owner = pcall(function() return Tip.GetOwner and Tip:GetOwner() end)
	if Ok3 and type(Owner) == "table" then
		if Owner.GetBagID and Owner.GetID and CC and CC.GetContainerItemInfo then
			local Ok4, S = pcall(function() return CC.GetContainerItemInfo(Owner:GetBagID(), Owner:GetID()) end)
			if Ok4 and type(S) == "table" and S.stackCount then return S.stackCount end
		end
		if type(rawget(Owner, "count")) == "number" then return Owner.count end
	end
	return nil
end
-- With Shift held: the stack's count and whether it's your bag count instead (no stack to read); nil = one item.
function L.TooltipCount(Tip, id)
	if not IsShiftKeyDown() then return nil end
	local N = L.TooltipStack(Tip)
	if N then return N > 1 and N or nil, false end
	local Ok, B = pcall(C_Item.GetItemCount, id)
	if Ok and type(B) == "number" and B > 1 then return B, true end
	return nil
end
-- For the bag icons (Bags.lua): the tooltip's Rec ("Auction" or "Vendor"; nil for Keep / "-") and the vendor price.
-- A third result, true: the vendor price isn't known yet (the item isn't loaded), so no advice yet; ask again later.
function L.BagAdvice(id, Key, Bound)
	local Rec, V = L.SellAdvice(id, Key, Bound)
	if Rec == nil then return nil, nil, true end
	if Rec ~= "Auction" and Rec ~= "Vendor" then return nil, V end
	return Rec, V
end
-- Shift pressed or released while our tooltip shows an item: show it again (stack values on / off). Listened to only
-- while such a tooltip is up.
local ShiftWatch = CreateFrame("Frame")
local Watched -- { tip, id }
ShiftWatch:SetScript("OnEvent", function(_, _, Key)
	if not (Key == "LSHIFT" or Key == "RSHIFT") or not Watched then return end
	local Tip = Watched.tip
	if not Tip:IsShown() then Watched = nil; ShiftWatch:UnregisterEvent("MODIFIER_STATE_CHANGED") return end
	local _, Link = Tip:GetItem()
	local id = Link and tonumber(Link:match("item:(%d+)"))
	if id ~= Watched.id then return end
	if Tip.RefreshData then pcall(Tip.RefreshData, Tip) return end
	local Owner = Tip:GetOwner()
	local Enter = Owner and Owner.GetScript and Owner:GetScript("OnEnter")
	if Enter then pcall(Enter, Owner) end
end)
local HideHooked = {}
local function WatchShift(Tip, id)
	Watched = { tip = Tip, id = id }
	ShiftWatch:RegisterEvent("MODIFIER_STATE_CHANGED")
	if not HideHooked[Tip] then
		HideHooked[Tip] = true
		Tip:HookScript("OnHide", function(self)
			if Watched and Watched.tip == self then Watched = nil; ShiftWatch:UnregisterEvent("MODIFIER_STATE_CHANGED") end
		end)
	end
end
L.ShiftWatch = ShiftWatch
local function OnTooltip(Tip, TData)
	if Tip ~= GameTooltip and Tip ~= ItemRefTooltip then return end
	local id = TData and TData.id
	if not id then return end
	local Link = TData.hyperlink
	if not Link and Tip.GetItem then local Ok, _, L2 = pcall(Tip.GetItem, Tip); Link = Ok and L2 or nil end
	local N, InBags = L.TooltipCount(Tip, id)
	local Lines = L.TooltipLines(id, N, InBags, Core.LinkKey(Link, id), L.TooltipBound(Tip, TData))
	if not Lines then return end
	WatchShift(Tip, id)
	Tip:AddLine(" ")
	Tip:AddLine("AuctionForever", 1, 0.82, 0)
	for _, Ln in ipairs(Lines) do Tip:AddDoubleLine(Ln[1], Ln[2], 0.8, 0.8, 0.8, 1, 1, 1) end
end

-- Events ---------------------------------------------------------------------------------------------------------
local Events = CreateFrame("Frame")
Events:RegisterEvent("PLAYER_LOGIN")
Events:RegisterEvent("TRADE_SKILL_SHOW")
Events:RegisterEvent("TRADE_SKILL_LIST_UPDATE")
Events:RegisterEvent("PLAYER_LOGOUT")
Events:RegisterEvent("CHAT_MSG_LOOT")
Events:RegisterEvent("CHAT_MSG_MONEY")
Events:RegisterEvent("GET_ITEM_INFO_RECEIVED")
Events:RegisterEvent("AUCTION_HOUSE_SHOW")
Events:RegisterEvent("OWNED_AUCTIONS_UPDATED")
-- Your active auctions, per item and unit price, from the game's list (filled when the game shows your auctions, e.g.
-- the Auctions tab). Core leaves them out of the price ladder: they aren't stock in front of you.
function L.ReadOwnedAuctions()
	local AH = rawget(_G, "C_AuctionHouse")
	if not (AH and AH.GetOwnedAuctions) then return end
	local Ok, List = pcall(AH.GetOwnedAuctions)
	if not Ok or type(List) ~= "table" then return end
	local Mine = {}
	for _, A in ipairs(List) do
		local id = A.itemKey and A.itemKey.itemID
		local Q, P = A.quantity or 0, A.buyoutAmount
		if id and P and Q > 0 and (A.status or 0) == 0 then -- 0 = active (1 = sold, waiting in the mail)
			Mine[id] = Mine[id] or {}
			Mine[id][P] = (Mine[id][P] or 0) + Q
		end
	end
	Core.MyListings = Mine
end
local RefreshQueued
Events:SetScript("OnEvent", function(_, Event, Msg)
	if Event == "PLAYER_LOGIN" then
		L.BuildPatterns()
		Char(); Account()
		local S = Session.Current()
		if S then S.runningSince = nil end -- a clock never runs across logins
		L.CreateMinimapButton()
		-- Names: your bag items 5 s in; the Farm list's top rows once the lists are built in the background (working
		-- them out here, with the flip plan and the quick scan list, was a second-long freeze after every /reload).
		C_Timer.After(5, function()
			local Ids = {}
			for id in pairs(L.BagCounts()) do Ids[#Ids + 1] = id end
			L.Preload(Ids)
			L.BuildListsLater(function()
				local Top = {}
				for i, R in ipairs(L.FarmRows()) do if i > 60 then break end Top[#Top + 1] = R.id end
				L.Preload(Top)
			end)
		end)
		if TooltipDataProcessor and Enum and Enum.TooltipDataType then
			TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, OnTooltip)
		end
	elseif Event == "TRADE_SKILL_SHOW" or Event == "TRADE_SKILL_LIST_UPDATE" then
		pcall(L.LearnRecipes) -- never let this break the profession window
	elseif Event == "OWNED_AUCTIONS_UPDATED" then
		L.ReadOwnedAuctions()
	elseif Event == "AUCTION_HOUSE_SHOW" then
		L.ResetBudget()
		L.CreateAHTab()
		L.HideAHPanel()
	elseif Event == "PLAYER_LOGOUT" then
		Session.Pause()
	elseif Event == "CHAT_MSG_LOOT" then
		local id, N = L.ParseLoot(Msg or "")
		if id then Session.AddItem(id, N) end
	elseif Event == "CHAT_MSG_MONEY" then
		local C = L.ParseMoney(Msg or "")
		if C > 0 then Session.AddMoney(C) end
	elseif Event == "GET_ITEM_INFO_RECEIVED" then
		LearnName(tonumber(Msg))
		if not RefreshQueued then
			RefreshQueued = true
			C_Timer.After(0.3, function()
				RefreshQueued = false
				if Frame and Frame:IsShown() then L.Refresh() end
				if AF.Trade and AF.Trade.RedrawNames then AF.Trade.RedrawNames() end
			end)
		end
	end
end)

SLASH_AUCTIONFOREVER1 = "/af"
SLASH_AUCTIONFOREVER2 = "/auctionforever"
SlashCmdList.AUCTIONFOREVER = function(Msg)
	Msg = (Msg or ""):lower()
	if Msg:match("^brief") and AF.Brief then AF.Brief.Command(Msg) return end
	if Msg:match("^favor") then L.FavorCommand(Msg) return end
	if Msg:match("^keep") and AF.Bags then AF.Bags.KeepCommand(Msg) elseif Msg:match("^icon") and AF.Bags then AF.Bags.IconCommand(Msg) elseif Msg == "flip" then L.Toggle(2) elseif Msg == "sessions" then L.Toggle(3) elseif Msg == "scan" then AF.Scan.Start() elseif Msg == "quick" then AF.Scan.Quick() elseif Msg == "selftest" then AF.SelfTest.Run()
	elseif Msg == "missed" then for _, Ln in ipairs(L.MissedSummary()) do print("|cffffd100AuctionForever:|r " .. Ln) end
	else L.Toggle(1) end
end

AF.UI = L
