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
FMT = 2          # data format; 2 = only compared hours count as hours of sales
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


def fetch():
    tok = _token()
    items = _get(f'/data/wow/ruleset/{RULESET}/auctions/{HOUSE}', tok).get('auctions') or []
    goods = _get(f'/data/wow/ruleset/{RULESET}/auctions/{HOUSE}/commodities', tok).get('auctions') or []
    return items, goods


# --- turning a snapshot into listings -------------------------------------------------------------------------
def listings(items, goods):
    """id -> [itemID, unit price (copper), quantity, bucket, kind] ; kind 'c' commodity, 'i' item."""
    out = {}
    for a in goods:
        out[str(a['id'])] = [a['item']['id'], a['unit_price'], a['quantity'], BUCKET_ORDER.get(a['time_left'], 3), 'c']
    for a in items:
        if not a.get('buyout'):
            continue  # bid-only: no price a buyer can just pay
        q = max(1, a['quantity'])
        out[str(a['id'])] = [a['item']['id'], a['buyout'] // q, q, BUCKET_ORDER.get(a['time_left'], 3), 'i']
    return out


def compare(prev, now, hours):
    """What happened to each previous listing. Returns item -> {'sold': [(price, qty)...], 'expired': qty}.

    - gone, and its time-left bucket could not have run out in `hours`: sold (or cancelled)
    - gone from the last bucket that could run out: expired
    - same listing, smaller quantity (commodities): the difference sold
    """
    ev = {}
    for lid, (item, price, qty, bucket, kind) in prev.items():
        cur = now.get(lid)
        e = ev.setdefault(item, {'sold': [], 'expired': 0})
        if cur is None:
            # Share of this listing that ran out of time rather than sold, from its time-left bucket: the time left is
            # taken as spread evenly over the bucket. Short (<30 min) can't be told apart: counted as expired.
            lo, hi = {0: (0, 0.5), 1: (0.5, 2), 2: (2, 12), 3: (12, 24)}[bucket]
            expired_share = 1.0 if bucket == 0 else min(1.0, max(0.0, (hours - lo) / (hi - lo)))
            e['expired'] += qty * expired_share
            if expired_share < 1:
                e['sold'].append((price, qty * (1 - expired_share)))
        elif cur[2] < qty:
            e['sold'].append((price, qty - cur[2]))
    return {k: v for k, v in ev.items() if v['sold'] or v['expired']}


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
    hourly = state.setdefault('hourly', {})   # item -> [[ts, low, qty, sold_qty, sold_value, expired, span], ...]
    daily = state.setdefault('daily', {})     # item -> [[day, median_sold, sold_qty, expired], ...]
    soldprices = state.setdefault('soldprices', {})  # item -> [[ts, price, qty], ...] for 72 h
    for item in set(mk) | set(ev):
        m, e = mk.get(item), ev.get(item, {'sold': [], 'expired': 0})
        sq = sum(q for _, q in e['sold'])
        sv = sum(p * q for p, q in e['sold'])
        k = str(item)
        hourly.setdefault(k, []).append([now_ts, m['low'] if m else None, m['qty'] if m else 0, sq, sv, e['expired'], span])
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
    hours = max(1.0, sum(r[6] for r in rows))
    sold_by_hour = [r[3] / r[6] for r in rows]
    recent = [(p, q * (2 if now_ts - t <= 86400 else 1)) for t, p, q in sp]  # last 24 h counts double
    med = wmedian(recent) if recent else None
    hi = None
    if sp:
        prices = sorted(p for _, p, q in sp for _ in range(max(1, min(int(round(q)), 50))))
        hi = prices[min(len(prices) - 1, int(len(prices) * 0.75))]
    sold_total = sum(sold_by_hour)
    exp_total = sum(r[5] for r in rows)
    sales = len(sp)
    med_hour = statistics.median(sold_by_hour) if sold_by_hour else 0
    hours_with_sales = sum(1 for s in sold_by_hour if s > 0)
    m = mk.get(int(k))
    # trend: last 24 h median sold vs the whole window
    last24 = [(p, q) for t, p, q in sp if now_ts - t <= 86400]
    med24 = wmedian(last24) if last24 else None
    med_all = wmedian([(p, q) for t, p, q in sp]) if sp else None
    qty_now = m['qty'] if m else 0
    qty_24h_ago = [r[2] for r in all_rows if 23 * 3600 <= now_ts - r[0] <= 25 * 3600]
    return {
        'low': m['low'] if m else None,
        'qty': qty_now,
        'ladder': m['ladder'] if m else [],
        'med': med, 'hi': hi, 'med24': med24, 'medAll': med_all,
        'perHour': sold_total / hours, 'medHour': med_hour,
        'hoursSeen': len(rows), 'hoursWithSales': hours_with_sales,
        'sales': sales, 'sellThrough': (sold_total / (sold_total + exp_total)) if (sold_total + exp_total) else None,
        'qtyDayAgo': qty_24h_ago[0] if qty_24h_ago else None,
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


FIELDS = ['low', 'qty', 'med', 'hi', 'med24', 'medAll', 'perHour', 'medHour', 'hoursSeen', 'hoursWithSales', 'sales',
          'sellThrough', 'qtyDayAgo']


def write_lua(path, state, mk, now_ts):
    keys = set(state['hourly']) | {str(i) for i in mk}
    parts = []
    for k in sorted(keys, key=int):
        n = item_numbers(k, state, mk, now_ts)
        if not n['low'] and not n['sales']:
            continue
        row = [n[f] for f in FIELDS] + [n['ladder'][:12]]
        parts.append(f'[{k}]={lua(row)}')
    body = (f'-- Written by the AuctionForever collector. Do not edit.\n'
            f'AuctionForeverData = {{v=1,house={HOUSE},time={int(now_ts)},hours={round(sum(c[1] for c in state.get("compared", [])), 1)},\n'
            f'fields={lua(FIELDS + ["ladder"])},\nitems={{\n' + ',\n'.join(parts) + '\n}}\n')
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


def run(state_path, out_path, items=None, goods=None, now_ts=None):
    now_ts = now_ts or time.time()
    if items is None:
        items, goods = fetch()
    state = load_state(state_path)
    now = listings(items, goods)
    prev = state.get('listings')
    if prev is not None and prev == now:
        # Blizzard hasn't published a new snapshot yet: change nothing, so this isn't counted as an hour of no sales.
        if state.get('fmt') != FMT:
            # ...but a data file written by an older collector is rewritten right away in the current format.
            state['fmt'] = FMT
            save_state(state_path, state)
            n = write_lua(out_path, state, market(now), state['time'])
            print(f'house {HOUSE}: no new snapshot yet; data file rewritten in the current format ({n} items)')
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
    ev = compare(prev, now, hours_for_rate) if hours_for_rate else {}
    mk = market(now)
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
    print(f'house {HOUSE}: {len(now)} listings, {len(ev)} items changed, {n} items written')
    return True


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else '.'
    changed = run(os.path.join(d, 'state.json.gz'), os.path.join(d, 'AuctionForeverData.lua'))
    # Tell the workflow whether there's anything new to upload.
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            print('changed=' + ('true' if changed else 'false'), file=f)
