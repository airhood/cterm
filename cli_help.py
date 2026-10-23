"""Concise overview and task-oriented command help, without terminal styling."""
import argparse

OVERVIEW = '''cterm - Share a terminal between your PC and phone.

Usage: cterm <command> [options]

Quick start
  cterm new work          Create a shared shell
  cterm attach            Pick a terminal to open on your PC
  cterm tunnel start      Get a public HTTPS link without a VPN app
  cterm start             Or use direct private access with Tailscale

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
  tunnel start|stop|status Connect with Cloudflare (no phone VPN required)

More help
  cterm help <command>    Show options and examples for a command
  cterm help new          Example: how to start a terminal program

NAME is a name you choose, such as work or api.
Tip: Ctrl-B, then D detaches the PC view without stopping the terminal.
'''

DETAILS = {
    'start': (
        'Start the background bridge and print your private phone access link.',
        '''Examples:
  cterm start
  cterm start --bind 127.0.0.1       Local testing only
  cterm start --port 9000
  cterm start --base-url https://cterm.example.com

The default address is your Tailscale IPv4 address, or localhost if unavailable.
Your phone must be on the same tailnet. To change an existing listener, run
cterm stop first, then start it with the new options.
--base-url only sets the browser link and Secure cookies. Configure DNS, a
trusted HTTPS certificate, and a reverse proxy separately; see deploy/README.md.'''),
    'stop': (
        'Stop the web bridge. Your terminal sessions and jobs keep running.',
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
If the bridge is stopped, run cterm tunnel start or cterm start first.'''),
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

Next: cterm attach to pick a terminal on your PC, then cterm tunnel start for
browser-only phone access (or cterm start for Tailscale access).
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
        'Connect through Cloudflare Tunnel. Your phone only needs a browser.',
        '''Examples:
  cterm tunnel start                     Get a temporary HTTPS URL
  cterm url --qr                          Scan the current private access link
  cterm tunnel start --hostname term.example.com
  cterm tunnel start --hostname term.example.com --api-token-file /path/to/cloudflare.ini
  cterm tunnel status
  cterm tunnel stop

Without --hostname, no account or domain is needed. The URL changes each time
the tunnel starts. Quick Tunnels are for development and have no uptime guarantee.
cloudflared is downloaded from Cloudflare's official GitHub release if missing;
its SHA-256 digest is verified and it is installed in your private state directory.

For your own domain, use a subdomain in a Cloudflare DNS zone. On first setup,
provide an API token file (chmod 600), or enter the token at the hidden prompt.
Permissions: Account / Cloudflare Tunnel / Edit; Zone / DNS / Edit;
Zone / Zone / Read. Scope the token to your account and domain.
An INI file with dns_cloudflare_api_token = TOKEN or a raw token is accepted.
Existing DNS is preserved unless you explicitly use --replace-dns for a single
A/CNAME record. Other record combinations must be resolved manually.

The bridge listens on localhost with Secure authentication cookies. Existing
terminal jobs stay alive. cterm tunnel stop stops both connector and bridge;
saved domain tunnels and DNS remain for reuse. Processes end on host reboot;
run cterm tunnel start again. See deploy/TUNNEL.md for setup and cleanup.'''),
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
