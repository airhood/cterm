"""Isolated connector lifecycle and DNS ownership tests; no Cloudflare account needed."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import core
import tunnel


class TunnelTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cterm-tunnel-test-')
        self.state = Path(self.temp.name)
        self.old_state, self.old_socket = core.STATE, core.SOCKET
        core.STATE, core.SOCKET = self.state, str(self.state / 'tmux.sock')
        self.bin = self.state / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'cloudflared'
        fake.write_text('#!' + sys.executable + '\n'
                        'import os,time\n'
                        'if os.environ.get("CTERM_FAKE_FAIL"): raise SystemExit(1)\n'
                        'print("https://isolated-test.trycloudflare.com",flush=True)\n'
                        'print("Registered tunnel connection",flush=True)\n'
                        'while True: time.sleep(1)\n')
        fake.chmod(0o700)
        self.env = {**os.environ, 'CTERM_STATE': str(self.state),
                    'PATH': str(self.bin) + os.pathsep + os.environ['PATH']}
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.token = self.state / 'cloudflare.ini'
        tunnel.write_private(self.token, 'dns_cloudflare_api_token = fake-private-token\n')

    def tearDown(self):
        self.cli('tunnel', 'stop')
        core.tmux(core.SOCKET, 'kill-server', check=False)
        core.STATE, core.SOCKET = self.old_state, self.old_socket
        self.temp.cleanup()

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(core.ROOT / 'control.py'), *args],
                              env=env or self.env, capture_output=True, text=True, timeout=20)

    def args(self, **kwargs):
        return argparse.Namespace(hostname='term.example.com', api_token_file=str(self.token),
                                  replace_dns=kwargs.get('replace_dns', False))

    def test_quick_lifecycle_preserves_jobs_and_secret(self):
        core.tmux(core.SOCKET, 'new-session', '-d', '-s', 'persistent', 'sleep 60')
        result = self.cli('tunnel', 'start', '--port', str(self.port))
        self.assertEqual(result.returncode, 0, result.stderr)
        bridge = json.loads((self.state / 'server.json').read_text())
        connector = json.loads((self.state / 'tunnel.json').read_text())
        self.assertEqual(bridge['bind'], '127.0.0.1')
        self.assertEqual(bridge['base_url'], 'https://isolated-test.trycloudflare.com')
        self.assertEqual((self.state / 'tunnel.json').stat().st_mode & 0o777, 0o600)
        self.assertNotIn(core.token(), (self.state / 'tunnel.log').read_text())
        again = self.cli('tunnel', 'start')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads((self.state / 'tunnel.json').read_text())['pid'], connector['pid'])
        self.assertEqual(self.cli('stop').returncode, 0)
        resumed = self.cli('tunnel', 'start')
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads((self.state / 'server.json').read_text())['base_url'], bridge['base_url'])
        self.assertEqual(json.loads((self.state / 'tunnel.json').read_text())['pid'], connector['pid'])
        stopped = self.cli('tunnel', 'stop')
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertFalse((self.state / 'server.json').exists())
        self.assertFalse((self.state / 'tunnel.json').exists())
        self.assertEqual([x['session'] for x in core.panes(core.SOCKET)], ['persistent'])

    def test_failed_connector_restores_previous_bridge(self):
        previous = self.cli('start', '--bind', '127.0.0.1', '--port', str(self.port),
                            '--base-url', 'https://previous.example.com')
        self.assertEqual(previous.returncode, 0, previous.stderr)
        failed = self.cli('tunnel', 'start', env={**self.env, 'CTERM_FAKE_FAIL': '1'})
        self.assertEqual(failed.returncode, 1)
        self.assertIn('cloudflared exited', failed.stderr)
        meta = json.loads((self.state / 'server.json').read_text())
        self.assertEqual(meta['base_url'], 'https://previous.example.com')
        self.assertEqual(meta['port'], self.port)
        self.assertFalse((self.state / 'tunnel.json').exists())
        self.assertEqual(self.cli('status').returncode, 0)

    def test_dns_conflict_requires_explicit_replacement_and_retry_reuses_tunnel(self):
        records = [dict(id='record', type='A', content='192.0.2.10')]
        calls = []
        def api(path, data=None, method=None):
            calls.append((path, data, method))
            if path.startswith('zones?'):
                return [dict(id='zone', account={'id': 'account'})]
            if '/dns_records?' in path:
                return records
            if path.endswith('/cfd_tunnel'):
                return dict(id='tunnel', token='private-connector-token')
            if path.endswith('/configurations'):
                return {}
            if path.endswith('/dns_records/record'):
                records[:] = [{**data, 'id': 'record'}]
                return records[0]
            self.fail('Unexpected API request: ' + path)
        client = unittest.mock.Mock()
        client.call.side_effect = api
        with patch.object(tunnel, 'Cloudflare', return_value=client):
            with self.assertRaisesRegex(core.TerminalError, 'DNS already exists'):
                tunnel.prepare_named(self.args(), self.port)
            self.assertFalse(any(p.endswith('/cfd_tunnel') for p, _, _ in calls))
            named, token_file, api_client, dns = tunnel.prepare_named(self.args(replace_dns=True), self.port)
            self.assertFalse(named['dns_ready'])
            self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
            # A retry after interruption uses the cached tunnel, not a new one.
            named, _, api_client, dns = tunnel.prepare_named(self.args(replace_dns=True), self.port)
            self.assertEqual(sum(p.endswith('/cfd_tunnel') for p, _, _ in calls), 1)
            tunnel.publish(named, api_client, dns)
            self.assertEqual(records[0]['type'], 'CNAME')
            self.assertEqual(records[0]['content'], 'tunnel.cfargotunnel.com')
            self.assertTrue(records[0]['proxied'])
            calls.clear()
            cached, _, client, _ = tunnel.prepare_named(self.args(), self.port)
            self.assertTrue(cached['dns_ready'])
            self.assertIsNone(client)
            self.assertEqual(calls, [])

    def test_token_permissions_and_hostname_validation(self):
        self.token.chmod(0o644)
        with self.assertRaisesRegex(core.TerminalError, 'chmod 600'):
            tunnel.api_token(str(self.token))
        for invalid in ('https://term.example.com', 'example.com/path', '../escape', 'a..com', '-bad.example.com'):
            with self.assertRaises(argparse.ArgumentTypeError):
                tunnel.hostname(invalid)
        self.assertEqual(tunnel.hostname('Term.Example.Com.'), 'term.example.com')


if __name__ == '__main__':
    unittest.main()
