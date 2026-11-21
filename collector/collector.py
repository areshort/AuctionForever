"""AuctionForever collector: fetch house 110 (WoW Forever, PvP Alliance) every hour, compare with the previous
hour, keep a compact history, and write the add-on's data file.

State (kept between runs, about a few MB):
  state.json.gz  - previous listings (id -> [item, unit price, quantity, time-left bucket]),
                   hourly rows per item for 72 h, daily rows per item for 14 days.
Output:
  AuctionForeverData.lua - a Lua table the add-on loads at login / reload.

Blizzard credentials come from the BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET environment variables and are
never printed or written anywhere.
"""
import base64, gzip, json, math, os, statistics, sys, time, urllib.request, urllib.error

REGION = 'us'
RULESET = 1          # the API returns the same houses for every ruleset
HOUSE = 110          # PvP Alliance, matched against the user's in-game listings 2026-11-19
FMT = 3          # data format; 2 = only compared hours count as hours of sales; 3 = random-suffix gear in its own table
HISTV = 3        # history version; 2 = cancels aren't sales; 3 = random-suffix versions kept apart. Older history
                 # (counted the old way) is dropped once.
HOURS_KEPT = 72
DAYS_KEPT = 14
BUCKET_ORDER = {'SHORT': 0, 'MEDIUM': 1, 'LONG': 2, 'VERY_LONG': 3}
# Upper end of each time-left bucket in hours (Forever strings: <30 min, 30 min-2 h, 2-12 h, >12 h).
BUCKET_MAX_H = {0: 0.5, 1: 2, 2: 12, 3: 24}


# --- fetching -------------------------------------------------------------------------------------------------
def _token():
    cid, sec = os.environ.get('BLIZZARD_CLIENT_ID'), os.environ.get('BLIZZARD_CLIENT_SECRET')
    if not cid or not sec:
        sys.exit('BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET are not set')
    pair = base64.b64encode(f'{cid}:{sec}'.encode()).decode()
    req = urllib.request.Request('https://oauth.battle.net/token', data=b'grant_type=client_credentials',
                                 headers={'Authorization': 'Basic ' + pair,
                                          'Content-Type': 'application/x-www-form-urlencoded'})
    return json.load(urllib.request.urlopen(req, timeout=60))['access_token']


def _get(path, tok, tries=3):
    url = f'https://{REGION}.api.blizzard.com{path}?namespace=dynamic-forever-{REGION}'
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok})
            return json.load(urllib.request.urlopen(req, timeout=180))
        except (urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


NAMES_PER_RUN = 4000  # items looked up per run at most (the first run fills most; the rest follow next run)
QUALITY = {'POOR': 0, 'COMMON': 1, 'UNCOMMON': 2, 'RARE': 3, 'EPIC': 4, 'LEGENDARY': 5, 'ARTIFACT': 6, 'HEIRLOOM': 7}


def fetch_names(ids, tok=None):
    """Item details from the static game data, {id: [name, vendor price, quality]}; unknown items get ["", 0, 1]."""
    from concurrent.futures import ThreadPoolExecutor
    tok = tok or _token()

    def one(i):
        url = f'https://{REGION}.api.blizzard.com/data/wow/item/{i}?namespace=static-forever-{REGION}&locale=en_US'
        for t in range(3):
            try:
                req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok})
                d = json.load(urllib.request.urlopen(req, timeout=30))
                return i, [d.get('name') or '', int(d.get('sell_price') or 0), QUALITY.get((d.get('quality') or {}).get('type'), 1)]
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return i, ['', 0, 1]
                time.sleep(2 * (t + 1))  # 429 / 5xx: wait and retry
            except (urllib.error.URLError, TimeoutError):
                time.sleep(2 * (t + 1))
        return i, None  # still failing: try again next run

    with ThreadPoolExecutor(max_workers=16) as pool:
        return {i: n for i, n in pool.map(one, ids) if n is not None}


def update_names(state, mk, names_fn):
    """Add name, vendor price and quality for listed items that don't have them yet. Returns how many were added."""
    names = state.setdefault('names', {})
    details = state.setdefault('details', {})
    missing = sorted({str(key_parts(i)[0]) for i in mk} - set(details), key=int)[:NAMES_PER_RUN]
    if not missing or not names_fn:
        return 0
    got = names_fn([int(k) for k in missing])
    for i, d in got.items():
        if isinstance(d, str):
            d = [d, 0, 1]
        names[str(i)] = d[0]
        details[str(i)] = [d[1], d[2]]
    return len(got)


def fetch():
    tok = _token()
    items = _get(f'/data/wow/ruleset/{RULESET}/auctions/{HOUSE}', tok).get('auctions') or []
    goods = _get(f'/data/wow/ruleset/{RULESET}/auctions/{HOUSE}/commodities', tok).get('auctions') or []
    return items, goods


# --- turning a snapshot into listings -------------------------------------------------------------------------
# Random-suffix gear ("of the Bear", "of the Whale"...): Forever's auctions carry the suffix as the item's bonus list
# (item.bonus_lists, one id such as 12719 = "of the Whale" in ItemBonus / ItemNameDescription; no "rand" field).
# Each version is its own market, so a suffixed item is keyed "itemID:bonus" (a string); items without a bonus list
# keep the plain item ID (an int).
def item_key(it):
    """The market key of an auction's item: its ID, or "ID:bonus" for a random-suffix version."""
    b = it.get('bonus_lists') or []
    return f"{it['id']}:{':'.join(str(x) for x in sorted(b))}" if b else it['id']


def key_parts(k):
    """(item ID, bonus or None) from a key (int, "123" or "123:12719")."""
    s = str(k)
    if ':' in s:
        a, b = s.split(':', 1)
        return int(a), b
    return int(s), None


def listings(items, goods):
    """id -> [item key, unit price (copper), quantity, bucket, kind] ; kind 'c' commodity, 'i' item."""
    out = {}
    for a in goods:
        out[str(a['id'])] = [a['item']['id'], a['unit_price'], a['quantity'], BUCKET_ORDER.get(a['time_left'], 3), 'c']
    for a in items:
        if not a.get('buyout'):
            continue  # bid-only: no price a buyer can just pay
        q = max(1, a['quantity'])
        out[str(a['id'])] = [item_key(a['item']), a['buyout'] // q, q, BUCKET_ORDER.get(a['time_left'], 3), 'i']
    return out


def new_cutoff(levels):
    """Highest price a new listing can have and still land in front of sellers at the cheap end: the price where the
    cheapest 25% of the item's stock is reached, but at least 10% over the lowest price. Listings posted far above
    the market don't compete with anyone selling near the bottom, so they don't count as new competition."""
    levels = sorted(levels)
    if not levels:
        return None
    total = sum(q for _, q in levels)
    run, p25 = 0, levels[-1][0]
    for p, q in levels:
        run += q
        if run * 4 >= total:
            p25 = p
            break
    return max(p25, int(levels[0][0] * 1.1))


def compare(prev, now, hours):
    """What happened to each previous listing. Returns item -> {'sold': [(price, qty)...], 'expired': qty,
    'cancel': [(price, qty)...], 'new': qty}.

    - gone, and its time-left bucket could not have run out in `hours`: sold, if nothing cheaper of the same item
      from before is still there untouched (buyers take the cheapest first); otherwise cancelled
    - gone from the last bucket that could run out: expired
    - same listing, smaller quantity (commodities): the difference sold
    - gone and a new listing with the same price and quantity appeared: a repost (cancel and post again), nothing
    - a listing that wasn't there before: newly posted ('new' quantity), counted only at the cheap end of the market
      (see new_cutoff) and not when it reposts a cancelled quantity at the same price
    """
    ev = {}
    # Cheapest earlier listing of each item that's still there with the same quantity.
    intact_min = {}
    for lid, (item, price, qty, bucket, kind) in prev.items():
        cur = now.get(lid)
        if cur is not None and cur[2] == qty and (item not in intact_min or price < intact_min[item]):
            intact_min[item] = price
    new, levels = {}, {}
    for lid, (item, price, qty, bucket, kind) in now.items():
        levels.setdefault(item, []).append((price, qty))
        if lid not in prev:
            new.setdefault(item, []).append([price, qty])
    for lid, (item, price, qty, bucket, kind) in prev.items():
        cur = now.get(lid)
        e = ev.setdefault(item, {'sold': [], 'expired': 0, 'cancel': []})
        if cur is None:
            same = next((n for n in new.get(item, []) if n[0] == price and n[1] == qty), None)
            if same is not None:
                new[item].remove(same)  # reposted as it was: nothing happened
                continue
            # Share of this listing that ran out of time rather than sold, from its time-left bucket: the time left is
            # taken as spread evenly over the bucket. Short (<30 min) can't be told apart: counted as expired.
            lo, hi = {0: (0, 0.5), 1: (0.5, 2), 2: (2, 12), 3: (12, 24)}[bucket]
            expired_share = 1.0 if bucket == 0 else min(1.0, max(0.0, (hours - lo) / (hi - lo)))
            e['expired'] += qty * expired_share
            if expired_share < 1:
                gone = qty * (1 - expired_share)
                if item in intact_min and price > intact_min[item]:
                    e['cancel'].append((price, gone))
                else:
                    e['sold'].append((price, gone))
        elif cur[2] < qty:
            e['sold'].append((price, qty - cur[2]))
    for item, lst in new.items():
        e = ev.setdefault(item, {'sold': [], 'expired': 0, 'cancel': []})
        cancelled = {}
        for p, q in e['cancel']:
            cancelled[p] = cancelled.get(p, 0) + q
        cut = new_cutoff(levels.get(item, []))
        n = 0
        for p, q in lst:
            m = min(q, cancelled.get(p, 0))  # a cancelled quantity posted again at the same price: not new
            cancelled[p] = cancelled.get(p, 0) - m
            if p <= cut:
                n += q - m
        if n > 0:
            e['new'] = n
    return {k: v for k, v in ev.items() if v['sold'] or v['expired'] or v.get('new') or v['cancel']}


def market(now):
    """item -> lowest price, quantity listed, number of listings, sorted [(price, qty)] ladder (cheapest 40 prices)."""
    by = {}
    for item, price, qty, bucket, kind in now.values():
        d = by.setdefault(item, {})
        d[price] = d.get(price, 0) + qty
    out = {}
    for item, ladder in by.items():
        steps = sorted(ladder.items())
        out[item] = {'low': steps[0][0], 'qty': sum(q for _, q in steps), 'n': len(steps), 'ladder': steps[:40]}
    return out


# --- history and numbers ----------------------------------------------------------------------------------------
def wmedian(pairs):
    """Median of (value, weight) pairs."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    run = 0
    for v, w in pairs:
        run += w
        if run * 2 >= total:
            return v
    return pairs[-1][0]


def update_history(state, now_ts, mk, ev, span=0):
    # span = hours since the previous snapshot when the two were compared, else 0 (first run or a long gap).
    hourly = state.setdefault('hourly', {})   # item -> [[ts, low, qty, sold_qty, sold_value, expired, span, new_qty], ...]
    daily = state.setdefault('daily', {})     # item -> [[day, median_sold, sold_qty, expired], ...]
    soldprices = state.setdefault('soldprices', {})  # item -> [[ts, price, qty], ...] for 72 h
    for item in set(mk) | set(ev):
        m, e = mk.get(item), ev.get(item, {'sold': [], 'expired': 0})
        sq = sum(q for _, q in e['sold'])
        sv = sum(p * q for p, q in e['sold'])
        k = str(item)
        hourly.setdefault(k, []).append([now_ts, m['low'] if m else None, m['qty'] if m else 0, sq, sv, e['expired'], span,
                                         e.get('new', 0)])
        if e['sold']:
            soldprices.setdefault(k, []).extend([now_ts, p, q] for p, q in e['sold'])
    # Daily summaries for every day that finished since the last run, before old hourly rows are dropped.
    day = int(now_ts // 86400)
    last = state.get('lastDay')
    if last is not None and last < day:
        for d in range(max(last, day - DAYS_KEPT), day):
            for k in set(soldprices) | set(hourly):
                sold = [(p, q) for t, p, q in soldprices.get(k, []) if int(t // 86400) == d]
                exp = sum(r[5] for r in hourly.get(k, []) if int(r[0] // 86400) == d)
                if sold or exp:
                    daily.setdefault(k, []).append([d, wmedian(sold) if sold else None, sum(q for _, q in sold), exp])
        for k in list(daily):
            daily[k] = [r for r in daily[k] if r[0] > day - DAYS_KEPT]
            if not daily[k]:
                del daily[k]
    state['lastDay'] = day
    cut = now_ts - HOURS_KEPT * 3600
    for store in (hourly, soldprices):
        for k in list(store):
            store[k] = [r for r in store[k] if r[0] >= cut]
            if not store[k]:
                del store[k]


def item_numbers(k, state, mk, now_ts):
    """The numbers the add-on needs for one item."""
    all_rows = state['hourly'].get(k, [])
    rows = [r for r in all_rows if len(r) > 6 and r[6] > 0]  # only hours that were compared with the one before
    sp = state['soldprices'].get(k, [])
    span_total = sum(r[6] for r in rows)
    hours = span_total if span_total > 0 else 1.0
    sold_by_hour = [r[3] / r[6] for r in rows]
    recent = [(p, q * (2 if now_ts - t <= 86400 else 1)) for t, p, q in sp]  # last 24 h counts double
    med = wmedian(recent) if recent else None
    hi = None
    if sp:
        # Upper range of what buyers paid, leaving out prices over twice the median (a mistake or a cancel at a silly
        # price would otherwise set the ceiling).
        m_all = wmedian([(p, q) for _, p, q in sp])
        prices = sorted(p for _, p, q in sp if p <= 2 * m_all for _ in range(max(1, min(int(round(q)), 50))))
        hi = prices[min(len(prices) - 1, int(len(prices) * 0.75))] if prices else m_all
    sold_total = sum(r[3] for r in rows)  # quantities (perHour = sold / hours watched)
    exp_total = sum(r[5] for r in rows)
    sales = len(sp)
    med_hour = statistics.median(sold_by_hour) if sold_by_hour else 0
    hours_with_sales = sum(1 for s in sold_by_hour if s > 0)
    m = mk.get(int(k)) if ':' not in k else mk.get(k)
    # trend: last 24 h median sold vs the whole window
    last24 = [(p, q) for t, p, q in sp if now_ts - t <= 86400]
    med24 = wmedian(last24) if last24 else None
    med_all = wmedian([(p, q) for t, p, q in sp]) if sp else None
    qty_now = m['qty'] if m else 0
    qty_24h_ago = [r[2] for r in all_rows if 23 * 3600 <= now_ts - r[0] <= 25 * 3600]
    # New listings per hour (other sellers posting): the average, so a busy posting hour isn't hidden.
    new_rows = [r for r in rows if len(r) > 7]
    new_hour = sum(r[7] for r in new_rows) / sum(r[6] for r in new_rows) if new_rows else None
    # Lowest price over time: the last three snapshots (falling-price check), and the highest lowest price over the
    # last 24 h when a day was watched (has the market stayed under a price all day?).
    lows = [r[1] for r in all_rows if r[1] is not None][-3:]
    day_rows = [r for r in all_rows if now_ts - r[0] <= 86400 and r[1] is not None]
    low_hi24 = max(r[1] for r in day_rows) if len(day_rows) >= 20 else None
    # The lowest price's range over the last 24 h (12+ hours watched): its 10th, 50th and 90th percentile. The
    # add-on flips volatile items (wide range: crates swing 5x in a day) only near the bottom of it, and resells
    # them at no more than the middle. Percentiles, not min/max: one stray cheap listing would set the minimum.
    low_range24 = None
    if len(day_rows) >= 12:
        ds = sorted(r[1] for r in day_rows)
        low_range24 = [ds[int(q * (len(ds) - 1) + 0.5)] for q in (0.1, 0.5, 0.9)]
    return {
        'low': m['low'] if m else None,
        'qty': qty_now,
        'ladder': m['ladder'] if m else [],
        'med': med, 'hi': hi, 'med24': med24, 'medAll': med_all,
        'perHour': sold_total / hours, 'medHour': med_hour,
        'hoursSeen': len(rows), 'hoursWithSales': hours_with_sales,
        'sales': sales, 'sellThrough': (sold_total / (sold_total + exp_total)) if (sold_total + exp_total) else None,
        'qtyDayAgo': qty_24h_ago[0] if qty_24h_ago else None,
        'newHour': new_hour,
        'lows': lows, 'lowHi24': low_hi24, 'lowRange24': low_range24,
        'daily': state['daily'].get(k, []),
    }


# --- writing the Lua data file ----------------------------------------------------------------------------------
def lua(v):
    if v is None:
        return 'nil'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, float):
        return ('%.4f' % v).rstrip('0').rstrip('.') if math.isfinite(v) else 'nil'
    if isinstance(v, str):
        return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return '{' + ','.join(lua(x) for x in v) + '}'
    if isinstance(v, dict):
        return '{' + ','.join(f'{k}={lua(x)}' if isinstance(k, str) and k.isidentifier() else f'[{lua(k)}]={lua(x)}'
                              for k, x in v.items()) + '}'
    raise TypeError(type(v))


SFX_CHUNK = 400  # suffix items per chunk of the data file (see write_lua)
FIELDS = ['low', 'qty', 'med', 'hi', 'med24', 'medAll', 'perHour', 'medHour', 'hoursSeen', 'hoursWithSales', 'sales',
          'sellThrough', 'qtyDayAgo', 'newHour', 'lows', 'lowHi24', 'lowRange24']


def write_lua(path, state, mk, now_ts):
    keys = set(state['hourly']) | {str(i) for i in mk}
    parts, names, info, sfx = [], [], [], {}
    have = state.get('names', {})
    det = state.get('details', {})
    # Commodities come from Blizzard's separate commodities list (stackable goods sold by quantity).
    goods = {str(v[0]) for v in (state.get('listings') or {}).values() if v[4] == 'c'}
    ids = set()

    def order(k):
        i, b = key_parts(k)
        return (i, b or '')
    for k in sorted(keys, key=order):
        n = item_numbers(k, state, mk, now_ts)
        if not n['low'] and not n['sales']:
            continue
        row = [n[f] for f in FIELDS] + [n['ladder'][:12]]
        i, b = key_parts(k)
        if b is None:
            parts.append(f'[{i}]={lua(row)}')
        else:
            sfx.setdefault(i, []).append(f'[{lua(int(b) if b.isdigit() else b)}]={lua(row)}')
        if i in ids:
            continue
        ids.add(i)
        if have.get(str(i)):
            names.append(f'[{i}]={lua(have[str(i)])}')
        d = det.get(str(i)) or [None, None]
        info.append(f'[{i}]={lua([d[0], d[1], 1 if str(i) in goods else 0])}')
    # The suffix rows are added after the main table, in chunks each inside its own function: Lua limits the
    # constants one function may hold (65,536 in LuaJIT), and one big table literal would pass it.
    sfx_rows = [f'S[{i}]={{' + ','.join(r) + '}' for i, r in sorted(sfx.items())]
    chunks = [sfx_rows[i:i + SFX_CHUNK] for i in range(0, len(sfx_rows), SFX_CHUNK)]
    sfx_code = ''.join(';(function() local S = AuctionForeverData.sfx\n' + '\n'.join(c) + '\nend)()\n' for c in chunks)
    body = (f'-- Written by the AuctionForever collector. Do not edit.\n'
            f'AuctionForeverData = {{v=1,house={HOUSE},time={int(now_ts)},hours={round(sum(c[1] for c in state.get("compared", [])), 1)},\n'
            f'fields={lua(FIELDS + ["ladder"])},\nitems={{\n' + ',\n'.join(parts) + '\n},\n'
            'names={\n' + ',\n'.join(names) + '\n},\n'
            '-- [itemID] = {vendor price, quality, commodity (1) or not (0)}\n'
            'info={\n' + ',\n'.join(info) + '\n},\n'
            '-- Random-suffix gear: sfx[itemID] = { [bonus list] = row like items }. Each suffix is its own market; items{}\n'
            '-- has only the listings without a suffix. Filled below, in chunks.\n'
            'sfx={}}\n' + sfx_code)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(body)
    os.replace(tmp, path)
    return len(parts)


# --- state ------------------------------------------------------------------------------------------------------
def load_state(path):
    if os.path.exists(path):
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_state(path, state):
    tmp = path + '.tmp'
    with gzip.open(tmp, 'wt', encoding='utf-8', compresslevel=9) as f:
        json.dump(state, f, separators=(',', ':'))
    os.replace(tmp, path)


def run(state_path, out_path, items=None, goods=None, now_ts=None, names_fn=None):
    now_ts = now_ts or time.time()
    if items is None:
        items, goods = fetch()
        names_fn = names_fn or fetch_names
    state = load_state(state_path)
    reset = state.get('histv') != HISTV
    if reset:
        # History counted under older rules is dropped once; listings and timing are kept so the next comparison counts.
        for k in ('hourly', 'soldprices', 'daily', 'compared', 'lastDay'):
            state.pop(k, None)
        state['histv'] = HISTV
    for k in ('hourly', 'soldprices', 'daily'):
        state.setdefault(k, {})  # may be missing after a reset (or a reset saved by an older run)
    now = listings(items, goods)
    prev = state.get('listings')
    if prev is not None and prev == now:
        # Blizzard hasn't published a new snapshot yet: change nothing, so this isn't counted as an hour of no sales.
        added = update_names(state, market(now), names_fn)
        if state.get('fmt') != FMT or added or reset:
            # ...but a data file written by an older collector is rewritten right away in the current format.
            state['fmt'] = FMT
            save_state(state_path, state)
            n = write_lua(out_path, state, market(now), state['time'])
            print(f'house {HOUSE}: no new snapshot yet; data file rewritten ({n} items, {added} new names)')
            return True
        print(f'house {HOUSE}: no new snapshot yet ({len(now)} listings unchanged)')
        return False
    hours = (now_ts - state['time']) / 3600 if state.get('time') else None
    # We only know when a snapshot was first seen. That's close to when Blizzard made it for every snapshot caught
    # by the 20-minute polling, but not for the very first one (it may have been up for an hour), so a comparison
    # starting from the first snapshot isn't counted: its sales rate could be several times too high.
    timed = state.get('timed', False)
    if not (prev and hours and hours < 6 and timed):
        hours_for_rate = None
    else:
        hours_for_rate = hours
    if hours_for_rate and reset:
        # After a history reset the previous item auctions may be keyed the old way (suffix versions under the plain
        # ID): only commodities are compared this once, or every suffixed listing would look sold and posted again.
        ev = compare({k: v for k, v in prev.items() if v[4] == 'c'}, {k: v for k, v in now.items() if v[4] == 'c'}, hours_for_rate)
    else:
        ev = compare(prev, now, hours_for_rate) if hours_for_rate else {}
    mk = market(now)
    added = update_names(state, mk, names_fn)
    span = hours_for_rate or 0
    update_history(state, now_ts, mk, ev, span)
    # Hours of sales watched in the kept window, shown by the add-on as "based on N h of sales".
    state['compared'] = [c for c in state.get('compared', []) if c[0] >= now_ts - HOURS_KEPT * 3600] + ([[now_ts, span]] if span else [])
    state['listings'] = now
    state['time'] = now_ts
    state['runs'] = state.get('runs', 0) + 1
    state['fmt'] = FMT
    # From now on snapshot times are accurate when the polling keeps going (a long gap starts over).
    state['timed'] = bool(prev) and hours is not None and hours < 3
    save_state(state_path, state)
    n = write_lua(out_path, state, mk, now_ts)
    print(f'house {HOUSE}: {len(now)} listings, {len(ev)} items changed, {n} items written, {added} new names')
    return True


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else '.'
    changed = run(os.path.join(d, 'state.json.gz'), os.path.join(d, 'AuctionForeverData.lua'))
    # Tell the workflow whether there's anything new to upload.
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            print('changed=' + ('true' if changed else 'false'), file=f)
