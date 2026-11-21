-- Login brief: a few chat lines worth acting on, printed once a few seconds after a fresh login (never on /reload),
-- and any time with "/af brief". Only printed to your own chat frame: nothing is ever sent to other players.
local _, AF = ...
local Core, Farm = AF.Core, AF.Farm

local B = {}
AF.Brief = B

-- Thresholds (copper) and limits.
B.DELAY = 5               -- seconds after a fresh login, so it isn't buried under the login messages
B.MIN_PLAN_PROFIT = 5000  -- Buy line: the flip plan's profit must be at least 50s
B.MIN_CRAFT_PROFIT = 5000 -- Craft line: profit per craft at least 50s
B.MIN_GATHER_EACH = 5000  -- Gather line: expected at least 50s each
B.NEW_MIN_QUALITY = 2     -- New on the AH: Uncommon or better ...
B.NEW_MIN_PRICE = 10000   -- ... or a median sale of 1g or more
B.NEW_MAX_NAMES = 3       -- names on the New line
B.SEEN_CAP = 8000         -- the remembered item set never grows past this (it's replaced by what's in the data now)
B.COLOR = "|cffff80ff"    -- whisper pink

-- Gathering professions (skill line and Forever's second line for it) and what each gathers, by item class.
-- No rank filter: the repo's Forever data has no node / herb / skin skill requirements, so every item a profession
-- gathers counts at any rank.
B.GATHER = {
	{ name = "Mining", lines = { 186, 2946 } },
	{ name = "Herbalism", lines = { 182, 2944 } },
	{ name = "Skinning", lines = { 393, 2947 } },
}
-- Gems found by mining (their subclass also holds drops).
B.MINING_GEMS = {}
for _, id in ipairs({ 774, 818, 1210, 1206, 1705, 1529, 3864, 7909, 7910, 12799, 12361, 12364, 12800, 12363 }) do B.MINING_GEMS[id] = true end

local function UI() return AF.UI end
local function DB() AuctionForeverDB = AuctionForeverDB or {} return AuctionForeverDB end
local function Money(C) return Core.MoneyColor(C) end

-- Which gathering profession an item comes from, or nil (fish and drops: none of these).
function B.GatherProfession(id)
	if B.MINING_GEMS[id] then return "Mining" end
	local Class, Sub = Farm.ClassOf(id)
	if Class ~= 7 then return nil end
	if Sub == 7 then return "Mining" elseif Sub == 9 then return "Herbalism" elseif Sub == 6 then return "Skinning" end
	return nil
end
-- This character's gathering professions: { [name] = rank }.
function B.MyGathering()
	local SI = rawget(_G, "C_SkillInfo")
	local Get = SI and SI.GetSkillLineInfoByID
	local Out = {}
	if not Get then return Out end
	for _, P in ipairs(B.GATHER) do
		for _, Line in ipairs(P.lines) do
			local Ok, Info = pcall(Get, Line)
			if Ok and type(Info) == "table" and (Info.rank or 0) > 0 then Out[P.name] = math.max(Out[P.name] or 0, Info.rank) end
		end
	end
	return Out
end

-- Items worth a "new" mention: Uncommon or better, or a median sale of 1g or more.
local function Notable(id, I)
	if (UI().QualityOf(id) or 1) >= B.NEW_MIN_QUALITY then return true end
	local M = I and (I.med or I.med24 or I.medAll)
	return type(M) == "number" and M >= B.NEW_MIN_PRICE
end
-- New on the AH since the last brief: notable items in the data now that weren't the last time. The set is kept per
-- account (AuctionForeverDB.briefSeen); the first time there's nothing to compare with, so nothing is "new".
function B.NewItems()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return {} end
	local Seen = DB().briefSeen
	local Now, New, N = {}, {}, 0
	for id in pairs(D.items) do
		local I = Core.Info(id)
		if Notable(id, I) then
			Now[id] = true
			N = N + 1
			if type(Seen) == "table" and not Seen[id] then New[#New + 1] = { id = id, info = I, value = (I and I.med or 0) * math.max(1, I and I.sales or 0) } end
		end
	end
	-- Remember what's there now (old ids stay until the set gets too big, then only today's are kept).
	local Keep = {}
	if type(Seen) == "table" then
		local Count = N
		for id in pairs(Seen) do
			if not Now[id] and Count < B.SEEN_CAP then Keep[id] = true; Count = Count + 1 end
		end
	end
	for id in pairs(Now) do Keep[id] = true end
	DB().briefSeen = Keep
	table.sort(New, function(a, b) if a.value ~= b.value then return a.value > b.value end return a.id < b.id end)
	return New
end

-- The brief's lines (without the color and prefix).
function B.Lines()
	local Out = {}
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return { "No auction data yet: scan at the auction house." } end
	local Age = math.max(0, math.floor((time() - (D.time or time())) / 60))
	Out[1] = string.format("Data %d min old (%d h history).", Age, D.hours or 0)
	-- Buy: the flip plan for your gold now.
	local Ok = pcall(function() UI().FlipTargets() end)
	local P = Ok and UI().LastPlan
	if P and (P.count or 0) > 0 and (P.profit or 0) >= B.MIN_PLAN_PROFIT then
		Out[#Out + 1] = string.format("Buy: %d flip%s, %s in plan. Check the AF Buy tab.", P.count, P.count == 1 and "" or "s", Core.MoneyDelta(P.profit))
	end
	-- Craft: the best plan for a recipe this character knows (Show all doesn't count), by profit a craft.
	local Best
	local Ok2, Crafts = pcall(function() return UI().CraftTargets(true) end)
	for _, E in ipairs(Ok2 and Crafts or {}) do
		local F = E.flip
		if E.known and not F.blocked and not F.onCooldown and (F.craftProfit or 0) >= B.MIN_CRAFT_PROFIT
			and (not Best or F.craftProfit > Best.flip.craftProfit) then Best = E end
	end
	if Best then
		Out[#Out + 1] = string.format("Craft: %s %s per craft, mats under target.", UI().ItemName(Best.id), Core.MoneyDelta(Best.flip.craftProfit))
	end
	-- Gather: the best item this character's gathering professions bring in.
	local Mine = B.MyGathering()
	if next(Mine) then
		local G, GP
		for _, R in ipairs(UI().GatherRows() or {}) do
			local Prof = B.GatherProfession(R.id)
			if Prof and Mine[Prof] and (R.expected or 0) >= B.MIN_GATHER_EACH and (not G or R.expected > G.expected) then G, GP = R, Prof end
		end
		if G then
			Out[#Out + 1] = string.format("Gather: %s ~%s each, %d sold/day (%s).", UI().ItemName(G.id), Money(math.floor(G.expected)), math.floor((G.salesDay or 0) + 0.5), GP)
		end
	end
	-- New on the AH since last time.
	local New = B.NewItems()
	if #New > 0 then
		local Names = {}
		for i, X in ipairs(New) do
			if i > B.NEW_MAX_NAMES then break end
			local Name = UI().ItemName(X.id)
			if i == 1 and X.info and (X.info.sales or 0) > 0 and X.info.med then
				Name = string.format("%s (%d sold at %s)", Name, X.info.sales, Money(X.info.med))
			end
			Names[#Names + 1] = Name
		end
		Out[#Out + 1] = "New on the AH: " .. table.concat(Names, ", ") .. "."
	end
	if #Out == 1 then Out[2] = "Nothing big today." end
	return Out
end

local function Say(Text)
	local F = rawget(_G, "DEFAULT_CHAT_FRAME")
	-- Coin colors end with |r: go back to pink after each, so the whole line stays pink.
	local Line = B.COLOR .. "[AF] " .. Text:gsub("|r", "|r" .. B.COLOR) .. "|r"
	if F and F.AddMessage then F:AddMessage(Line) else print(Line) end
end
function B.Print()
	for _, Ln in ipairs(B.Lines()) do Say(Ln) end
end
function B.Enabled() return DB().briefOff ~= true end
-- "/af brief" prints it; "/af brief off" / "on" turns the login print off or on.
function B.Command(Msg)
	local Arg = (Msg or ""):match("^brief%s*(%a*)") or ""
	if Arg == "off" then DB().briefOff = true; Say("Login brief off (\"/af brief on\" turns it back on).")
	elseif Arg == "on" then DB().briefOff = nil; Say("Login brief on.")
	else B.Print() end
end

-- A fresh login (not a /reload): one timer, then the brief.
local Events = CreateFrame("Frame")
Events:RegisterEvent("PLAYER_ENTERING_WORLD")
Events:SetScript("OnEvent", function(_, _, IsInitialLogin, IsReloadingUi)
	if IsInitialLogin and not IsReloadingUi and B.Enabled() then
		C_Timer.After(B.DELAY, function() pcall(B.Print) end)
	end
end)
