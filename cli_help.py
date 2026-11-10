"""Concise overview and task-oriented command help, without terminal styling."""
import argparse

OVERVIEW = '''cterm - Share a terminal between your PC and phone.

Usage: cterm <command> [options]

Quick start
  cterm new work          Create a shared shell
  cterm attach            Pick a terminal to open on your PC
  cterm tunnel --quick    Choose temporary HTTPS access (one-time setup)
  cterm start             Start using your saved connection settings

Terminals
  new NAME [-- COMMAND]   Create a persistent terminal and share it
  attach [NAME]           Pick a shared terminal to open           [TUI]
  delete [NAME]           Close a terminal and clean up its entry  [TUI]

Sharing
  register                Pick a running tmux pane to share       [TUI]
  unregister [NAME]       Pick a shared pane to unshare            [TUI]
  list                    Show shared terminals
  available               Show tmux panes you can share

Bridge
  start                   Turn on phone access (runs in the background)
  stop                    Turn off phone access; keep terminals running
  status                  Show bridge and terminal status
  url [--qr]              Show your phone access link, optionally as a QR code
  tunnel [HOSTNAME]       Save a domain, or show saved tunnel settings

More help
  cterm help <command>    Show options and examples for a command
  cterm help new          Example: how to start a terminal program

NAME is a name you choose, such as work or api.
Tip: Ctrl-B, then D detaches the PC view without stopping the terminal.
'''

DETAILS = {
    'start': (
        'Start the bridge and any saved tunnel, then print your private access link.',
        '''Examples:
  cterm start
  cterm start --bind 127.0.0.1       Local testing only
  cterm start --port 9000
  cterm start --base-url https://cterm.example.com

With a saved tunnel, this starts both the localhost bridge and Cloudflare.
Use cterm tunnel HOSTNAME or cterm tunnel --quick to save your choice once.
Without a tunnel setting, the default is direct Tailscale access, or localhost
if unavailable. Use cterm tunnel --off before choosing --bind or --base-url.
To change an existing listener, run cterm stop before starting it again.
--base-url only sets the browser link and Secure cookies. Configure DNS, a
trusted HTTPS certificate, and a reverse proxy separately; see deploy/README.md.'''),
    'stop': (
        'Stop the bridge and tunnel. Keep saved settings and terminal jobs.',
        '''Example:
  cterm stop

Use cterm start to restore phone access. No terminal processes are terminated.'''),
    'status': (
        'Show whether the bridge is running and how many terminals are shared.',
        '''Example:
  cterm status

Also prints the state directory containing the registry, token, and server log.'''),
    'url': (
        'Print the private browser link for the running bridge.',
        '''Examples:
  cterm url
  cterm url --qr     Also show a QR code to scan with your phone camera

Open the link on your phone. Direct Tailscale links require a tailnet connection;
Cloudflare Tunnel links do not. Keep this link private.
The QR code contains the same private access link; keep it private too.
If the bridge is stopped, run cterm start first.'''),
    'list': (
        'Show shared terminals by name, state, and running program.',
        '''Examples:
  cterm list          Show names, state, and running programs
  cterm list --ids    Also include registration IDs

Use cterm attach to choose a terminal with arrow keys. Names and IDs are both
accepted for direct attach/unregister. Use cterm available for unshared panes.'''),
    'available': (
        'List tmux panes that you can register for phone access.',
        '''Example:
  cterm available

Shows the source, pane ID, session, and running program for each pane.
To select one interactively, run cterm register.'''),
    'new': (
        'Create a persistent tmux terminal and add it to your shared list.',
        '''Examples:
  cterm new work                                   Start a login shell
  cterm new coding -- codex                        Start a CLI program
  cterm new --cwd /path/to/project work -- bash     Choose a directory

NAME is a name you choose, such as work, api, or experiments.
Existing names are never overwritten. Use cterm delete to clean up an old one.
Put --cwd before NAME. Everything after NAME (optionally separated by --)
is the program to run and its arguments. Omit the program for a login shell.

Next: cterm attach to pick a terminal on your PC. Choose a connection once with
cterm tunnel --quick or cterm tunnel HOSTNAME, then run cterm start.
Jobs keep running when you detach or stop the bridge; they end on host shutdown.'''),
    'register': (
        'Select an existing tmux pane and add it to your shared terminal list.',
        '''Examples:
  cterm register                                  Open the arrow-key picker
  cterm register --source default --pane '%0'       Share a specific pane
  cterm register --name server                     Choose a display name

Picker: Up/Down to move, Enter to share, Esc to cancel, R to refresh.
Ordinary terminal processes cannot be imported. Start them inside tmux first,
or create a new shared terminal with cterm new NAME.'''),
    'unregister': (
        'Remove phone access to a terminal without stopping its running job.',
        '''Examples:
  cterm unregister                  Pick a shared terminal with arrow keys
  cterm unregister work             Unshare by name
  cterm unregister REGISTRATION_ID  Unshare by ID from cterm list --ids

With no argument, opens the picker: Up/Down to move, Enter to unshare,
Esc to cancel. Connected browser viewers are disconnected for that pane.
The terminal and its job keep running.'''),
    'attach': (
        'Choose a running shared terminal to open on your PC.',
        '''Examples:
  cterm attach                     Open the arrow-key picker
  cterm attach work                Open the terminal named work
  cterm attach REGISTRATION_ID     Open by ID from cterm list --ids

With no argument, choose with Up/Down and Enter. Esc cancels.
Only running shared terminals appear; exited jobs cannot be attached.
NAME is your chosen terminal name, not a command keyword.

Press Ctrl-B, release both keys, then D to detach without stopping the job.
The PC and phone share one terminal.'''),
    'delete': (
        'Close a terminal pane, stop its attached program, and remove its registrations.',
        """Examples:
  cterm delete                  Choose a terminal with arrow keys
  cterm delete work             Delete by name, with confirmation if running
  cterm delete work --yes       Confirm deletion without a prompt

Includes unshared terminals left on cterm's private tmux server after unregister.
Exited registrations are removed without affecting replacement terminals.
Deleting a running terminal can lose unsaved work. Other panes remain running.
The tmux session disappears when its last pane is closed; an empty private
server exits too. The name is then available for a new terminal.

Use cterm unregister to remove phone access while keeping the job alive."""),
    'tunnel': (
        'Save tunnel settings for cterm start. Settings survive stops and reboots.',
        '''Examples:
  cterm tunnel term.example.com          Save your domain
  cterm tunnel --quick                   Save temporary URL mode
  cterm tunnel --off                     Disable tunneling
  cterm tunnel                           Show saved settings
  cterm start                            Start the saved connection
  cterm stop                             Stop it; keep settings and jobs

This command changes settings only. Run cterm start to apply them, or cterm stop
and cterm start if already running. Settings are stored in STATE/tunnel-config.json.
No arguments shows settings. --quick needs no account or domain; its URL changes
each time the tunnel starts. Quick Tunnels have no uptime guarantee.
cloudflared is downloaded from Cloudflare's official GitHub release if missing;
its SHA-256 digest is verified and it is installed in your private state directory.

For your own domain, use a subdomain in a Cloudflare DNS zone. On first start,
provide an API token file (chmod 600), or enter the token at the hidden prompt.
Permissions: Account / Cloudflare Tunnel / Edit; Zone / DNS / Edit;
Zone / Zone / Read. Scope the token to your account and domain.
An INI file with dns_cloudflare_api_token = TOKEN or a raw token is accepted.
Existing DNS is preserved unless you explicitly use --replace-dns for a single
A/CNAME record. Other record combinations must be resolved manually.

Use --api-token-file FILE to save a token file path. No token is stored in the
settings file. --replace-dns allows replacing one record on successful setup,
then resets automatically. Domain credentials and DNS remain for reuse.
Processes end on host reboot; cterm start restores your saved connection.
This does not enable automatic startup at boot. The older tunnel start/stop/status
commands remain supported. See deploy/TUNNEL.md for setup and cleanup.'''),
    'help': (
        'Show the command overview or detailed help for one command.',
        '''Examples:
  cterm help
  cterm help register
  cterm new --help

--help and cterm help COMMAND show the same command-specific help.'''),
}


class HelpParser(argparse.ArgumentParser):
    def __init__(self, *args, overview=False, **kwargs):
        self.overview = overview
        kwargs.setdefault('formatter_class', argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)
        self._positionals.title = 'Arguments'
        self._optionals.title = 'Options'

    def format_help(self):
        return OVERVIEW if self.overview else super().format_help()
