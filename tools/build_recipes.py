"""Build addon/AuctionForever/Recipes.lua: every WoW Forever craft that makes a sellable item.

Source: WoW Forever (wago.tools product "wowf") DB2 tables exported as CSV, named <Table>_<build>.csv:
  SkillLineAbility  recipe spell -> profession, required skill, yellow/grey ranks, how it is learned
  SpellEffect       Effect 24 (CREATE_ITEM): product item and how many (EffectBasePointsF)
  SpellReagents     reagents and counts
  ItemSparse        names, bonding (BoP products can't be sold), vendor buy price
  Item              item class (9 = recipe/pattern items)
  ItemEffect + ItemXItemEffect   recipe items: TriggerType 6 = the spell the item teaches
  SpellName         spell names (to drop test/DNT spells)
  SpellCooldowns + SpellCategories   craft cooldowns (transmutes, Mooncloth...) and the shared cooldown category

Tool conversions: crafts that aren't profession recipes but a tool item's use (ItemEffect TriggerType 0), e.g. the
Salt Shaker (item 15846, spell 19566: Deeprock Salt -> Refined Deeprock Salt, 71 h cooldown). Taken when the tool
needs a profession skill (ItemSparse RequiredSkill / RequiredSkillRank) and the product is sellable; they're filed
under that profession, with the tool item in the teachItem slot. Without them such products looked gathered.
Download a table: https://wago.tools/db2/<Table>/csv?build=<build>  (Forever builds: wago.tools/api/builds, key "wowf").

Vendor-sold reagents are not in the client data (vendor lists are server side). They come from a hand-made list of
item IDs below (thread, vials, flux, dyes, spices, ...); their price is ItemSparse BuyPrice / VendorStackCount.

Usage: python -I build_recipes.py [--data DIR] [--build 1.60.1.NNNNN] [--out PATH] [--report]
"""
import argparse
import csv
import glob
import os
import re
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.join(os.path.dirname(REPO), 'data')
DEFAULT_OUT = os.path.join(REPO, 'addon', 'AuctionForever', 'Recipes.lua')

# Professions (and secondary skills) whose crafts make items. Rogue Poisons are kept: poisons are tradeable.
PROFESSIONS = {
    164: 'Blacksmithing', 165: 'Leatherworking', 171: 'Alchemy', 185: 'Cooking', 186: 'Mining',
    197: 'Tailoring', 202: 'Engineering', 333: 'Enchanting', 129: 'First Aid', 40: 'Poisons',
}

# Reagents sold by vendors (Classic-era vendor goods; Forever keeps these items). Checked against ItemSparse:
# an ID here that has no BuyPrice is dropped with a warning.
VENDOR_REAGENTS = [
    # thread
    2320, 2321, 4291, 8343, 14341,
    # dyes and bleach
    2324, 2325, 2604, 2605, 4340, 4341, 4342, 6260, 6261, 10290,
    # alchemy / poison vials and rogue poison reagents
    3371, 3372, 8925, 18256, 2928, 2930, 5173, 8923, 8924,
    # blacksmithing / mining
    2880, 3466, 3857, 18567,
    # leatherworking
    4289, 7005,
    # engineering
    4399, 4400, 10647, 10648, 6530,
    # enchanting
    4470, 6217, 11291,
    # cooking
    159, 1179, 2678, 2692, 3713, 2596, 4536, 17194, 17196,
]

BIND_ON_PICKUP, QUEST_ITEM = 1, 4


def read(data, table, build):
    path = os.path.join(data, f'{table}_{build}.csv')
    with open(path, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def latest_build(data):
    builds = set()
    for p in glob.glob(os.path.join(data, 'SpellReagents_1.60.1.*.csv')):
        m = re.search(r'_(1\.60\.1\.\d+)\.csv$', p)
        if m:
            builds.add(m.group(1))
    if not builds:
        sys.exit('no SpellReagents_1.60.1.*.csv in ' + data)
    return max(builds, key=lambda b: int(b.split('.')[-1]))


def build(data, ver):
    sla = read(data, 'SkillLineAbility', ver)
    effects = read(data, 'SpellEffect', ver)
    reagents = read(data, 'SpellReagents', ver)
    sparse = {int(r['ID']): r for r in read(data, 'ItemSparse', ver)}
    items = {int(r['ID']): r for r in read(data, 'Item', ver)}
    names = {int(r['ID']): r['Name_lang'] for r in read(data, 'SpellName', ver)}
    ieff = {int(r['ID']): r for r in read(data, 'ItemEffect', ver)}
    xeff = read(data, 'ItemXItemEffect', ver)
    cooldown = {}                                # spell -> seconds
    for r in read(data, 'SpellCooldowns', ver):
        ms = max(int(r['RecoveryTime']), int(r['CategoryRecoveryTime']))
        if ms > 0 and r['DifficultyID'] == '0':
            cooldown[int(r['SpellID'])] = ms // 1000
    category = {int(r['SpellID']): int(r['Category']) for r in read(data, 'SpellCategories', ver)
                if r['DifficultyID'] == '0' and int(r['Category']) > 0}

    creates = defaultdict(list)                  # spell -> [(item, count)]
    for e in effects:
        if e['Effect'] == '24' and int(e['EffectItemType']) > 0:
            n = max(1, round(float(e['EffectBasePointsF'] or 1)))
            creates[int(e['SpellID'])].append((int(e['EffectItemType']), n))
    regs = {}
    for r in reagents:
        sp = int(r['SpellID'])
        if sp in regs:
            continue
        lst = []
        for k in range(8):
            it, n = int(r[f'Reagent_{k}']), int(r[f'ReagentCount_{k}'])
            if it > 0 and n > 0:
                lst.append((it, n))
        regs[sp] = lst
    # recipe items: class 9, effect with TriggerType 6 teaches the spell
    teach = {}
    for x in xeff:
        e = ieff.get(int(x['ItemEffectID']))
        it = int(x['ItemID'])
        if e and e['TriggerType'] == '6' and items.get(it, {}).get('ClassID') == '9':
            sp = int(e['SpellID'])
            if sp not in teach or it < teach[sp]:
                teach[sp] = it

    recipes = defaultdict(list)                  # product -> rows
    seen = set()
    skipped = defaultdict(int)
    by_prof = defaultdict(int)
    for a in sla:
        line, sp = int(a['SkillLine']), int(a['Spell'])
        if line not in PROFESSIONS or sp in seen:
            continue
        seen.add(sp)
        nm = names.get(sp, '')
        # (OLD / UNUSED only as capital words: matched without case they dropped "Smelt Gold" and every "...Gold...")
        if not nm or re.search(r'DNT|\[PH\]|\btest\b|Deprecated', nm, re.I) or re.search(r'\b(OLD|UNUSED)\b', nm):
            skipped['test/unnamed spell'] += 1
            continue
        if sp not in creates:
            skipped['no item made (enchant/other)'] += 1
            continue
        if sp not in regs or not regs[sp]:
            skipped['no reagents'] += 1
            continue
        if len(creates[sp]) > 1:
            skipped['makes several items (kept first)'] += 1
        prod, n = creates[sp][0]
        ps = sparse.get(prod)
        if not ps:
            skipped['product not in ItemSparse'] += 1
            continue
        if int(ps['Bonding']) in (BIND_ON_PICKUP, QUEST_ITEM):
            skipped['product bind on pickup / quest'] += 1
            continue
        how = teach.get(sp, 0)
        # Required rank: the recipe item's RequiredSkillRank; trainer recipes don't have it in the client data
        # (MinSkillLineRank is 1 for almost all), so it is 0 = unknown there (the yellow rank is a close guide).
        req = int(sparse[how]['RequiredSkillRank']) if how and how in sparse else 0
        if not req and int(a['MinSkillLineRank']) > 1:
            req = int(a['MinSkillLineRank'])
        cd = cooldown.get(sp, 0)
        recipes[prod].append((sp, line, req, n, regs[sp], how,
                              int(a['TrivialSkillLineRankLow']), int(a['TrivialSkillLineRankHigh']),
                              cd, category.get(sp, 0) if cd else 0))
        by_prof[PROFESSIONS[line]] += 1

    vendor = {}
    warn = []
    for it in VENDOR_REAGENTS:
        s = sparse.get(it)
        if not s or int(s['BuyPrice']) <= 0:
            warn.append(f'vendor list item {it} has no BuyPrice in this build (dropped)')
            continue
        vendor[it] = max(1, round(int(s['BuyPrice']) / max(1, int(s['VendorStackCount'] or 1))))
    # Tool conversions (see the module notes): a tool's use spell that makes a sellable item from reagents, when
    # using the tool needs a profession skill.
    tools = 0
    for x in xeff:
        e = ieff.get(int(x['ItemEffectID']))
        it = int(x['ItemID'])
        t = sparse.get(it)
        if not e or e['TriggerType'] != '0' or not t:
            continue
        sp, line = int(e['SpellID']), int(t['RequiredSkill'] or 0)
        if line not in PROFESSIONS or sp in seen or sp not in creates or not regs.get(sp):
            continue
        if any(r == it for r, _ in regs[sp]):
            continue  # the item is used up making it (a one-time combine, e.g. a quest blade): not a tool
        prod, n = creates[sp][0]
        ps = sparse.get(prod)
        if not ps or int(ps['Bonding']) in (BIND_ON_PICKUP, QUEST_ITEM):
            continue
        seen.add(sp)
        cd = cooldown.get(sp, 0)
        recipes[prod].append((sp, line, int(t['RequiredSkillRank'] or 0), n, regs[sp], it, 0, 0,
                              cd, category.get(sp, 0) if cd else 0))
        by_prof[PROFESSIONS[line]] += 1
        tools += 1
    skipped['(added) tool conversions'] = tools
    used = {r for rows in recipes.values() for row in rows for r, _ in row[4]}
    info = dict(sparse=sparse, items=items, names=names, skipped=skipped, by_prof=by_prof, warn=warn, used=used)
    return recipes, vendor, info


def lua_list(vals):
    return '{' + ','.join(str(v) for v in vals) + '}'


def write_lua(out, ver, recipes, vendor):
    L = ['-- Generated by tools/build_recipes.py from WoW Forever game data (build %s). Do not edit.' % ver,
         '-- AF_Recipes[product] = { {spell, skillLine, skillReq, makes, {reagent, count, ...}, teachItem, yellow, grey}, ... }',
         '--   with cooldown recipes adding: cooldownSeconds, cooldownCategory (crafts in one category share the cooldown)',
         '-- skillReq = the recipe item required rank (0 = not in the client data: trainer recipes; yellow is a guide).',
         '-- teachItem = recipe/pattern item that teaches it (0 = trainer or learned automatically); for a tool conversion',
         '--   (a tool item\'s use, e.g. the Salt Shaker) the tool item. yellow/grey 0 = no ranks (a tool, not a recipe).',
         '-- AF_RecipeVendor[item] = vendor price per unit (copper) for reagents sold by vendors.',
         'AF_RecipeBuild = "%s"' % ver,
         'AF_RecipeSkills = {' + ','.join('[%d]="%s"' % (k, v) for k, v in sorted(PROFESSIONS.items())) + '}',
         'AF_RecipeVendor = {' + ','.join('[%d]=%d' % (k, v) for k, v in sorted(vendor.items())) + '}',
         'AF_Recipes = {']
    for prod in sorted(recipes):
        rows = []
        for sp, line, req, n, regs, how, yel, grey, cd, cat in sorted(recipes[prod]):
            flat = [x for r in regs for x in r]
            tail = ',%d,%d' % (cd, cat) if cd else ''
            rows.append('{%d,%d,%d,%d,%s,%d,%d,%d%s}' % (sp, line, req, n, lua_list(flat), how, yel, grey, tail))
        L.append('[%d]={%s},' % (prod, ','.join(rows)))
    L.append('}')
    with open(out, 'w', encoding='ascii', newline='\n') as f:
        f.write('\n'.join(L) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=DEFAULT_DATA)
    ap.add_argument('--build')
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--report', action='store_true', help='list reagents that may be vendor goods but are not marked')
    a = ap.parse_args()
    ver = a.build or latest_build(a.data)
    recipes, vendor, info = build(a.data, ver)
    write_lua(a.out, ver, recipes, vendor)
    n = sum(len(v) for v in recipes.values())
    print(f'build {ver}: {n} recipes, {len(recipes)} products, {len(vendor)} vendor reagents -> {a.out}')
    for k, v in sorted(info['by_prof'].items()):
        print(f'  {k}: {v}')
    for k, v in sorted(info['skipped'].items()):
        print(f'  skipped {k}: {v}')
    for w in info['warn']:
        print('  WARN ' + w)
    if a.report:
        pat = re.compile(r'thread|vial|flux|dye|bleach|spice|salt|stock|ink|parchment|wood|rod|water|milk|'
                         r'dust of|essence of|deathweed|coal|flour|seasoning|oil$', re.I)
        for it in sorted(info['used']):
            s = info['sparse'].get(it)
            nm = s['Display_lang'] if s else '?'
            if it not in vendor and pat.search(nm):
                print(f'  maybe vendor (not marked): {it} {nm} buy={s and s["BuyPrice"]}')


if __name__ == '__main__':
    main()
