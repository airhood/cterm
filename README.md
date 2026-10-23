# cterm

**Share selected terminal sessions with your phone. Keep working from your PC.**

cterm connects a mobile browser to explicitly shared tmux panes over your private Tailscale network. Your PC and phone operate the same running terminal. No desktop sharing, cloud workspace, or application-specific integration is required.

Use it with a regular shell, Codex CLI, Claude Code, Python, or another terminal program. Start and stop the web bridge independently: your terminal jobs keep running when the bridge stops or your phone disconnects.

```text
PC terminal ─────── tmux pane ─────── cterm bridge ─────── phone browser
                       │                  │
                persistent job      Tailscale + token
```

## Requirements

- A **Linux host** with Python **3.10+**, Python's `venv` and `curses` modules, and **tmux 3.3+**. Development has been tested on Ubuntu 24.04 with tmux 3.4.
- Tailscale on the host and your phone, connected to the same tailnet, for remote access. Localhost-only operation is also supported.
- A modern mobile or desktop browser. The phone does not need Python, tmux, or a terminal app.
- Git to clone the repository. Node.js is only needed for the frontend tests.

Native macOS and Windows hosts are not currently supported. Android and iOS browsers can act as clients; physical-device browser testing is still limited.

## Install

On Debian or Ubuntu, install the host prerequisites:

```sh
sudo apt update
sudo apt install git python3 python3-venv tmux
```

Install and connect Tailscale on your devices using the [official Tailscale instructions](https://tailscale.com/download). Then clone cterm and run its user-local installer:

```sh
git clone https://github.com/airhood/cterm.git
cd cterm
./install.sh
```

The installer creates a `.venv` inside the checkout, installs the Python dependencies there, and links `~/.local/bin/cterm` to this checkout. It does not install system packages, change your shell startup files, or start a service. Keep the checkout in place while using it.

If `cterm` is not on your PATH, add this line to your shell configuration, then open a new shell:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

You can also run `./cterm` directly. To select another Python interpreter or command directory:

```sh
CTERM_PYTHON=python3.12 CTERM_BIN_DIR="$HOME/.local/bin" ./install.sh
```

## Quick start

Create a persistent, shared shell and attach to it on your PC:

```sh
cterm new work
cterm attach
```

**work** is an example name that you choose, not a command keyword. Use any descriptive name, such as `api` or `experiments`. Running `cterm attach` opens an arrow-key picker of running shared terminals; choose one and press Enter. You can still attach directly with `cterm attach work`.

Inside that shell, run your usual commands or CLI application. Press **Ctrl-B**, release both keys, then press **D** to detach the PC view while leaving the job running.

Start the web bridge from another terminal:

```sh
cterm start
```

Open the printed private access link on your phone, with Tailscale connected. Select **work** to view its screen and send input. Reattach from the PC at any time with `cterm attach work`.

To open the link without typing or copying it, display a QR code on your PC:

```sh
cterm url --qr
```

Scan it with your phone camera while connected to Tailscale. The QR code contains the same access token as the link, so keep both private. `cterm url` still prints only the link.

To run a program directly instead of starting a shell:

```sh
cterm new --cwd /path/to/project coding -- codex
cterm new --cwd /path/to/project assistant -- claude
cterm new --cwd /path/to/project job -- python3 script.py
```

`--cwd` must appear **before the terminal name**. The program runs with your existing host credentials, environment, and application settings.

## Select terminals interactively

```sh
cterm register
```

The terminal picker lists discoverable tmux panes and marks panes that are already shared:

- **Up / Down**: move the selection.
- **Enter**: share the selected pane.
- **Esc** or **Q**: cancel.
- **R**: refresh the list.
- **Home / End** and **Page Up / Page Down**: navigate longer lists.

The picker discovers cterm's own tmux server, the default tmux server, and the current tmux socket when launched from inside tmux.

To unshare a terminal, use the corresponding picker:

```sh
cterm unregister
```

It lists only registered panes, including panes whose programs have exited. Unsharing disconnects their browser viewers and removes them from the phone's list. **It does not terminate the terminal or its job.**

You can still specify a name or registration ID directly:

```sh
cterm unregister work
cterm unregister <registration-id>
```

### Register an existing tmux pane by ID

```sh
cterm available
cterm register --source default --pane '%0' --name existing-work
cterm register --source local --pane '%1' --name another-job
cterm register --source /path/to/tmux.sock --pane '%2'
```

`local` means cterm's private tmux server. `default` means the standard tmux server. Each registration grants the browser access to one pane. A terminated pane's replacement is not automatically shared, even if it reuses the same name.

**An already-running program in an ordinary terminal cannot be imported into tmux by cterm.** Start new work with `cterm new`, or start it inside tmux first. To resume an existing coding conversation in a new shared terminal, first let its original CLI release it, then run, for example:

```sh
cterm new coding -- codex resume <conversation-id>
```

## Help

Run `cterm` or `cterm help` for a grouped command overview and a three-step quick start. Command-specific help includes options, examples, and what happens to running jobs.

```sh
cterm help           # All commands
cterm help register  # Help for a specific command
cterm --help         # Equivalent standard option
cterm register --help
```

## Clean up terminals and reuse names

`unregister` only disables sharing: a running tmux job remains alive. To finish a job and remove its terminal, use:

```sh
cterm delete               # Pick a terminal to close and clean up
cterm delete work          # Choose by name; confirms before closing a running job
cterm delete work --yes    # Explicitly confirm for non-interactive use
```

The delete picker includes registered terminals **and unshared panes on cterm's own tmux server**, so jobs left behind by `unregister` can still be cleaned up. Unregistered panes on unrelated tmux servers are not included.

Deletion closes the selected pane and removes its matching registration. The session disappears when its last pane closes, and the private tmux server exits when it has no sessions left. Other panes keep running. Programs deliberately detached or daemonized from their terminal may continue independently. A stale registration is removed without closing a replacement job that reused its pane ID.

Terminal names are never silently overwritten. If `cterm new work` reports that `work` is already in use, reuse the existing terminal, choose another name, or run `cterm delete work` before creating it again. Display names for shared panes must also be unique. Deleting an exited entry only cleans up the registration; deleting a running job may lose unsaved work.

The web bridge, access token, and global configuration are independent of an individual terminal and remain available after deletion.

## Bridge commands

| Command | Behavior |
| --- | --- |
| `cterm help [COMMAND]` | Show general or command-specific help. |
| `cterm start` | Start the background web bridge and print its access link. |
| `cterm stop` | Stop only the web bridge; terminal jobs keep running. |
| `cterm status` | Show bridge status, registration counts, and the state directory. |
| `cterm url [--qr]` | Print the private access link; add `--qr` to display a scannable QR code. |
| `cterm new NAME -- COMMAND ...` | Create and share a persistent terminal. Omit the command for a login shell. |
| `cterm delete [NAME_OR_ID] [--yes]` | Close a pane and remove its registration; also finds cterm-owned unshared panes. |
| `cterm attach [NAME_OR_ID]` | Pick a running shared terminal, or open one directly by name/ID. |
| `cterm register` | Choose a tmux pane with the interactive picker. |
| `cterm unregister [NAME_OR_ID]` | Unshare via the picker or a direct argument. |
| `cterm list` | List terminal names, state, and programs. Add `--ids` for registration IDs. |
| `cterm available` | List discoverable tmux panes. |

The bridge binds to the host's Tailscale IPv4 address by default. If Tailscale is unavailable, it falls back to localhost and prints a notice. You can choose the bind address and port explicitly:

```sh
cterm start --bind 127.0.0.1 --port 8765  # Local testing only
cterm start --bind <host-tailscale-ip>   # Remote access over the tailnet
```

To change an already-running bridge's address or port, stop it and start it again. Stopping the bridge, closing a browser, or detaching a PC client does not kill tmux jobs. Exiting the shell or application itself does end that terminal. Sessions survive client disconnections, not host shutdowns or reboots.

## Mobile controls

The browser shows the current text screen and a command/message input box. **Enter** sends the text and an Enter key; **Shift+Enter** inserts a newline. IME composition is preserved. Buttons provide arrows, Tab, Escape, Enter, Ctrl-C, and Ctrl-D.

Input is cleared only after the bridge confirms it was forwarded. That confirmation means the input reached tmux, not that the command finished successfully. If a connection drops before confirmation, the input is retained and **never automatically resent**, avoiding accidental duplicate commands. Reconnecting restores the latest screen.

Multiple viewers can connect to the same pane. Their input goes to the same terminal, so coordinate typing when using both the PC and phone.

## Access and security

cterm is a **single-user private terminal bridge**, not a multi-user authorization system. Someone with your access link and network access can control all panes you have registered, with the same account privileges as those terminals. Pane registration is a sharing selection, not an operating-system sandbox.

- Bind addresses are restricted to loopback and Tailscale address ranges. No router port forwarding is needed.
- The access link contains a secret token. Keep it private and out of screenshots, logs, and public issues.
- The token is exchanged for an HTTP-only browser cookie; the token is then removed from the address bar. WebSocket connections enforce the request origin.
- The default HTTP listener relies on **Tailscale's encrypted transport** between tailnet devices. The bridge does not provision HTTPS itself. Use localhost or a correctly configured TLS proxy for other deployments. For your own domain, follow the [private custom-domain guide](deploy/README.md) and use `cterm start --base-url https://cterm.example.com`.
- Tailscale access controls still apply. Do not expose this service through Tailscale Funnel or a public reverse proxy.

For a fresh installation, state is stored in `$XDG_STATE_HOME/cterm`, or `~/.local/state/cterm` when `XDG_STATE_HOME` is unset. Early installations automatically keep using their existing `codex-mobile-terminal` state directory. `cterm status` shows the actual location. Set `CTERM_STATE` to override it; use the same value for every cterm command.

The state directory contains `registry.json`, `token`, `server.json`, `server.log`, and the private tmux socket. The directory is user-only and credential files are created with restrictive permissions. To revoke existing browser access, stop the bridge, remove **only the `token` file** from the displayed state directory, and restart. A new access link will be generated; terminals and registrations remain intact.

## Current limitations

- Only the current **plain-text screen** is synchronized. Colors, complete scrollback, images, and a full browser terminal emulator are not implemented.
- The browser preserves the tmux pane's dimensions instead of resizing the PC terminal to match the phone. Wide output scrolls horizontally.
- New terminals and registrations are managed on the host, not from the phone.
- Full-screen applications can be viewed as text, but not every keyboard shortcut or terminal feature is available in the browser.
- There is no automatic start on login or reboot. Use `cterm start` when you want remote access.

## Update or uninstall

Update the checkout and its isolated Python environment, then reload the bridge:

```sh
cterm stop
git pull --ff-only
./install.sh
cterm start
```

To remove the command, stop the bridge and unlink `~/.local/bin/cterm` (or the custom command location you chose). Removing the checkout removes the application and its virtual environment. Terminal state lives separately: do not delete its state directory while tmux sessions are still running. Unsharing a terminal alone never deletes or stops it.

## Development and tests

```sh
./install.sh
.venv/bin/python -m unittest -v test_bridge.py test_selector.py
node test_ui.js
```

The tests create isolated temporary tmux servers and PTYs. They cover authentication, registration visibility, bidirectional input, split UTF-8 output, Ctrl-C, disconnect/reconnect, multiple viewers, immediate unsharing, stale pane identities, bridge stop/restart persistence, arrow-key selection, cancellation, direct-argument compatibility, and terminal-mode restoration. The JavaScript tests exercise Enter, IME composition, delivery acknowledgments, and disconnected input retention.

CI runs on Linux. Browser behavior on physical Android/iOS devices still needs broader testing.

## License

[MIT](LICENSE). Python dependencies and a system-installed tmux retain their own licenses. Downloaded local tools and runtime state are not included in the repository.
