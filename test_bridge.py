"""Real tmux + HTTP/WebSocket tests, isolated from the user's terminals."""
import asyncio
import base64
import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from aiohttp import ClientSession, CookieJar, WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestServer, TestClient
import core
import server

class BridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_state, self.old_socket = core.STATE, core.SOCKET
        self.temp = tempfile.TemporaryDirectory(prefix='cterm-test-')
        core.STATE = Path(self.temp.name)
        core.SOCKET = str(core.STATE / 'tmux.sock')
        self.env = {**os.environ, 'CTERM_STATE': self.temp.name}
        self.background = False
        for name in ('visible', 'private'):
            core.tmux(core.SOCKET, '-f', str(core.ROOT / 'tmux.conf'), 'new-session', '-d',
                      '-s', name, '-x', '100', '-y', '32', '--', '/bin/bash', '--noprofile', '--norc')
        self.pane = next(p for p in core.panes(core.SOCKET) if p['session'] == 'visible')
        self.key = core.register(self.pane, '공유 테스트')
        self.client = TestClient(TestServer(server.create_app('test-secret')), cookie_jar=CookieJar(unsafe=True))
        await self.client.start_server()
        await self.client.get('/?token=test-secret')

    async def asyncTearDown(self):
        await self.client.close()
        if self.background:
            subprocess.run([sys.executable, str(core.ROOT / 'control.py'), 'stop'], env=self.env, capture_output=True)
        core.tmux(core.SOCKET, 'kill-server', check=False)
        core.STATE, core.SOCKET = self.old_state, self.old_socket
        self.temp.cleanup()

    def command(self, code):
        encoded = base64.b64encode(code.encode()).decode()
        return 'python3 -c ' + shlex.quote("import base64;exec(base64.b64decode('" + encoded + "'))")

    async def screen_until(self, ws, marker):
        async def read():
            while True:
                packet = await ws.receive_json()
                if packet.get('type') == 'screen' and marker in [s.strip() for s in packet['text'].splitlines()]:
                    return packet
        return await asyncio.wait_for(read(), timeout=8)

    async def test_auth_scope_input_unicode_and_reconnect(self):
        async with ClientSession() as unauthorized:
            res = await unauthorized.get(self.client.make_url('/api/sessions'))
            self.assertEqual(res.status, 401)
            res = await unauthorized.get(self.client.make_url('/?token=wrong'))
            self.assertEqual(res.status, 401)
        response = await self.client.get('/api/sessions')
        items = await response.json()
        self.assertEqual([x['name'] for x in items], ['공유 테스트'])
        with self.assertRaises(WSServerHandshakeError) as error:
            await self.client.ws_connect('/ws/' + self.key, headers={'Origin': 'https://evil.example'})
        self.assertEqual(error.exception.status, 403)
        ws = await self.client.ws_connect('/ws/' + self.key)
        first = await ws.receive_json()
        self.assertEqual(first['type'], 'screen')
        await ws.send_str('[]')
        while True:
            packet = await ws.receive_json(timeout=3)
            if packet['type'] == 'error':
                break
        # Bytes of one Korean character deliberately arrive in different reads.
        code = "import os,time;os.write(1,b'\\nUTF8_');os.write(1,b'\\xed');time.sleep(.25);os.write(1,b'\\x95\\x9c\\xea\\xb8\\x80\\n')"
        await ws.send_json({'type': 'text', 'text': self.command(code), 'id': 1})
        await self.screen_until(ws, 'UTF8_한글')
        hidden = next(p for p in core.panes(core.SOCKET) if p['session'] == 'private')
        self.assertNotIn('UTF8_', core.tmux(core.SOCKET, 'capture-pane', '-p', '-t', hidden['pane']).stdout.decode())
        code = "import time;print('INTERRUPT_READY',flush=True);time.sleep(30)"
        await ws.send_json({'type': 'text', 'text': self.command(code), 'id': 10})
        await self.screen_until(ws, 'INTERRUPT_READY')
        await ws.send_json({'type': 'key', 'key': 'ctrlc'})
        await ws.send_json({'type': 'text', 'text': self.command("print('INTERRUPT_OK')"), 'id': 11})
        await self.screen_until(ws, 'INTERRUPT_OK')
        marker = Path(self.temp.name) / 'continued'
        code = f"import time;from pathlib import Path;time.sleep(.4);Path({str(marker)!r}).write_text('ok');print('AFTER_DISCONNECT',flush=True)"
        await ws.send_json({'type': 'text', 'text': self.command(code), 'id': 2})
        while True:
            packet = await ws.receive_json()
            if packet.get('type') == 'ack' and packet.get('id') == 2:
                break
        await ws.close()
        for _ in range(50):
            if marker.exists():
                break
            await asyncio.sleep(.1)
        self.assertTrue(marker.exists())
        ws = await self.client.ws_connect('/ws/' + self.key)
        await self.screen_until(ws, 'AFTER_DISCONNECT')
        await ws.close()

    async def test_multiple_clients_unregister_and_stale_identity(self):
        a = await self.client.ws_connect('/ws/' + self.key)
        b = await self.client.ws_connect('/ws/' + self.key)
        await a.receive_json(); await b.receive_json()
        await a.send_json({'type': 'text', 'text': self.command("print('BOTH_CLIENTS')"), 'id': 3})
        await self.screen_until(a, 'BOTH_CLIENTS')
        await self.screen_until(b, 'BOTH_CLIENTS')
        core.unregister(self.key)
        for ws in (a, b):
            while True:
                msg = await ws.receive(timeout=3)
                if msg.type == WSMsgType.TEXT and json.loads(msg.data)['type'] == 'removed':
                    break
            await ws.close()
        self.assertIsNotNone(core.live_pane(self.pane))
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect('/ws/' + self.key)
        key = core.register(self.pane)
        core.tmux(core.SOCKET, 'kill-session', '-t', 'visible')
        core.tmux(core.SOCKET, 'new-session', '-d', '-s', 'visible', '--', '/bin/bash', '--norc')
        self.assertFalse(next(x for x in core.shared_list() if x['id'] == key)['online'])
        with self.assertRaises(core.TerminalError):
            core.send_text(key, 'MUST_NOT_REACH_NEW_TERMINAL', True)

    async def test_https_base_url_secure_cookie_and_local_readiness(self):
        secure = TestClient(TestServer(server.create_app('secure-test', secure_cookie=True)), cookie_jar=CookieJar(unsafe=True))
        await secure.start_server()
        try:
            response = await secure.get('/?token=secure-test', allow_redirects=False)
            self.assertEqual(response.status, 302)
            self.assertTrue(response.cookies['cterm']['secure'])
            self.assertTrue(response.cookies['cterm']['httponly'])
        finally:
            await secure.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        command = [sys.executable, str(core.ROOT / 'control.py')]
        for invalid in ('http://cterm.example.test', 'https://cterm.example.test/private', 'https://user:pass@cterm.example.test'):
            result = await asyncio.to_thread(subprocess.run, command + ['start', '--base-url', invalid], env=self.env, capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        result = await asyncio.to_thread(subprocess.run, command + ['start', '--bind', '127.0.0.1', '--port', str(port), '--base-url', 'https://cterm.example.test/'], env=self.env, capture_output=True, text=True, timeout=15)
        self.background = True
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('https://cterm.example.test/?token=', result.stdout)
        meta = json.loads((core.STATE / 'server.json').read_text())
        self.assertEqual(meta['base_url'], 'https://cterm.example.test')
        # The reserved example hostname does not need to resolve: readiness is local.
        url = await asyncio.to_thread(subprocess.run, command + ['url'], env=self.env, capture_output=True, text=True, timeout=8)
        self.assertTrue(url.stdout.startswith('https://cterm.example.test/?token='))

    async def test_bridge_stop_restart_preserves_terminal(self):
        await self.client.close()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        def cli(*args):
            result = subprocess.run([sys.executable, str(core.ROOT / 'control.py'), *args],
                                    env=self.env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return result.stdout
        await asyncio.to_thread(cli, 'start', '--bind', '127.0.0.1', '--port', str(port))
        self.background = True
        self.assertIn('running', await asyncio.to_thread(cli, 'status'))
        await asyncio.to_thread(cli, 'stop')
        self.background = False
        self.assertIsNotNone(core.live_pane(self.pane))
        core.send_text(self.key, self.command("print('ALIVE_AFTER_SERVER_STOP')"), True)
        await asyncio.sleep(.4)
        self.assertIn('ALIVE_AFTER_SERVER_STOP', core.snapshot(self.key)['text'])
        await asyncio.to_thread(cli, 'start', '--bind', '127.0.0.1', '--port', str(port))
        self.background = True
        self.assertEqual(core.registry()[self.key]['name'], '공유 테스트')
        await asyncio.to_thread(cli, 'stop')
        self.background = False
        self.assertIsNotNone(core.live_pane(self.pane))

if __name__ == '__main__':
    unittest.main(verbosity=2)
