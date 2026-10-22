#!/usr/bin/env python3
"""cterm: persistent terminals with explicit, reversible phone sharing."""
import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
import core
from selector import select_item
from server import allowed_bind

META = core.STATE / 'server.json'

def process_start(pid):
    try:
        parts = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()
        return parts[19] if parts[0] != 'Z' else None
    except (OSError, IndexError):
        return None

def server_status():
    try:
        meta = json.loads(META.read_text())
        return meta if process_start(meta['pid']) == meta['start'] else None
    except (OSError, ValueError, KeyError):
        return None

@contextmanager
def lifecycle_lock():
    core.ensure_state()
    with (core.STATE / 'server.lock').open('a') as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        yield

def private_ip():
    try:
        result = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            return allowed_bind(result.stdout.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        pass
    return '127.0.0.1'

def base_url(meta):
    host = meta['bind']
    return f"http://{'[' + host + ']' if ':' in host else host}:{meta['port']}"

def secret_url(meta):
    return base_url(meta) + '/?token=' + core.token()

def start(args):
    with lifecycle_lock():
        meta = server_status()
        if meta:
            print('The bridge is already running.')
            print(secret_url(meta))
            return
        host = allowed_bind(args.bind or private_ip())
        secret = core.token()
        log_path = core.STATE / 'server.log'
        fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'ab') as log:
            proc = subprocess.Popen([sys.executable, str(core.ROOT / 'server.py'), '--bind', host, '--port', str(args.port)],
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    start_new_session=True, close_fds=True)
        meta = dict(pid=proc.pid, start=process_start(proc.pid), bind=host, port=args.port)
        # Do not use the user's proxy for local/Tailscale readiness checks.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(80):
            if proc.poll() is not None:
                raise core.TerminalError('Failed to start the bridge. Check: ' + str(log_path))
            try:
                request = urllib.request.Request(base_url(meta) + '/api/sessions', headers={'Cookie': 'cterm=' + secret})
                with opener.open(request, timeout=0.3) as response:
                    if response.status == 200 and response.headers.get('X-Cterm-Process') == str(proc.pid):
                        META.write_text(json.dumps(meta))
                        META.chmod(0o600)
                        print('Bridge started. Open this link on a device connected to the same tailnet:')
                        print(secret_url(meta))
                        if host == '127.0.0.1':
                            print('Listening on localhost only. Start on your Tailscale IP for phone access.')
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        proc.terminate()
        raise core.TerminalError('Bridge startup timed out. Check: ' + str(log_path))

def stop(args):
    with lifecycle_lock():
        meta = server_status()
        if not meta:
            print('The bridge is stopped. Terminals run independently.')
            return
        os.kill(meta['pid'], signal.SIGTERM)
        for _ in range(70):
            if process_start(meta['pid']) != meta['start']:
                META.unlink(missing_ok=True)
                print('Bridge stopped. Shared terminals keep running.')
                return
            time.sleep(0.1)
        raise core.TerminalError('The bridge is still shutting down. No terminal processes were signaled.')

def source_arg(value):
    return core.SOCKET if value == 'local' else ('default' if value == 'default' else str(Path(value).expanduser().resolve()))

def select_shared(selector):
    entries = core.registry()
    if selector in entries:
        return selector, entries[selector]
    matches = [(key, value) for key, value in entries.items() if value['name'] == selector]
    if len(matches) != 1:
        raise core.TerminalError('Specify an exact registration ID or unique name. Run: cterm list')
    return matches[0]

def new(args):
    if not re.fullmatch(r'[\w-]{1,60}', args.name):
        raise core.TerminalError('Use 1-60 letters, digits, underscores, or hyphens for the terminal name.')
    core.ensure_state()
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        command = [os.environ.get('SHELL', '/bin/bash'), '-l']
    core.tmux(core.SOCKET, '-f', str(core.ROOT / 'tmux.conf'), 'new-session', '-d', '-s', args.name,
              '-c', str(Path(args.cwd).expanduser().resolve()), '-x', '120', '-y', '36', '--', *command)
    matches = [p for p in core.panes(core.SOCKET) if p['session'] == args.name]
    if not matches:
        raise core.TerminalError('The terminal exited immediately. Check the command you supplied.')
    key = core.register(matches[0], args.name)
    print(f'Created shared terminal: {args.name}  [{key}]')
    print(f'Attach on the host: cterm attach {key}')

def register(args):
    if args.pane:
        source = source_arg(args.source)
        matches = [p for p in core.panes(source) if p['pane'] == args.pane or p['session'] == args.pane]
        if len(matches) != 1:
            raise core.TerminalError('Select exactly one pane. Run cterm available to find pane IDs.')
        pane = matches[0]
    else:
        def available():
            entries = list(core.registry().values())
            found = sorted(core.discover(), key=lambda p: (p['session'], p['source'], p['pane']))
            for item in found:
                item['shared'] = any(all(old.get(field) == item[field] for field in ('source', 'pane', 'identity')) for old in entries)
            return found

        def label(item):
            status = 'shared' if item['shared'] else 'not shared'
            source = 'local' if item['source'] == core.SOCKET else item['source']
            return f"[{status}] {item['session']} / {item['location']}  {item['command']}  {item['pane']} ({source})"

        pane = select_item('Select a terminal to share', available, label, 'share')
        if pane is None:
            print('Sharing canceled.')
            return
    # A pane can disappear while the picker is open. Never register its replacement.
    if not core.live_pane(pane):
        raise core.TerminalError('The selected terminal has exited. Please select again.')
    key = core.register(pane, args.name)
    print(f"Shared: {args.name or pane['session']}  [{key}]")

def unregister(args):
    if args.name is not None:
        key, entry = select_shared(args.name)
    else:
        def entries():
            return sorted(core.shared_list(), key=lambda item: (item['name'], item['id']))

        def label(item):
            state = 'running' if item['online'] else 'exited'
            return f"{item['name']}  [{state}]  {item['command']}  {item['id']}"

        chosen = select_item('Select a terminal to unshare', entries, label, 'unshare')
        if chosen is None:
            print('Unsharing canceled.')
            return
        key, entry = select_shared(chosen['id'])
    core.unregister(key)
    print(f"Unshared: {entry['name']}. The terminal keeps running.")


def attach(args):
    key, entry = select_shared(args.name)
    _, live = core.target(key)
    core.tmux(entry['source'], 'select-pane', '-t', entry['pane'])
    env = os.environ.copy()
    env.pop('TMUX', None)
    env['LD_LIBRARY_PATH'] = str(core.ROOT / 'vendor/root/usr/lib/x86_64-linux-gnu') + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    argv = core.tmux_command(entry['source']) + ['attach-session', '-t', '=' + live['session']]
    os.execvpe(argv[0], argv, env)

def main():
    parser = argparse.ArgumentParser(prog='cterm', description='Share selected tmux panes with your phone.')
    sub = parser.add_subparsers(dest='action', required=True)
    cmd = sub.add_parser('start', help='Start the bridge (default: Tailscale IP)')
    cmd.add_argument('--bind')
    cmd.add_argument('--port', type=int, default=8765)
    cmd.set_defaults(run=start)
    sub.add_parser('stop', help='Stop the bridge without stopping terminals').set_defaults(run=stop)
    for action, description in {
        'status': 'Show bridge and shared terminal status',
        'url': 'Print the private browser access link',
        'list': 'List shared terminals',
        'available': 'List discoverable tmux panes',
    }.items():
        sub.add_parser(action, help=description)
    cmd = sub.add_parser('new', help='Create and share a persistent terminal')
    cmd.add_argument('--cwd', default=os.getcwd())
    cmd.add_argument('name')
    cmd.add_argument('command', nargs=argparse.REMAINDER)
    cmd.set_defaults(run=new)
    cmd = sub.add_parser('register', help='Select and share an existing tmux pane')
    cmd.add_argument('--pane')
    cmd.add_argument('--source', default='local', help='local, default, or a tmux socket path')
    cmd.add_argument('--name')
    cmd.set_defaults(run=register)
    for action in ('unregister', 'attach'):
        cmd = sub.add_parser(action, help='Select or specify a terminal to unshare' if action == 'unregister' else 'Attach to a shared terminal on the host')
        cmd.add_argument('name', **({'nargs': '?'} if action == 'unregister' else {}))
    sub.choices['unregister'].set_defaults(run=unregister)
    sub.choices['attach'].set_defaults(run=attach)
    cmd = sub.add_parser('help', help='Show help for cterm or a command')
    cmd.add_argument('command', nargs='?', choices=sorted(sub.choices), help='Command to describe')
    args = parser.parse_args()
    if args.action == 'help':
        (sub.choices[args.command] if args.command else parser).print_help()
    elif hasattr(args, 'run'):
        args.run(args)
    elif args.action == 'list':
        entries = core.shared_list()
        for entry in entries:
            print(f"{entry['id']}  {entry['name']}  {'running' if entry['online'] else 'exited'}  {entry['command']}")
        if not entries:
            print('No terminals are shared.')
    elif args.action == 'available':
        for p in core.discover():
            source = 'local' if p['source'] == core.SOCKET else p['source']
            print(f"{source}  {p['pane']}  {p['session']} / {p['location']}  {p['command']}")
    elif args.action == 'url':
        meta = server_status()
        if not meta:
            raise core.TerminalError('The bridge is stopped. Run: cterm start')
        print(secret_url(meta))
    elif args.action == 'status':
        meta = server_status()
        print('Bridge: ' + (f"running ({base_url(meta)})" if meta else 'stopped'))
        entries = core.shared_list()
        print(f"Shared terminals: {len(entries)} / running: {sum(e['online'] for e in entries)}")
        print(f'State directory: {core.STATE}')

if __name__ == '__main__':
    try:
        main()
    except (core.TerminalError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
