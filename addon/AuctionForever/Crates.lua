-- AuctionForever: Merchant's Favor per Waylaid Crate. Hand-kept: the game data doesn't have it (it's a server-side quest
-- reward). Correct a line after you hand in a crate: put the Favor you got, change "reported" / "expected" to
-- "confirmed", and put the money the hand-in paid (copper; 0 when none) as the third value.
--   "reported": from player reports (outof.games, read 23 Nov 2026; Blizzard doesn't publish these)
--   "expected": not confirmed by anyone yet (outof.games' guess for the Artisan tier)
-- What fills each crate comes from the game data (AF_CrateFills in Recipes.lua). A crate's fair value is
-- Favor x your Favor price (/af favor) + the money back - the cheapest bundle that fills it, bought on the AH.
-- Not counted: the first hand-in's one-time 50 Favor bonus, and the chance of +100% Favor (spell 1225456, a perk).
AF_CrateFavor = {
	[248682] = { 5, "reported", 0 },   -- Apprentice Herbs
	[248683] = { 5, "reported", 0 },   -- Apprentice Ore
	[248684] = { 5, "reported", 0 },   -- Apprentice Textiles
	[248685] = { 5, "reported", 0 },   -- Apprentice Curiosities
	[248702] = { 10, "reported", 0 },  -- Apprentice Fabrics
	[248703] = { 10, "reported", 0 },  -- Apprentice Ingots
	[248704] = { 10, "reported", 0 },  -- Apprentice Parts
	[248686] = { 10, "reported", 0 },  -- Journeyman Herbs
	[248687] = { 10, "reported", 0 },  -- Journeyman Ore
	[248688] = { 10, "reported", 0 },  -- Journeyman Textiles
	[248689] = { 10, "reported", 0 },  -- Journeyman Curiosities
	[248705] = { 20, "reported", 0 },  -- Journeyman Fabrics
	[248706] = { 20, "reported", 0 },  -- Journeyman Ingots
	[248707] = { 20, "reported", 0 },  -- Journeyman Parts
	[248690] = { 15, "reported", 0 },  -- Earthly Expert Herbs
	[248691] = { 15, "reported", 0 },  -- Flowering Expert Herbs
	[248692] = { 15, "reported", 0 },  -- Expert Ore
	[248693] = { 15, "reported", 0 },  -- Expert Textiles
	[248694] = { 15, "reported", 0 },  -- Expert Curiosities
	[248708] = { 30, "reported", 0 },  -- Expert Fabrics
	[248709] = { 30, "reported", 0 },  -- Expert Ingots
	[248710] = { 30, "reported", 0 },  -- Expert Parts
	[248695] = { 20, "expected", 0 },  -- Earthly Artisan Herbs
	[248696] = { 20, "expected", 0 },  -- Flowering Artisan Herbs
	[248697] = { 20, "expected", 0 },  -- Artisan Ore
	[248698] = { 20, "expected", 0 },  -- Artisan Textiles
	[248699] = { 20, "expected", 0 },  -- Artisan Curiosities
	[248711] = { 40, "expected", 0 },  -- Artisan Fabrics
	[248712] = { 40, "expected", 0 },  -- Artisan Ingots
	[248713] = { 40, "expected", 0 },  -- Artisan Parts
}
