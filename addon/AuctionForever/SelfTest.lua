-- /af selftest: checks inside the real game what offline tests can't (API, taint, layout, live server answers).
-- Prints pass/fail in chat and saves the results in AuctionForeverDB.selftest (written to disk on /reload).
local _, AF = ...
local T = {}
AF.SelfTest = T

local Lines, Fails, Started

local function Add(Pass, Text)
	local Tag = Pass == nil and "|cffffd100INFO|r" or (Pass and "|cff1eff00PASS|r" or "|cffff4040FAIL|r")
	if Pass == false then Fails = Fails + 1 end
	Lines[#Lines + 1] = (Pass == nil and "INFO " or (Pass and "PASS " or "FAIL ")) .. Text
	print("|cffffd100AuctionForever selftest:|r " .. Tag .. " " .. Text)
end

local function Finish()
	AuctionForeverDB = AuctionForeverDB or {}
	AuctionForeverDB.selftest = { time = time(), fails = Fails, lines = Lines }
	print(string.format("|cffffd100AuctionForever selftest:|r done, %d problem(s). /reload saves the results for checking.", Fails))
end

-- Functions the add-on calls.
local function CheckAPI()
	local Need = {
		{ C_AuctionHouse, "C_AuctionHouse", { "ReplicateItems", "GetNumReplicateItems", "GetReplicateItemInfo", "GetReplicateItemTimeLeft",
			"SendBrowseQuery", "GetBrowseResults", "RequestMoreBrowseResults", "HasFullBrowseResults", "SendSearchQuery", "MakeItemKey",
			"GetNumCommoditySearchResults", "GetCommoditySearchResultInfo", "HasFullCommoditySearchResults",
			"GetNumItemSearchResults", "GetItemSearchResultInfo", "HasFullItemSearchResults", "IsThrottledMessageSystemReady", "GetItemKeyInfo", "HasSearchResults",
			"StartCommoditiesPurchase", "ConfirmCommoditiesPurchase", "CancelCommoditiesPurchase", "PlaceBid", "PostCommodity", "ConfirmPostCommodity",
			"PostItem", "ConfirmPostItem", "GetItemCommodityStatus", "CalculateCommodityDeposit", "CalculateItemDeposit" } },
		{ C_Container, "C_Container", { "GetContainerNumSlots", "GetContainerItemInfo" } },
		{ C_Item, "C_Item", { "GetItemInfo", "GetItemInfoInstant", "RequestLoadItemDataByID" } },
		{ _G, "global", { "PanelTemplates_SelectTab", "PanelTemplates_DeselectTab", "PanelTemplates_TabResize", "hooksecurefunc", "issecurevariable", "GetInboxNumItems", "GetInboxHeaderInfo", "GetInboxInvoiceInfo", "GetInboxItem" } },
	}
	local Missing = {}
	for _, N in ipairs(Need) do
		for _, F in ipairs(N[3]) do
			if type(N[1]) ~= "table" or type(N[1][F]) ~= "function" then Missing[#Missing + 1] = N[2] .. "." .. F end
		end
	end
	if not (TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall) then Missing[#Missing + 1] = "TooltipDataProcessor" end
	Add(#Missing == 0, #Missing == 0 and "all game functions the add-on uses exist" or ("missing: " .. table.concat(Missing, ", ")))
end

-- Taint: Blizzard values we must never modify. issecurevariable says whether an add-on has touched them.
local function CheckTaint()
	local Bad = {}
	local function Check(Tbl, Key, Label)
		local Ok, Secure, By = pcall(function() if Tbl then return issecurevariable(Tbl, Key) end return issecurevariable(Key) end)
		if Ok and Secure == false then Bad[#Bad + 1] = Label .. " (touched by " .. tostring(By) .. ")" end
	end
	Check(nil, "StaticPopupDialogs", "StaticPopupDialogs")
	Check(nil, "UISpecialFrames", "UISpecialFrames")
	if AuctionHouseFrame then
		Check(AuctionHouseFrame, "displayMode", "AuctionHouseFrame.displayMode")
		Check(AuctionHouseFrame, "selectedTab", "AuctionHouseFrame.selectedTab")
		Check(AuctionHouseFrame, "Tabs", "AuctionHouseFrame.Tabs")
		Check(nil, "AuctionHouseFrameDisplayMode", "AuctionHouseFrameDisplayMode")
	end
	local Mine, Others = {}, {}
	for _, B in ipairs(Bad) do if B:find("AuctionForever") then Mine[#Mine + 1] = B else Others[#Others + 1] = B end end
	Add(#Mine == 0, #Mine == 0 and "no Blizzard values touched by AuctionForever (no taint)" or ("taint from AuctionForever: " .. table.concat(Mine, ", ")))
	if #Others > 0 then Add(nil, "touched by other add-ons (not ours): " .. table.concat(Others, ", ")) end
end

local function CheckData()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then Add(false, "no cloud data loaded (start AuctionForever Sync, then /reload)") return end
	local N = 0
	for _ in pairs(D.items) do N = N + 1 end
	local Age = AF.Core.DataAge()
	Add(N > 1000, string.format("cloud data: %d items, %.1f h old, %.1f h of sales", N, Age or -1, D.hours or 0))
	local Errors = 0
	for id in pairs(D.items) do
		local Ok = pcall(function() local I = AF.Core.Info(id); AF.Core.Status(I); AF.Core.ValuePerDay(I) end)
		if not Ok then Errors = Errors + 1 end
	end
	Add(Errors == 0, string.format("every item rates without errors (%d errors)", Errors))
end

local function CheckWindow()
	local Ok, Err = pcall(function() AF.UI.Toggle(1); AF.UI.Toggle(1) end)
	Add(Ok and AuctionForeverFrame ~= nil, Ok and "AuctionForever window opens and closes" or ("window error: " .. tostring(Err)))
	Add(AuctionForeverMinimapButton ~= nil and AuctionForeverMinimapButton:IsShown(), "minimap button present")
end

-- Auction house layout: our three tabs visible, on the tab row, not overlapping each other or any other tab.
local OUR_TABS = { { "AuctionForeverBuyTab", "AF Buy", "AuctionForeverBuyPanel" }, { "AuctionForeverSellTab", "AF Sell", "AuctionForeverSellPanel" },
	{ "AuctionForeverAHTab", "AuctionForever", "AuctionForeverAHPanel" } }
local function CheckTab()
	local Buy = AuctionHouseFrame.BuyTab
	local Mine = {}
	for _, D in ipairs(OUR_TABS) do
		local Tab = _G[D[1]]
		if not Tab then Add(false, D[2] .. " tab missing in the auction house") else Mine[#Mine + 1] = { Tab, D[2], _G[D[3]] } end
	end
	for _, M in ipairs(Mine) do Add(M[1]:IsVisible(), M[2] .. " tab visible") end
	if not (Buy and Buy:GetTop() and Mine[1] and Mine[1][1]:GetTop()) then Add(nil, "couldn't measure tab positions") return end
	-- Every visible button on the tab row: Blizzard's, other add-ons' and ours.
	local Row = {}
	local function Walk(F, Depth)
		for _, C in ipairs({ F:GetChildren() }) do
			if C:IsVisible() and C:GetObjectType() == "Button" and C:GetTop() and math.abs(C:GetTop() - Buy:GetTop()) < 6 then
				Row[#Row + 1] = C
			elseif Depth < 2 then Walk(C, Depth + 1) end
		end
	end
	Walk(AuctionHouseFrame, 0)
	for _, M in ipairs(Mine) do
		local Tab = M[1]
		Add(math.abs(Tab:GetTop() - Buy:GetTop()) < 6, string.format("%s tab sits on the tab row (%.0f px from Buy's top)", M[2], Tab:GetTop() - Buy:GetTop()))
		local Overlap = {}
		for _, C in ipairs(Row) do
			local L, R = C:GetLeft(), C:GetRight()
			if C ~= Tab and L and R and Tab:GetLeft() < R - 2 and Tab:GetRight() > L + 2 then Overlap[#Overlap + 1] = (C:GetText() or C:GetName() or "a tab") end
		end
		Add(#Overlap == 0, #Overlap == 0 and (M[2] .. " tab doesn't overlap other tabs") or (M[2] .. " tab overlaps: " .. table.concat(Overlap, ", ")))
	end
	-- Each panel opens on its own and closes.
	for i, M in ipairs(Mine) do
		local P = M[3]
		local Ok = pcall(function() AF.UI.ShowAHPage(i) end)
		local Alone = Ok and P and P:IsVisible()
		for j, O in ipairs(Mine) do if j ~= i and O[3] and O[3]:IsVisible() then Alone = false end end
		Add(Alone, M[2] .. " panel opens (alone)")
	end
	AF.UI.HideAHPanel()
	local Closed = true
	for _, M in ipairs(Mine) do if M[3] and M[3]:IsVisible() then Closed = false end end
	Add(Closed, "panels close")
	Add(type(ItemLocation) == "table" and type(ItemLocation.CreateFromBagAndSlot) == "function", "item locations available (needed to post)")
end

-- One live lookup by plain item number (a commodity), timed. Uses a real search, like clicking Search once.
local function CheckLookup(Next)
	if AF.Scan.Busy() then Add(nil, "a scan is running; skipped the live lookup") Next() return end
	local id = 2589 -- Linen Cloth: always listed
	local T0 = GetTime()
	local Started = AF.Scan.Lookup({ id }, true, function()
		local R = AF.Scan.LastResult or ""
		local Answered = not R:find("didn't answer")
		Add(Answered, string.format("live item lookup answered in %.1f s (%s)", GetTime() - T0, R))
		Next()
	end)
	if not Started then Add(false, "live item lookup couldn't start") Next() end
end

-- Run one check; if it errors, report that as a failure and carry on with the rest.
local function Safe(Name, Fn, ...)
	local Ok, Err = pcall(Fn, ...)
	if not Ok then Add(false, Name .. " check crashed: " .. tostring(Err)) end
	return Ok
end

local function CheckFlips()
	local D = AuctionForeverData
	if type(D) ~= "table" or type(D.items) ~= "table" then return end
	local Rows = AF.UI.FlipRows()
	local P = AF.UI.LastPlan
	local NoFlag = 0
	for id in pairs(D.items) do if not AF.UI.Kind(id) then NoFlag = NoFlag + 1 end end
	Add(nil, string.format("AF Buy: %d flips, plan %d items for budget %s (profit %s); %d items without a commodity flag",
		#Rows, P and P.count or 0, AF.Core.Money(AF.UI.FlipBudget()), AF.Core.Money(P and P.profit or 0), NoFlag))
end

function T.Run()
	Lines, Fails, Started = {}, 0, GetTime()
	local Version = C_AddOns and C_AddOns.GetAddOnMetadata and C_AddOns.GetAddOnMetadata("AuctionForever", "Version") or "?"
	Add(nil, string.format("AuctionForever %s, game %s", tostring(Version), tostring(GetBuildInfo and (GetBuildInfo()) or "?")))
	Safe("API", CheckAPI)
	Safe("taint", CheckTaint)
	Safe("data", CheckData)
	Safe("window", CheckWindow)
	Safe("flips", CheckFlips)
	if AuctionHouseFrame and AuctionHouseFrame:IsShown() then
		Safe("tab", CheckTab)
		if not Safe("lookup", CheckLookup, Finish) then Finish() end
	else
		Add(nil, "auction house closed: open it and run /af selftest again to check the tab and a live lookup")
		Finish()
	end
end
