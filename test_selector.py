"""Exercise the real curses picker under a PTY with isolated tmux terminals."""
import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path
import core


class SelectorTest(unittest.TestCase):
    def setUp(self):
        self.old_state, self.old_socket = core.STATE, core.SOCKET
        self.temp = tempfile.TemporaryDirectory(prefix='cterm-picker-')
        core.STATE = Path(self.temp.name)
        core.SOCKET = str(core.STATE / 'tmux.sock')
        self.env = {**os.environ, 'CTERM_STATE': self.temp.name, 'TMUX_TMPDIR': self.temp.name,
                    'TERM': 'xterm-256color', 'LC_ALL': 'C.UTF-8'}
        self.env.pop('TMUX', None)
        for name in ('alpha', 'beta', 'gamma'):
            core.tmux(core.SOCKET, '-f', str(core.ROOT / 'tmux.conf'), 'new-session', '-d',
                      '-s', name, '--', '/bin/bash', '--noprofile', '--norc')
        self.panes = {p['session']: p for p in core.panes(core.SOCKET)}

    def tearDown(self):
        core.tmux(core.SOCKET, 'kill-server', check=False)
        core.STATE, core.SOCKET = self.old_state, self.old_socket
        self.temp.cleanup()

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(core.ROOT / 'control.py'), *args],
                                env=self.env, capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def picker(self, action, keys):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 20, 100, 0, 0))
        before = termios.tcgetattr(slave)[3]
        proc = subprocess.Popen([sys.executable, str(core.ROOT / 'control.py'), action],
                                stdin=slave, stdout=slave, stderr=slave, env=self.env,
                                start_new_session=True, pass_fds=(slave,),
                                preexec_fn=lambda: fcntl.ioctl(slave, termios.TIOCSCTTY, 0))
        output = b''
        sent = False
        deadline = time.monotonic() + 8
        try:
            while time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    output += os.read(master, 65536)
                if not sent and b'Enter' in output:
                    os.write(master, keys)
                    sent = True
                if proc.poll() is not None:
                    break
            self.assertTrue(sent, output.decode('utf-8', 'replace'))
            self.assertEqual(proc.wait(timeout=2), 0, output.decode('utf-8', 'replace'))
            mask = termios.ICANON | termios.ECHO | termios.ISIG
            self.assertEqual(termios.tcgetattr(slave)[3] & mask, before & mask,
                             'Picker must restore terminal input mode')
            return output.decode('utf-8', 'replace')
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()
            os.close(master); os.close(slave)

    def test_register_down_enter_selects_second_terminal(self):
        self.picker('register', b'\x1bOB\r')
        entries = list(core.registry().values())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['session'], 'beta')

    def test_unregister_down_enter_and_direct_parameters(self):
        first = core.register(self.panes['alpha'])
        second = core.register(self.panes['beta'])
        self.picker('unregister', b'\x1bOB\r')
        self.assertEqual(set(core.registry()), {first})
        self.assertIsNotNone(core.live_pane(self.panes['beta']))
        self.cli('unregister', 'alpha')
        self.assertEqual(core.registry(), {})
        self.cli('register', '--pane', self.panes['gamma']['pane'], '--name', '기존방식')
        key = next(iter(core.registry()))
        self.cli('unregister', key)
        self.assertEqual(core.registry(), {})
        self.assertIsNotNone(core.live_pane(self.panes['gamma']))

    def test_escape_cancels_without_mutation(self):
        self.picker('register', b'\x1b')
        self.assertEqual(core.registry(), {})
        key = core.register(self.panes['alpha'])
        self.picker('unregister', b'\x1b')
        self.assertEqual(set(core.registry()), {key})
        self.assertIsNotNone(core.live_pane(self.panes['alpha']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
