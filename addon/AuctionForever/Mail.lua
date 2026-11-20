-- Reads your auction mail while the mailbox is open: "Auction successful" invoices (item, amount, price) and
-- "Auction expired" mail. Each is recorded once in AuctionForeverDB.mysales = { { time, itemID, qty, total, kind } }.
-- Only reads; never takes money or items.
local _, AF = ...
local M = {}
AF.Mail = M

local KEEP_DAYS = 30

local function Pattern(Fmt)
	if type(Fmt) ~= "string" then return nil end
	local P = Fmt:gsub("([%(%)%.%+%-%*%?%[%]%^%$])", "%%%1"):gsub("%%s", "(.+)")
	return "^" .. P .. "$"
end

-- Item name -> itemID: names you've seen, names shipped with the cloud data, then the client's own cache.
local function IdFromName(Name)
	if not Name then return nil end
	local DB = AuctionForeverDB
	if type(DB) == "table" and type(DB.names) == "table" then
		for id, N in pairs(DB.names) do if N[1] == Name then return id end end
	end
	local D = AuctionForeverData
	if type(D) == "table" and type(D.names) == "table" then
		for id, N in pairs(D.names) do if N == Name then return id end end
	end
	local id = C_Item and C_Item.GetItemInfoInstant and C_Item.GetItemInfoInstant(Name)
	return type(id) == "number" and id or nil
end
M.IdFromName = IdFromName

-- A mail's key that stays the same between visits: subject, amount and when it runs out (rounded to 5 min). For a
-- sale the amount is the invoice's sale price, not the mail's money: that drops to 0 once you take the gold, which
-- used to record the sale a second time.
local function Key(Subject, Money, Expires)
	return string.format("%s|%d|%d", Subject, Money or 0, math.floor(Expires / 300 + 0.5))
end

function M.Read()
	if not (GetInboxNumItems and GetInboxHeaderInfo) then return 0 end
	AuctionForeverDB = AuctionForeverDB or {}
	local DB = AuctionForeverDB
	DB.mysales = DB.mysales or {}
	DB.mailseen = DB.mailseen or {}
	local Now = time()
	local SoldP, ExpP = Pattern(AUCTION_SOLD_MAIL_SUBJECT), Pattern(AUCTION_EXPIRED_MAIL_SUBJECT)
	local Added = 0
	for i = 1, (GetInboxNumItems()) or 0 do
		local _, _, _, Subject, Money, _, DaysLeft = GetInboxHeaderInfo(i)
		if Subject and DaysLeft then
			local Expires = Now + DaysLeft * 86400
			local Amount = Money
			if SoldP and Subject:match(SoldP) and GetInboxInvoiceInfo then
				local _, _, _, Bid = GetInboxInvoiceInfo(i)
				Amount = Bid or Money
			end
			local K = Key(Subject, Amount, Expires)
			local KB, KA = Key(Subject, Amount, Expires - 300), Key(Subject, Amount, Expires + 300)
			if not (DB.mailseen[K] or DB.mailseen[KB] or DB.mailseen[KA]) then
				local Row
				if SoldP and Subject:match(SoldP) and GetInboxInvoiceInfo then
					local Kind, ItemName, _, Bid, _, _, _, _, _, _, Count = GetInboxInvoiceInfo(i)
					local id = Kind == "seller" and IdFromName(ItemName or Subject:match(SoldP))
					if id then Row = { Now, id, Count or 1, Bid or Money or 0, "sold" } end
				elseif ExpP and Subject:match(ExpP) and GetInboxItem then
					local _, id, _, Count = GetInboxItem(i, 1)
					if type(id) == "number" then Row = { Now, id, Count or 1, 0, "expired" } end
				end
				if Row then
					DB.mysales[#DB.mysales + 1] = Row
					DB.mailseen[K] = Expires
					Added = Added + 1
				end
			end
		end
	end
	-- Forget old results and old mail keys. Once: drop sales recorded twice by the old key (the same sale read again
	-- seconds later, after its gold was taken; sales read together share the same time, so they're kept).
	local Kept = {}
	for _, R in ipairs(DB.mysales) do
		local Dup = false
		if not DB.mailfix1 and R[5] == "sold" then
			for _, P in ipairs(Kept) do
				if P[5] == "sold" and P[2] == R[2] and P[3] == R[3] and P[4] == R[4] and R[1] > P[1] and R[1] - P[1] <= 60 then Dup = true break end
			end
		end
		if not Dup and R[1] >= Now - KEEP_DAYS * 86400 then Kept[#Kept + 1] = R end
	end
	DB.mailfix1 = true
	DB.mysales = Kept
	for K, Expires in pairs(DB.mailseen) do if Expires < Now then DB.mailseen[K] = nil end end
	return Added
end

local Events = CreateFrame("Frame")
Events:RegisterEvent("MAIL_SHOW")
Events:RegisterEvent("MAIL_INBOX_UPDATE")
Events:SetScript("OnEvent", function() M.Read() end)
