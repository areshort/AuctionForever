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


