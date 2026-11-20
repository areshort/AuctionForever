"""AuctionForever Sync: keeps the add-on's data file up to date while it runs.

Every 5 minutes it asks GitHub when the collector last published AuctionForeverData.lua, and downloads it into
the AuctionForever add-on folder only when there's a newer one. The game reads the file at login or /reload.
Close the window to stop it.

Usage: AuctionForeverSync.exe [add-on folder]
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

REPO = 'areshort/AuctionForever'
ASSET = 'AuctionForeverData.lua'
CHECK_EVERY = 300  # seconds
DEFAULT_DIR = r'C:\Program Files (x86)\World of Warcraft\_forever_\Interface\AddOns\AuctionForever'
HEADER = '-- Written by the AuctionForever collector.'
UA = {'User-Agent': 'AuctionForeverSync', 'Accept': 'application/vnd.github+json'}


def latest():
    """(updated_at, download url) of the published data file."""
    req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases/tags/data', headers=UA)
    rel = json.load(urllib.request.urlopen(req, timeout=30))
    for a in rel.get('assets', []):
        if a['name'] == ASSET:
            return a['updated_at'], a['url']  # API asset URL: not cached like the public download link
    raise RuntimeError('no data file published yet')


def download(url, dest):
    req = urllib.request.Request(url, headers={'User-Agent': 'AuctionForeverSync', 'Accept': 'application/octet-stream'})
    body = urllib.request.urlopen(req, timeout=120).read()
    text = body.decode('utf-8')
    if not text.startswith(HEADER):
        raise RuntimeError('downloaded file is not an AuctionForever data file')
    tmp = dest + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(body)
    os.replace(tmp, dest)
    return len(body)


def local_stamp(stamp_path):
    try:
        with open(stamp_path, encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return None


def age(iso):
    t = datetime.strptime(iso, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    mins = int((datetime.now(timezone.utc) - t).total_seconds() // 60)
    return f'{mins} min ago' if mins < 120 else f'{mins // 60} h ago'


def once(folder):
    """One check. Returns a status line."""
    dest = os.path.join(folder, ASSET)
    stamp_path = os.path.join(folder, 'AuctionForeverData.stamp')
    updated, url = latest()
    if updated == local_stamp(stamp_path) and os.path.exists(dest):
        return f'up to date (collected {age(updated)})'
    size = download(url, dest)
    with open(stamp_path, 'w', encoding='utf-8') as f:
        f.write(updated)
    return f'downloaded new data ({size // 1024} KB, collected {age(updated)}): /reload in game to use it'


def already_running():
    """True if another copy is running (a named Windows mutex, released by Windows when that copy closes)."""
    if os.name != 'nt':
        return False
    import ctypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    global _MUTEX  # kept for the life of the program
    _MUTEX = k32.CreateMutexW(None, False, r'Local\AuctionForeverSync')
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    if already_running():
        os.system('title AuctionForever Sync (already running)')
        print('AuctionForever Sync is already running: look for its window on the taskbar.')
        print('Only one copy is needed. This window closes in 10 seconds.')
        time.sleep(10)
        return 0
    os.system('title AuctionForever Sync')
    print('AuctionForever Sync')
    print(f'Add-on folder: {folder}')
    print('Checks for new auction data every 5 minutes. Close this window to stop.\n')
    if not os.path.isdir(folder):
        print('The AuctionForever add-on folder was not found. Install the add-on first, or pass its folder:')
        print('  AuctionForeverSync.exe "<path to Interface\\AddOns\\AuctionForever>"')
        input('\nPress Enter to close.')
        return 1
    while True:
        stamp = datetime.now().strftime('%H:%M')
        try:
            print(f'[{stamp}] {once(folder)}')
        except urllib.error.HTTPError as e:
            print(f'[{stamp}] GitHub answered {e.code}; will try again in 5 minutes')
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            print(f'[{stamp}] could not update ({e}); will try again in 5 minutes')
        time.sleep(CHECK_EVERY)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
