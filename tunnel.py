"""Optional public Cloudflare connectors; credentials stay in the user's state."""
import argparse
import configparser
from contextlib import contextmanager, redirect_stdout
import fcntl
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

import core


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + secrets.token_hex(8))
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(value)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def lock():
    core.ensure_state()
    with (core.STATE / 'tunnel.lock').open('a') as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        yield


def load(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def status(controller):
    meta = load(core.STATE / 'tunnel.json')
    if meta and controller.process_start(meta['pid']) == meta['start']:
        return meta
    return None


def request_json(url, headers=None, data=None, method=None):
    request = urllib.request.Request(url, headers={'User-Agent': 'cterm', **(headers or {})},
                                     data=None if data is None else json.dumps(data).encode(), method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def binary():
    existing = shutil.which('cloudflared')
    target = core.STATE / 'tools/cloudflared'
    if existing:
        return existing
    if target.is_file() and os.access(target, os.X_OK):
        return str(target)
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or not arch:
        raise core.TerminalError('Install cloudflared on this platform and add it to PATH.')
    print('Downloading cloudflared from the official Cloudflare GitHub release...')
    release = request_json('https://api.github.com/repos/cloudflare/cloudflared/releases/latest')
    asset = next(a for a in release['assets'] if a['name'] == 'cloudflared-linux-' + arch)
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise core.TerminalError('The release has no SHA-256 digest. Install cloudflared manually.')
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/cloudflare/cloudflared/releases/download/'):
        raise core.TerminalError('Unexpected cloudflared download location.')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = target.with_name('cloudflared.' + secrets.token_hex(8))
    try:
        sha = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(url, timeout=60) as source, temp.open('xb') as output:
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise core.TerminalError('Unexpected cloudflared download size.')
                sha.update(chunk)
                output.write(chunk)
        if total != asset['size'] or 'sha256:' + sha.hexdigest() != digest:
            raise core.TerminalError('cloudflared checksum verification failed.')
        temp.chmod(0o700)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    print('Installed cloudflared ' + release['tag_name'] + ' (SHA-256 verified).')
    return str(target)


def api_token(filename):
    path = Path(filename).expanduser()
    if not path.exists():
        if not os.isatty(0):
            raise core.TerminalError('Create a Cloudflare API token file first; see cterm help tunnel.')
        print('Create a token at https://dash.cloudflare.com/profile/api-tokens')
        print('Permissions: Account / Cloudflare Tunnel / Edit; Zone / DNS / Edit; Zone / Zone / Read.')
        token = getpass.getpass('Cloudflare API token (hidden): ').strip()
        if not token:
            raise core.TerminalError('No API token provided.')
        write_private(path, 'dns_cloudflare_api_token = ' + token + '\n')
        return token
    if path.stat().st_mode & 0o077:
        raise core.TerminalError('Restrict the API token file to its owner: chmod 600 ' + str(path))
    text = path.read_text().strip()
    if '=' in text:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string('[cloudflare]\n' + text)
        text = parser['cloudflare'].get('dns_cloudflare_api_token', '').strip()
    if not text or '\n' in text:
        raise core.TerminalError('Use a raw API token or dns_cloudflare_api_token = TOKEN in the token file.')
    return text


class Cloudflare:
    def __init__(self, token):
        self.headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    def call(self, path, data=None, method=None):
        try:
            result = request_json('https://api.cloudflare.com/client/v4/' + path, self.headers, data, method)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise core.TerminalError('Cloudflare denied access. The token needs Account / Cloudflare Tunnel / Edit, Zone / DNS / Edit, and Zone / Zone / Read for the selected account and zone.') from None
            raise core.TerminalError('Cloudflare API request failed (HTTP ' + str(exc.code) + ').') from None
        if not result.get('success'):
            raise core.TerminalError('Cloudflare rejected the request. Check token permissions and account limits.')
        return result['result']


def hostname(value):
    value = value.rstrip('.').lower()
    if len(value) > 253 or '.' not in value or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in value.split('.')):
        raise argparse.ArgumentTypeError('Use a hostname such as terminal.example.com, without https:// or a path.')
    return value


def prepare_named(args, port):
    path = core.STATE / 'tunnels' / (args.hostname + '.json')
    cached = load(path)
    token_path = path.with_suffix('.token')
    if cached and cached.get('dns_ready') and cached['port'] == port and token_path.exists():
        return cached, token_path, None, None
    api = Cloudflare(api_token(args.api_token_file))
    # Query possible zone suffixes rather than requiring access to all zones.
    parts = args.hostname.split('.')
    zone = None
    for index in range(1, len(parts)):
        zones = api.call('zones?name=' + '.'.join(parts[index:]))
        if zones:
            zone = zones[0]
            break
    if not zone:
        raise core.TerminalError('No accessible Cloudflare zone for this subdomain. Check the hostname and token zone scope.')
    account = zone['account']['id']
    records_path = 'zones/' + zone['id'] + '/dns_records'
    records = api.call(records_path + '?name=' + args.hostname)
    own_target = cached['id'] + '.cfargotunnel.com' if cached else None
    own = len(records) == 1 and records[0]['type'] == 'CNAME' and records[0]['content'] == own_target
    if records and not own:
        if not args.replace_dns or len(records) != 1 or records[0]['type'] not in ('A', 'CNAME'):
            raise core.TerminalError('DNS already exists for this hostname. Choose an unused subdomain, or use --replace-dns to replace one A/CNAME record explicitly.')
    if cached:
        tunnel = cached
        if not token_path.exists():
            token = api.call('accounts/' + account + '/cfd_tunnel/' + tunnel['id'] + '/token')
            write_private(token_path, token + '\n')
    else:
        tunnel = api.call('accounts/' + account + '/cfd_tunnel', {
            'name': 'cterm-' + args.hostname[:40] + '-' + secrets.token_hex(4), 'config_src': 'cloudflare'})
        token = tunnel.get('token') or api.call('accounts/' + account + '/cfd_tunnel/' + tunnel['id'] + '/token')
        write_private(token_path, token + '\n')
    saved = dict(id=tunnel['id'], account=account, zone=zone['id'], hostname=args.hostname, port=port,
                 dns_ready=False)
    # Keep the tunnel identity even after an interrupted setup so retry reuses it.
    write_private(path, json.dumps(saved))
    api.call('accounts/' + account + '/cfd_tunnel/' + saved['id'] + '/configurations', {'config': {'ingress': [
        {'hostname': args.hostname, 'service': f'http://127.0.0.1:{port}'}, {'service': 'http_status:404'}]}}, 'PUT')
    return saved, token_path, api, (records_path, records, path)


def publish(named, api, dns):
    if api is None:
        if not named.get('dns_ready'):
            raise core.TerminalError('Domain setup was interrupted. Retry with --api-token-file to complete DNS setup.')
        return
    path, records, cache_path = dns
    payload = dict(type='CNAME', name=named['hostname'], content=named['id'] + '.cfargotunnel.com', proxied=True, ttl=1)
    if records:
        api.call(path + '/' + records[0]['id'], payload, 'PUT')
    else:
        api.call(path, payload, 'POST')
    named['dns_ready'] = True
    write_private(cache_path, json.dumps(named))


def terminate(meta, controller):
    if controller.process_start(meta['pid']) != meta['start']:
        return
    os.kill(meta['pid'], signal.SIGTERM)
    for _ in range(50):
        if controller.process_start(meta['pid']) != meta['start']:
            return
        time.sleep(.1)
    if controller.process_start(meta['pid']) == meta['start']:
        os.kill(meta['pid'], signal.SIGKILL)


def bridge(controller, bind, port, base_url):
    with redirect_stdout(io.StringIO()):
        controller.stop(None)
        controller.start(argparse.Namespace(bind=bind, port=port, base_url=base_url))


def start(args, controller):
    running = status(controller)
    if running:
        if running.get('hostname') != args.hostname:
            raise core.TerminalError('A different tunnel is running. Run cterm tunnel stop first.')
        current = controller.server_status()
        if not current or current['bind'] != '127.0.0.1' or current.get('base_url') != running['url'] or current['port'] != running['port']:
            bridge(controller, '127.0.0.1', running['port'], running['url'])
        print('Tunnel is already running: ' + running['url'])
        controller.show_url(argparse.Namespace(qr=False))
        return
    previous = controller.server_status()
    port = previous['port'] if previous else args.port
    named = token_path = api = dns = None
    if args.hostname:
        named, token_path, api, dns = prepare_named(args, port)
    executable = binary()
    command = [executable, 'tunnel', '--config', '/dev/null', '--no-autoupdate', '--protocol', 'http2', '--metrics', '127.0.0.1:0']
    if named:
        command += ['run', '--token-file', str(token_path)]
    else:
        command += ['--url', f'http://127.0.0.1:{port}']
    log_path = core.STATE / 'tunnel.log'
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    meta = None
    try:
        # The backend is loopback-only and uses Secure cookies before publication.
        bridge(controller, '127.0.0.1', port, 'https://' + args.hostname if named else 'https://pending.invalid')
        with os.fdopen(fd, 'wb') as log:
            fd = None
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)
        meta = dict(pid=proc.pid, start=controller.process_start(proc.pid), hostname=args.hostname, url=None, port=port)
        print('Connecting Cloudflare Tunnel...')
        deadline = time.monotonic() + 55
        url = 'https://' + args.hostname if named else None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise core.TerminalError('cloudflared exited. Check the private log: ' + str(log_path))
            text = log_path.read_text(errors='replace')
            if not named:
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com\b', text)
                if match:
                    url = match[0]
            if url and 'Registered tunnel connection' in text:
                break
            time.sleep(.2)
        else:
            raise core.TerminalError('Tunnel connection timed out. Check outbound TCP port 7844 and ' + str(log_path))
        if not named:
            bridge(controller, '127.0.0.1', port, url)
        if named:
            publish(named, api, dns)
        meta['url'] = url
        write_private(core.STATE / 'tunnel.json', json.dumps(meta))
    except BaseException:
        if fd is not None:
            os.close(fd)
        if meta:
            terminate(meta, controller)
        with redirect_stdout(io.StringIO()):
            controller.stop(None)
            if previous:
                controller.start(argparse.Namespace(bind=previous['bind'], port=previous['port'], base_url=previous.get('base_url')))
        raise
    print('Tunnel is running. No VPN app is required on your phone.')
    if not named:
        print('This temporary URL changes after restarting the tunnel.')
    controller.show_url(argparse.Namespace(qr=False))
    print('To display a QR code: cterm url --qr')


def handle(args, controller):
    try:
        with lock():
            if args.tunnel_action == 'start':
                start(args, controller)
            elif args.tunnel_action == 'status':
                meta = status(controller)
                print('Tunnel: ' + (meta['url'] if meta else 'stopped'))
                print('Bridge: ' + ('running' if controller.server_status() else 'stopped'))
            else:
                meta = status(controller)
                if meta:
                    terminate(meta, controller)
                (core.STATE / 'tunnel.json').unlink(missing_ok=True)
                controller.stop(None)
                print('Tunnel stopped. Terminal jobs keep running. Saved domain tunnels are kept for reuse.')
    except (urllib.error.URLError, OSError, ValueError, KeyError, StopIteration) as exc:
        raise core.TerminalError('Tunnel setup failed (' + type(exc).__name__ + '). Check your network, cloudflared installation, and configuration.') from None
