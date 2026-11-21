-- Bag icons (Baganator, top right corner): the auction icon on items AuctionForever would sell on the auction house,
-- a coin on items for a vendor (the tooltip's "Rec" line). No icon on soulbound items, quest items, items with no
-- recommendation and items on your keep list (/af keep [item link]).
-- Also a Baganator junk source ("AuctionForever"): the vendor items, for its junk search and sell button.
-- One coin per item: when AuctionForever is Baganator's junk source, Baganator draws the coin (its junk icon) and
-- this widget only draws the auction icon. Otherwise this widget draws the coin, except on poor (grey) items, which
-- Baganator's own default junk rule already marks.
local _, AF = ...
local B = {}
AF.Bags = B

-- Icon choices (/af icons lists them, /af icon vendor 2 picks one). A file path, or { atlas = name }, or
-- { file, left, right, top, bottom } for part of a file.
local ICONS = {
	vendor = {
		"Interface\\GossipFrame\\VendorGossipIcon",
		"Interface\\Minimap\\Tracking\\Banker",
		"Interface\\Icons\\INV_Misc_Bag_10",
		"Interface\\Icons\\INV_Misc_Bag_11",
		"Interface\\Icons\\INV_Misc_Coin_02",
		{ atlas = "Banker" },
		{ "Interface\\AddOns\\AuctionForever\\Textures\\UpgradeArrowBig", 0, 0.5, 0.5, 1 }, -- Pawn's coin
	},
	auction = {
		"Interface\\Minimap\\Tracking\\Auctioneer",
		{ atlas = "Auctioneer" },
		"Interface\\Icons\\INV_Hammer_15",
		"Interface\\Icons\\INV_Scroll_03",
		"Interface\\Icons\\INV_Misc_Note_02",
		"Interface\\GossipFrame\\BankerGossipIcon",
	},
}
B.ICONS = ICONS
-- The user's picks (2026-11-20): a bag for vendor, the gold coins for auction.
local DEFAULT = { vendor = 6, auction = 2 }
B.DEFAULT = DEFAULT
local function Choice(Kind)
	-- Picks saved before these defaults (icons version 1) are dropped once, so the new defaults show.
	if AuctionForeverDB and AuctionForeverDB.icons and AuctionForeverDB.iconsVersion ~= 2 then
		AuctionForeverDB.icons, AuctionForeverDB.iconsVersion = nil, 2
	end
	local Saved = AuctionForeverDB and AuctionForeverDB.icons and AuctionForeverDB.icons[Kind]
	return ICONS[Kind][Saved] or ICONS[Kind][DEFAULT[Kind]]
end
local function Draw(Icon, C)
	if type(C) == "table" and C.atlas then
		Icon:SetAtlas(C.atlas)
	elseif type(C) == "table" then
		Icon:SetTexture(C[1])
		Icon:SetTexCoord(C[2], C[3], C[4], C[5])
	else
		Icon:SetTexture(C)
		Icon:SetTexCoord(0, 1, 0, 1)
	end
end
-- The icon as chat text.
local function ChatIcon(C)
	if type(C) == "table" and C.atlas then return "|A:" .. C.atlas .. ":18:18|a" end
	if type(C) == "table" then
		return string.format("|T%s:18:18:0:0:64:64:%d:%d:%d:%d|t", C[1], C[2] * 64, C[3] * 64, C[4] * 64, C[5] * 64)
	end
	return "|T" .. C .. ":18|t"
end
local WIDGET_ID = "auctionforever" -- the auction icon, top right
local VENDOR_WIDGET_ID = "auctionforever_vendor" -- the vendor icon, top left
local JUNK_ID = "auctionforever"
local POOR = 0
local QUEST_CLASS = 12
-- Time budget per refresh (as Gear Upgrade Forever's arrows): items over it are worked out on later frames.
local LIMIT, RESET_INTERVAL = 2 / 60 / 4, 1 / 4

local function Say(Msg) print("|cffffd100AuctionForever:|r " .. Msg) end

-- Keep list (all characters): items never marked for selling.
local function KeepList()
	AuctionForeverDB = AuctionForeverDB or {}
	AuctionForeverDB.keep = AuctionForeverDB.keep or {}
	return AuctionForeverDB.keep
end

local Known, Pending = {}, {}
local Version
local function Refresh()
	local Bag = rawget(_G, "Baganator")
	if Bag and Bag.API and Bag.API.RequestItemButtonsRefresh then Bag.API.RequestItemButtonsRefresh() end
end
function B.Reset() Known = {} Refresh() end

local function ItemID(Link, ID)
	if type(ID) == "number" then return ID end
	return tonumber(string.match(Link or "", "item:(%d+)"))
end

-- "Auction", "Vendor" or "" (no icon). Bound: soulbound.
-- MKey: the item's market (a suffix version's own, from its link; see Core.LinkKey).
local function Decide(ID, Bound, MKey)
	if Bound or KeepList()[ID] then return "" end
	local _, _, _, _, _, ClassID = C_Item.GetItemInfoInstant(ID)
	if ClassID == QUEST_CLASS then return "" end
	local Advice, _, Unknown = AF.UI.BagAdvice(ID, MKey)
	if Unknown then return nil end -- vendor price not known yet: decided later, not cached as "nothing"
	return Advice or ""
end

local TimerResetsAt, Left = 0, 0
local Warned = false
-- The item's advice, cached; nil when this frame's time is used up (asked again on a later frame).
local function Status(ID, Bound, MKey)
	local V = AF.Scan and AF.Scan.Version or 0
	if V ~= Version then Version = V; Known = {} end -- new auction data: work everything out again
	local Key = tostring(MKey or ID) .. (Bound and "#b" or "")
	if Known[Key] ~= nil then return Known[Key] end
	local Start = GetTimePreciseSec()
	if Start >= TimerResetsAt then
		TimerResetsAt = Start + RESET_INTERVAL
		Left = LIMIT
	elseif Left <= 0 then
		return nil
	end
	local Ok, Where = pcall(Decide, ID, Bound, MKey)
	Left = Left - (GetTimePreciseSec() - Start)
	if not Ok then
		if not Warned then Warned = true; Say("bag icon error: " .. tostring(Where)) end
		Where = ""
	end
	Known[Key] = Where
	return Where
end
B.Status = Status

-- Items left over a frame's budget are worked out on the next frames, then the bags are redrawn.
local Retry = CreateFrame("Frame")
local Tries = 0
local function OnUpdate(self)
	Tries = Tries + 1
	for Key, Args in pairs(Pending) do
		if Status(Args[1], Args[2], Args[3]) ~= nil then Pending[Key] = nil end
	end
	if next(Pending) == nil or Tries > 600 then
		Pending = {}
		self:SetScript("OnUpdate", nil)
		Refresh()
	end
end
local function Later(ID, Bound, MKey)
	Pending[tostring(MKey or ID) .. (Bound and "#b" or "")] = { ID, Bound, MKey }
	Tries = 0
	Retry:SetScript("OnUpdate", OnUpdate)
end

-- Is AuctionForever Baganator's junk source (Baganator then draws the coin)?
local function JunkSource()
	local Bag = rawget(_G, "Baganator")
	local API = Bag and Bag.API
	if not (API and API.IsJunkPluginActive) then return false end
	local Ok, Active = pcall(API.IsJunkPluginActive, JUNK_ID)
	return Ok and Active == true
end
B.JunkSource = JunkSource

-- Baganator corner widget: Details is the item button's info (itemID, itemLink, quality, isBound).
-- Is Baganator's own junk icon showing on this item (then it carries the vendor icon, see SkinJunk)?
local function BaganatorJunkShown(Details)
	local Bag = rawget(_G, "Baganator")
	local API = Bag and Bag.API
	if API and API.IsCornerWidgetActive then
		local Ok, Active = pcall(API.IsCornerWidgetActive, "junk")
		if Ok and not Active then return false end
	end
	return JunkSource() or Details.quality == POOR
end
-- Only = "Auction" (the top right widget) or "Vendor" (the top left one); nil = either (tests).
function B.UpdateIcon(Icon, Details, Only)
	local ID = Details and ItemID(Details.itemLink, Details.itemID)
	if not ID then return false end
	local Bound = Details.isBound == true
	local MKey = AF.Core.LinkKey(Details.itemLink, ID)
	local Where = Status(ID, Bound, MKey)
	if Where == nil then Later(ID, Bound, MKey) return false end
	if Only and Where ~= Only then return false end
	if Details.quality == POOR then return false end -- grey items: left to the junk sellers (Leatrix, RXP)
	if Where == "Auction" then
		Draw(Icon, Choice("auction"))
		return true
	elseif Where == "Vendor" then
		if BaganatorJunkShown(Details) then return false end -- Baganator's junk icon (now the vendor icon) shows it
		Draw(Icon, Choice("vendor"))
		return true
	end
	return false
end

-- Baganator junk source: vendor items are junk (its junk search and sell button use this).
function B.IsJunk(BagID, SlotID, ID, Link)
	ID = ItemID(Link, ID)
	if not (Link and ID) then return false end
	local Bound = false
	if C_Item.IsBound and BagID and SlotID then
		local IL = rawget(_G, "ItemLocation")
		if IL then
			local Ok, Yes = pcall(function() return C_Item.IsBound(IL:CreateFromBagAndSlot(BagID, SlotID)) end)
			Bound = Ok and Yes == true
		end
	end
	local Quality = select(3, C_Item.GetItemInfo(Link))
	if Quality == POOR then return false end -- grey items: left to the junk sellers (Leatrix, RXP)
	local MKey = AF.Core.LinkKey(Link, ID)
	local Where = Status(ID, Bound, MKey)
	if Where == nil then Later(ID, Bound, MKey) return false end
	return Where == "Vendor"
end

-- Baganator's own junk icon (a coin, top left by default) shows on every junk item: grey items, or AF's vendor
-- items when AF is its junk source. It gets the chosen vendor icon instead of the coin, and this widget doesn't
-- draw a second one on those items, so each item shows one icon whatever the Baganator settings.
local Buttons = setmetatable({}, { __mode = "k" })
local function SkinJunk(Button)
	local J = Button and Button.JunkIcon
	if not J then return end
	Draw(J, Choice("vendor"))
	J:SetSize(15, 15)
end
B.SkinJunk = SkinJunk

-- /af icons: the choices in chat; /af icon vendor 2 (or auction 3): pick one.
function B.IconCommand(Msg)
	local Kind, N = string.match(Msg or "", "^icon%s+(%a+)%s+(%d+)")
	N = tonumber(N)
	if Kind and ICONS[Kind] and N and ICONS[Kind][N] then
		AuctionForeverDB = AuctionForeverDB or {}
		AuctionForeverDB.icons = AuctionForeverDB.icons or {}
		AuctionForeverDB.icons[Kind] = N
		AuctionForeverDB.iconsVersion = 2
		for Button in pairs(Buttons) do SkinJunk(Button) end
		Say(Kind .. " icon is now " .. ChatIcon(ICONS[Kind][N]) .. " (" .. N .. ").")
		B.Reset()
		return
	end
	for _, K in ipairs({ "vendor", "auction" }) do
		local Parts = {}
		for i, C in ipairs(ICONS[K]) do Parts[#Parts + 1] = i .. " " .. ChatIcon(C) end
		Say(K .. ": " .. table.concat(Parts, "   "))
	end
	Say("pick with /af icon vendor 2 or /af icon auction 3 (a blank number means that art isn't in this game).")
end

-- /af keep [item link]: add or remove an item from the keep list; /af keep alone lists it.
function B.KeepCommand(Msg)
	local List = KeepList()
	local ID = tonumber(string.match(Msg or "", "item:(%d+)") or string.match(Msg or "", "^%s*keep%s+(%d+)%s*$") or "")
	if not ID then
		local Names = {}
		for K in pairs(List) do Names[#Names + 1] = AF.UI.ItemName(K) or ("item " .. K) end
		table.sort(Names)
		Say("kept (no bag icon, never junk): " .. (#Names > 0 and table.concat(Names, ", ") or "nothing yet") .. ". Add or remove one with /af keep and Shift-click the item.")
		return
	end
	local Name = AF.UI.ItemName(ID) or ("item " .. ID)
	if List[ID] then
		List[ID] = nil
		Say(Name .. " can be marked for selling again.")
	else
		List[ID] = true
		Say(Name .. " will never be marked for selling.")
	end
	B.Reset()
end

local SetUp = false
function B.SetUp()
	local Bag = rawget(_G, "Baganator")
	if SetUp or not (Bag and Bag.API and Bag.API.RegisterCornerWidget) then return false end
	SetUp = true
	local function NewIcon(ItemButton)
		Buttons[ItemButton] = true
		SkinJunk(ItemButton)
		local Icon = ItemButton:CreateTexture(nil, "OVERLAY")
		Icon:SetSize(15, 15)
		return Icon
	end
	Bag.API.RegisterCornerWidget("AuctionForever", WIDGET_ID, function(Icon, Details) return B.UpdateIcon(Icon, Details, "Auction") end,
		NewIcon, { corner = "top_right", priority = 1 })
	Bag.API.RegisterCornerWidget("AuctionForever: vendor", VENDOR_WIDGET_ID, function(Icon, Details) return B.UpdateIcon(Icon, Details, "Vendor") end,
		NewIcon, { corner = "top_left", priority = 1 })
	if Bag.API.RegisterJunkPlugin then Bag.API.RegisterJunkPlugin("AuctionForever", JUNK_ID, B.IsJunk) end
	-- New auction data (a scan finished): redraw. Scan calls AF.UI.ScanDone by name, so wrapping it is enough.
	local ScanDone = AF.UI.ScanDone
	AF.UI.ScanDone = function(...)
		if ScanDone then ScanDone(...) end
		B.Reset()
	end
	return true
end

local LoggedIn = false
local Events = CreateFrame("Frame")
Events:RegisterEvent("PLAYER_LOGIN")
Events:RegisterEvent("ADDON_LOADED")
Events:RegisterEvent("AUCTION_HOUSE_CLOSED")
Events:SetScript("OnEvent", function(_, Event, Name)
	if Event == "PLAYER_LOGIN" then
		LoggedIn = true
		B.SetUp()
	elseif Event == "ADDON_LOADED" then
		if Name == "Baganator" and LoggedIn then B.SetUp() end -- loaded after login
	elseif Event == "AUCTION_HOUSE_CLOSED" then
		if SetUp then B.Reset() end -- your own listings may have changed
	end
end)
