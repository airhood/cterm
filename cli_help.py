"""Concise overview and task-oriented command help, without terminal styling."""
import argparse

OVERVIEW = '''cterm - Share a terminal between your PC and phone.

Usage: cterm <command> [options]

Quick start
  cterm new work          Create a shared shell
  cterm attach work       Open it on your PC
  cterm start             Get the link to open on your phone

Terminals
  new NAME [-- COMMAND]   Create a persistent terminal and share it
  attach NAME             Open a shared terminal on your PC

Sharing
  register                Pick a running tmux pane to share       [TUI]
  unregister [NAME]       Pick a shared pane to unshare            [TUI]
  list                    Show shared terminals
  available               Show tmux panes you can share

Bridge
  start                   Turn on phone access (runs in the background)
  stop                    Turn off phone access; keep terminals running
  status                  Show bridge and terminal status
  url                     Show your private phone access link

More help
  cterm help <command>    Show options and examples for a command
  cterm help new          Example: how to start a terminal program

Tip: Ctrl-B, then D detaches the PC view without stopping the terminal.
'''

DETAILS = {
    'start': (
        'Start the background bridge and print your private phone access link.',
        '''Examples:
  cterm start
  cterm start --bind 127.0.0.1       Local testing only
  cterm start --port 9000

The default address is your Tailscale IPv4 address, or localhost if unavailable.
Your phone must be on the same tailnet. To change an existing listener, run
cterm stop first, then start it with the new options.'''),
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
        '''Example:
  cterm url

Open the link on your phone with Tailscale connected. Keep this link private.
If the bridge is stopped, run cterm start first.'''),
    'list': (
        'List shared terminals, their registration IDs, and running/exited state.',
        '''Example:
  cterm list

Use a terminal name or registration ID with cterm attach or cterm unregister.
Use cterm available to see panes that have not been shared yet.'''),
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

Put --cwd before NAME. Everything after NAME (optionally separated by --)
is the program to run and its arguments. Omit the program for a login shell.

Next: cterm attach NAME to open it on your PC, then cterm start for phone access.
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
  cterm unregister REGISTRATION_ID  Unshare by ID from cterm list

With no argument, opens the picker: Up/Down to move, Enter to unshare,
Esc to cancel. Connected browser viewers are disconnected for that pane.
The terminal and its job keep running.'''),
    'attach': (
        'Open a shared terminal on your PC, using its name or registration ID.',
        '''Examples:
  cterm attach work
  cterm attach REGISTRATION_ID

Press Ctrl-B, release both keys, then D to detach without stopping the job.
The PC and phone share one terminal. Use cterm list to find names and IDs.'''),
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
