"""Save a snapshot of the live data before pushing any collector or workflow change.

Downloads the release assets state.json.gz and AuctionForeverData.lua (tag "data") into
backups/<UTC yyyymmdd-hhmm>/ and keeps the newest KEEP snapshots (older ones are deleted). backups/ is gitignored.

Run: python -I tools/snapshot.py
"""
import json, os, shutil, sys, time, urllib.request

REPO = 'areshort/AuctionForever'
ASSETS = ('state.json.gz', 'AuctionForeverData.lua')
KEEP = 5
UA = 'snapshot-client'
HERE = os.path.dirname(os.path.abspath(__file__))
BACKUPS = os.path.join(HERE, '..', 'backups')


def get(url, accept):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept})
    return urllib.request.urlopen(req, timeout=120).read()


def main():
    rel = json.loads(get(f'https://api.github.com/repos/{REPO}/releases/tags/data', 'application/vnd.github+json'))
    found = {a['name']: a for a in rel['assets']}
    missing = [n for n in ASSETS if n not in found]
    if missing:
        sys.exit(f'release has no {missing}')
    out = os.path.join(BACKUPS, time.strftime('%Y%m%d-%H%M', time.gmtime()))
    os.makedirs(out, exist_ok=True)
    for n in ASSETS:
        body = get(found[n]['url'], 'application/octet-stream')
        if len(body) != found[n]['size']:
            sys.exit(f'{n}: got {len(body)} bytes, expected {found[n]["size"]}')
        with open(os.path.join(out, n), 'wb') as f:
            f.write(body)
        print(f'{n}: {len(body)} bytes (published {found[n]["updated_at"]})')
    snaps = sorted(d for d in os.listdir(BACKUPS) if os.path.isdir(os.path.join(BACKUPS, d)))
    for d in snaps[:-KEEP]:
        shutil.rmtree(os.path.join(BACKUPS, d))
    print('saved to', os.path.abspath(out), f'({min(len(snaps), KEEP)} kept)')


if __name__ == '__main__':
    main()
