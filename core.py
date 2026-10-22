"""Local tmux discovery and explicit terminal sharing registry."""
import fcntl
import json
import os
import secrets
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_BASE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
LEGACY_STATE = STATE_BASE / 'codex-mobile-terminal'
DEFAULT_STATE = LEGACY_STATE if LEGACY_STATE.is_dir() else STATE_BASE / 'cterm'
STATE = Path(os.environ.get('CTERM_STATE', str(DEFAULT_STATE))).expanduser().resolve()
SOCKET = str(STATE / 'tmux.sock')
KEYS = {'enter': 'Enter', 'tab': 'Tab', 'escape': 'Escape', 'backspace': 'BSpace',
        'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right',
        'ctrlc': 'C-c', 'ctrld': 'C-d'}

class TerminalError(RuntimeError):
    pass

def ensure_state():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)

def tmux_command(source):
    bundled = ROOT / 'vendor/root/usr/bin/tmux'
    binary = str(bundled) if bundled.exists() else shutil.which('tmux')
    if not binary:
        raise TerminalError('tmux was not found. See the installation instructions in README.md.')
    return [binary, '-L', 'default'] if source == 'default' else [binary, '-S', source]

def tmux(source, *args, data=None, check=True):
    env = os.environ.copy()
    env.pop('TMUX', None)
    libs = str(ROOT / 'vendor/root/usr/lib/x86_64-linux-gnu')
    env['LD_LIBRARY_PATH'] = libs + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    try:
        result = subprocess.run(tmux_command(source) + list(args), input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TerminalError(str(exc)) from exc
    if check and result.returncode:
        raise TerminalError(result.stderr.decode('utf-8', 'replace').strip() or 'tmux request failed')
    return result

def sources(extra=None):
    values = [SOCKET, 'default']
    if os.environ.get('TMUX'):
        values.append(os.environ['TMUX'].split(',')[0])
    if extra:
        values.append(extra)
    return list(dict.fromkeys(values))

def panes(source):
    fmt = '#{pane_id}\t#{session_name}\t#{window_index}.#{pane_index}\t#{pane_current_command}\t#{pane_width}\t#{pane_height}\t#{pid}\t#{pane_pid}\t#{session_created}'
    result = tmux(source, 'list-panes', '-a', '-F', fmt, check=False)
    if result.returncode:
        return []
    found = []
    for line in result.stdout.decode('utf-8', 'replace').splitlines():
        fields = line.split('\t')
        if len(fields) != 9:
            continue
        pane, session, location, command, width, height, server_pid, pane_pid, created = fields
        found.append(dict(source=source, pane=pane, session=session, location=location,
                          command=command, width=int(width), height=int(height),
                          identity=[server_pid, pane_pid, created]))
    return found

def discover(extra=None):
    return [p for source in sources(extra) for p in panes(source)]

def registry():
    ensure_state()
    try:
        value = json.loads((STATE / 'registry.json').read_text())
    except FileNotFoundError:
        value = {}
    if not isinstance(value, dict):
        raise TerminalError('The terminal registry is invalid.')
    return value

@contextmanager
def registry_lock():
    ensure_state()
    with (STATE / 'registry.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield

def save_registry(value):
    temp = STATE / ('registry-' + secrets.token_hex(8) + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
    os.replace(temp, STATE / 'registry.json')

def register(pane, name=None):
    with registry_lock():
        value = registry()
        for key, old in value.items():
            if all(old.get(field) == pane[field] for field in ('source', 'pane', 'identity')):
                old['name'] = name or old['name']
                save_registry(value)
                return key
        key = secrets.token_hex(8)
        value[key] = {**pane, 'name': name or pane['session']}
        save_registry(value)
        return key

def unregister(key):
    with registry_lock():
        value = registry()
        if key not in value:
            raise TerminalError('This terminal ID is not registered.')
        del value[key]
        save_registry(value)

def live_pane(entry):
    return next((p for p in panes(entry['source']) if p['pane'] == entry['pane'] and p['identity'] == entry['identity']), None)

def target(key):
    entry = registry().get(key)
    if not entry:
        raise TerminalError('This terminal is no longer shared.')
    pane = live_pane(entry)
    if not pane:
        raise TerminalError('The terminal has exited. Register its replacement explicitly.')
    return entry, pane

def shared_list():
    cache = {}
    output = []
    for key, entry in registry().items():
        source = entry['source']
        if source not in cache:
            cache[source] = panes(source)
        pane = next((p for p in cache[source] if p['pane'] == entry['pane'] and p['identity'] == entry['identity']), None)
        output.append(dict(id=key, name=entry['name'], online=bool(pane),
                           command=pane['command'] if pane else '', session=entry['session']))
    return output

def snapshot(key):
    entry, pane = target(key)
    result = tmux(entry['source'], 'capture-pane', '-p', '-t', entry['pane'])
    return dict(type='screen', text=result.stdout.decode('utf-8', 'replace'),
                cols=pane['width'], rows=pane['height'])

def send_text(key, text, enter):
    entry, _ = target(key)
    source, pane = entry['source'], entry['pane']
    if text:
        buffer = 'cterm-' + secrets.token_hex(12)
        try:
            tmux(source, 'load-buffer', '-b', buffer, '-', data=text.encode('utf-8'))
            tmux(source, 'paste-buffer', '-p', '-d', '-b', buffer, '-t', pane)
        finally:
            tmux(source, 'delete-buffer', '-b', buffer, check=False)
    if enter:
        tmux(source, 'send-keys', '-t', pane, 'Enter')

def send_key(key, name):
    if name not in KEYS:
        raise TerminalError('Unsupported key.')
    entry, _ = target(key)
    tmux(entry['source'], 'send-keys', '-t', entry['pane'], KEYS[name])

def token():
    ensure_state()
    file = STATE / 'token'
    try:
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return file.read_text().strip()
    value = secrets.token_urlsafe(32)
    with os.fdopen(fd, 'w') as output:
        output.write(value + '\n')
    return value
