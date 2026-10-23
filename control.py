#!/usr/bin/env python3
"""cterm: persistent terminals with explicit, reversible phone sharing."""
import argparse
import fcntl
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from contextlib import contextmanager
from pathlib import Path
import core
from selector import select_item, clipped, display_width
from cli_help import HelpParser, DETAILS
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

def listener_url(meta):
    host = meta['bind']
    return f"http://{'[' + host + ']' if ':' in host else host}:{meta['port']}"

def browser_url(value):
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError('Use an HTTPS origin without a path, query, or credentials, e.g. https://cterm.example.com')
    return 'https://' + parsed.netloc


def base_url(meta):
    return meta.get('base_url') or listener_url(meta)


def secret_url(meta):
    return base_url(meta) + '/?token=' + core.token()

def show_url(args):
    meta = server_status()
    if not meta:
        raise core.TerminalError('The bridge is stopped. Run: cterm start')
    url = secret_url(meta)
    print(url)
    if args.qr:
        try:
            import segno
        except ImportError as exc:
            raise core.TerminalError('QR support is missing. Run ./install.sh from the cterm checkout to update dependencies.') from exc
        qr = segno.make_qr(url, error='m')
        print('\nScan with your phone camera (Tailscale must be connected):\n')
        # Reset before every newline: scrolling with an active background color
        # can otherwise paint the unused area to the right of the QR code.
        output = io.StringIO()
        qr.terminal(out=output, border=4, compact=True)
        for line in output.getvalue().splitlines():
            if sys.stdout.isatty():
                print('\033[97;40m' + line + '\033[0m')
            else:
                print(line)

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
            command = [sys.executable, str(core.ROOT / 'server.py'), '--bind', host, '--port', str(args.port)]
            if args.base_url:
                command.append('--secure-cookie')
            proc = subprocess.Popen(command,
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    start_new_session=True, close_fds=True)
        meta = dict(pid=proc.pid, start=process_start(proc.pid), bind=host, port=args.port, base_url=args.base_url)
        # Do not use the user's proxy for local/Tailscale readiness checks.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(80):
            if proc.poll() is not None:
                raise core.TerminalError('Failed to start the bridge. Check: ' + str(log_path))
            try:
                request = urllib.request.Request(listener_url(meta) + '/api/sessions', headers={'Cookie': 'cterm=' + secret})
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
        raise core.TerminalError('Use a unique name or registration ID (cterm list --ids). Omit the name to choose interactively.')
    return matches[0]

def new(args):
    if not re.fullmatch(r'[\w-]{1,60}', args.name):
        raise core.TerminalError('Use 1-60 letters, digits, underscores, or hyphens for the terminal name.')
    core.ensure_state()
    if any(item['name'] == args.name or (item['source'] == core.SOCKET and item['session'] == args.name) for item in core.cleanup_targets()):
        raise core.TerminalError(f'The name {args.name!r} is already in use. Reuse it with cterm attach, share it with cterm register, or clean it up first with cterm delete {args.name}.')
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
    print(f'Created shared terminal: {args.name}')
    print('Attach on the host: cterm attach')

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
    print(f"Shared: {args.name or pane['session']}")

def choose_shared(title, verb, running_only=False):
    def entries():
        registry = core.registry()
        items = core.shared_list()
        for item in items:
            item['location'] = registry.get(item['id'], {}).get('location', '')
        return sorted((item for item in items if item['online'] or not running_only),
                      key=lambda item: (item['name'], item['session'], item['location'], item['id']))

    def label(item):
        state = 'running' if item['online'] else 'exited'
        return f"{item['name']}  [{state}]  {item['command'] or '-'}  ({item['session']}:{item['location']})"

    return select_item(title, entries, label, verb)


def unregister(args):
    if args.name is not None:
        key, entry = select_shared(args.name)
    else:
        chosen = choose_shared('Select a terminal to unshare', 'unshare')
        if chosen is None:
            print('Unsharing canceled.')
            return
        key, entry = select_shared(chosen['id'])
    core.unregister(key)
    print(f"Unshared: {entry['name']}. The terminal keeps running.")


def delete(args):
    items = core.cleanup_targets()
    if args.name is None:
        def label(item):
            state = 'running' if item['online'] else 'exited'
            sharing = 'shared' if item['shared'] else 'not shared'
            return f"{item['name']}  [{state}, {sharing}]  {item['command'] or '-'}  ({item['session']}:{item['location']})"
        item = select_item('Select a terminal to delete (stops its program)', core.cleanup_targets, label, 'select')
        if item is None:
            print('Deletion canceled.')
            return
    else:
        matches = [item for item in items if item['id'] == args.name]
        if not matches:
            matches = [item for item in items if item['name'] == args.name]
        if len(matches) != 1:
            raise core.TerminalError('Terminal name is missing or ambiguous. Run cterm delete without a name to choose one.')
        item = matches[0]
    if item['online'] and not args.yes:
        if not sys.stdin.isatty():
            raise core.TerminalError('Deleting a running terminal requires confirmation. Use --yes for non-interactive deletion.')
        try:
            reply = input(f"Delete {item['name']!r} and stop its running program? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            print('\nDeletion canceled.')
            return
        if reply.strip().lower() not in ('y', 'yes'):
            print('Deletion canceled.')
            return
    core.delete_terminal(item)
    print(f"Deleted: {item['name']}. Its tmux pane and matching registrations have been removed.")


def attach(args):
    if args.name is None:
        chosen = choose_shared('Select a terminal to open', 'attach', running_only=True)
        if chosen is None:
            print('Attach canceled.')
            return
        key, entry = select_shared(chosen['id'])
    else:
        key, entry = select_shared(args.name)
    _, live = core.target(key)
    core.tmux(entry['source'], 'select-pane', '-t', entry['pane'])
    env = os.environ.copy()
    env.pop('TMUX', None)
    env['LD_LIBRARY_PATH'] = str(core.ROOT / 'vendor/root/usr/lib/x86_64-linux-gnu') + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    argv = core.tmux_command(entry['source']) + ['attach-session', '-t', '=' + live['session']]
    os.execvpe(argv[0], argv, env)

def main():
    parser = HelpParser(prog='cterm', overview=True, usage='%(prog)s <command> [options]')
    sub = parser.add_subparsers(prog='cterm', dest='action', required=True, metavar='COMMAND')
    cmd = sub.add_parser('start', help='Start the bridge (default: Tailscale IP)')
    cmd.add_argument('--bind', metavar='ADDRESS', help='Loopback or Tailscale IP (default: automatic)')
    cmd.add_argument('--port', metavar='PORT', type=int, default=8765, help='Listening port (default: 8765)')
    cmd.add_argument('--base-url', type=browser_url, metavar='HTTPS_URL', help='Browser origin behind your HTTPS reverse proxy, e.g. https://cterm.example.com')
    cmd.set_defaults(run=start)
    sub.add_parser('stop', help='Stop the bridge without stopping terminals').set_defaults(run=stop)
    for action, description in {
        'status': 'Show bridge and shared terminal status',
        'url': 'Print the private browser access link',
        'list': 'List shared terminals',
        'available': 'List discoverable tmux panes',
    }.items():
        cmd = sub.add_parser(action, help=description)
        if action == 'list':
            cmd.add_argument('--ids', action='store_true', help='Include registration IDs in the last column')
        elif action == 'url':
            cmd.add_argument('--qr', action='store_true', help='Also display a QR code to scan with your phone')
            cmd.set_defaults(run=show_url)
    cmd = sub.add_parser('new', help='Create and share a persistent terminal')
    cmd.usage = '%(prog)s [--cwd DIR] NAME [-- COMMAND ...]'
    cmd.add_argument('--cwd', metavar='DIR', default=os.getcwd(), help='Working directory (default: current directory); put before NAME')
    cmd.add_argument('name', metavar='NAME', help='A name you choose for this terminal (e.g. work or api)')
    cmd.add_argument('command', metavar='COMMAND', nargs=argparse.REMAINDER, help='Program and arguments (default: your login shell)')
    cmd.set_defaults(run=new)
    cmd = sub.add_parser('register', help='Select and share an existing tmux pane')
    cmd.add_argument('--pane', metavar='PANE', help='Pane ID to share directly, e.g. %%0 (default: TUI picker)')
    cmd.add_argument('--source', metavar='SOURCE', default='local', help='Source for --pane: local, default, or a tmux socket path')
    cmd.add_argument('--name', metavar='NAME', help='Display name in the shared terminal list')
    cmd.set_defaults(run=register)
    for action in ('unregister', 'attach'):
        cmd = sub.add_parser(action, help='Select or specify a terminal to unshare' if action == 'unregister' else 'Pick a shared terminal to open on the host')
        cmd.add_argument('name', metavar='NAME_OR_ID', nargs='?', help='Shared terminal name or registration ID (omit for TUI picker)')
    sub.choices['unregister'].set_defaults(run=unregister)
    sub.choices['attach'].set_defaults(run=attach)
    cmd = sub.add_parser('delete', help='Close a terminal and remove its registrations')
    cmd.add_argument('name', metavar='NAME_OR_ID', nargs='?', help='Terminal name or ID (omit for TUI picker)')
    cmd.add_argument('--yes', '-y', action='store_true', help='Confirm stopping the selected terminal without prompting')
    cmd.set_defaults(run=delete)
    cmd = sub.add_parser('help', help='Show help for cterm or a command')
    cmd.add_argument('command', metavar='COMMAND', nargs='?', choices=sorted(sub.choices), help='Command to describe (omit for overview)')
    for name, command_parser in sub.choices.items():
        command_parser.description, command_parser.epilog = DETAILS[name]
    if len(sys.argv) == 1:
        parser.print_help()
        return
    args = parser.parse_args()
    if args.action == 'help':
        (sub.choices[args.command] if args.command else parser).print_help()
    elif hasattr(args, 'run'):
        args.run(args)
    elif args.action == 'list':
        entries = sorted(core.shared_list(), key=lambda entry: (entry['name'], entry['id']))
        if not entries:
            print('No terminals are shared.')
        else:
            headers = ['NAME', 'STATE', 'PROGRAM'] + (['ID'] if args.ids else [])
            rows = [[entry['name'], 'running' if entry['online'] else 'exited', entry['command'] or '-'] +
                    ([entry['id']] if args.ids else []) for entry in entries]
            limits = [36, 7, 24, 16]
            widths = [min(limits[i], max(display_width(row[i]) for row in [headers, *rows])) for i in range(len(headers))]
            for row in [headers, *rows]:
                cells = []
                for value, width in zip(row, widths):
                    text = clipped(value, width - 3) + '...' if display_width(value) > width else clipped(value, width)
                    cells.append(text + ' ' * (width - display_width(text)))
                print('  '.join(cells).rstrip())
    elif args.action == 'available':
        for p in core.discover():
            source = 'local' if p['source'] == core.SOCKET else p['source']
            print(f"{source}  {p['pane']}  {p['session']} / {p['location']}  {p['command']}")
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
