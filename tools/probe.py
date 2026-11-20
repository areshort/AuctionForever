"""Probe Blizzard's WoW Forever auction API and save sample responses (no credentials are printed or saved)."""
import base64, json, os, sys, time, urllib.request, winreg

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'samples')
os.makedirs(OUT, exist_ok=True)


def user_env(name):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as k:
        return winreg.QueryValueEx(k, name)[0]


def token():
    pair = base64.b64encode(f"{user_env('BLIZZARD_CLIENT_ID')}:{user_env('BLIZZARD_CLIENT_SECRET')}".encode()).decode()
    req = urllib.request.Request('https://oauth.battle.net/token', data=b'grant_type=client_credentials',
                                 headers={'Authorization': 'Basic ' + pair, 'Content-Type': 'application/x-www-form-urlencoded'})
    return json.load(urllib.request.urlopen(req, timeout=30))['access_token']


TOK = token()


def get(path, ns='dynamic-forever-us'):
    url = f'https://us.api.blizzard.com{path}{"&" if "?" in path else "?"}namespace={ns}'
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + TOK, 'Accept-Encoding': 'identity'})
    t = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=120)
        body = r.read()
        return r.status, body, time.time() - t, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t, dict(e.headers)


def save(name, body):
    with open(os.path.join(OUT, name), 'wb') as f:
        f.write(body)


st, body, dt, _ = get('/data/wow/ruleset/index')
print('ruleset index', st, f'{dt:.1f}s')
save('ruleset_index.json', body)
rulesets = []
if st == 200:
    j = json.loads(body)
    for r in j.get('rulesets', []):
        rulesets.append(r.get('id'))
        print('  ruleset', r.get('id'), r.get('name'))
rs = rulesets[0] if rulesets else 1
st, body, dt, _ = get(f'/data/wow/ruleset/{rs}')
print('ruleset detail', rs, st)
save(f'ruleset_{rs}.json', body)
if st == 200:
    print('  ', json.dumps(json.loads(body))[:600])
st, body, dt, _ = get(f'/data/wow/ruleset/{rs}/auctions/')
print('auction index', st, f'{dt:.1f}s')
save('auction_index.json', body)
houses = []
if st == 200:
    j = json.loads(body)
    for a in j.get('auctions', []):
        nm = a.get('name'); houses.append((a.get('id'), nm.get('en_US') if isinstance(nm, dict) else nm))
    print('  houses:', houses)
summary = {}
for hid, name in houses:
    st, body, dt, hdr = get(f'/data/wow/ruleset/{rs}/auctions/{hid}')
    n = None
    if st == 200:
        j = json.loads(body)
        n = len(j.get('auctions', []) or [])
        save(f'house_{hid}.json', body)
    summary[hid] = {'name': name, 'status': st, 'auctions': n, 'bytes': len(body), 'secs': round(dt, 1), 'last_modified': hdr.get('Last-Modified')}
    print('  house', hid, name, st, n, 'auctions', len(body), 'bytes', hdr.get('Last-Modified'))
for hid, name in houses[:3]:
    st, body, dt, hdr = get(f'/data/wow/ruleset/{rs}/auctions/{hid}/commodities')
    n = len(json.loads(body).get('auctions', []) or []) if st == 200 else None
    if st == 200:
        save(f'house_{hid}_commodities.json', body)
    print('  commodities', hid, st, n, len(body), 'bytes', hdr.get('Last-Modified'))
json.dump(summary, open(os.path.join(OUT, 'summary.json'), 'w'), indent=1)
