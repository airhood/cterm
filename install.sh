#!/bin/sh
set -eu
if [ "$(uname -s)" != Linux ]; then
    printf '%s\n' 'cterm currently supports Linux hosts only.' >&2
    exit 1
fi
CTERM_ROOT=$(CDPATH= cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)
CTERM_PYTHON=${CTERM_PYTHON:-python3}
CTERM_BIN_DIR=${CTERM_BIN_DIR:-"$HOME/.local/bin"}
if [ "${1:-}" = '--help' ]; then
    printf '%s\n' 'Usage: ./install.sh' 'Optional: CTERM_PYTHON=python3 CTERM_BIN_DIR=$HOME/.local/bin ./install.sh'
    exit 0
fi
if [ "$#" -ne 0 ]; then
    printf '%s\n' 'Unexpected argument. Run ./install.sh --help.' >&2
    exit 1
fi
if ! command -v "$CTERM_PYTHON" >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.10 or later is required.' >&2
    exit 1
fi
"$CTERM_PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or later is required"; import curses, venv'
if ! command -v tmux >/dev/null 2>&1 && [ ! -x "$CTERM_ROOT/vendor/root/usr/bin/tmux" ]; then
    printf '%s\n' 'tmux is required. On Debian/Ubuntu: sudo apt install tmux' >&2
    exit 1
fi
mkdir -p "$CTERM_BIN_DIR"
CTERM_TARGET="$CTERM_BIN_DIR/cterm"
if [ -e "$CTERM_TARGET" ] || [ -L "$CTERM_TARGET" ]; then
    if [ "$(readlink -f -- "$CTERM_TARGET")" != "$CTERM_ROOT/cterm" ]; then
        printf '%s\n' "Refusing to replace an existing command: $CTERM_TARGET" >&2
        exit 1
    fi
fi
"$CTERM_PYTHON" -m venv "$CTERM_ROOT/.venv"
"$CTERM_ROOT/.venv/bin/python" -m pip install -r "$CTERM_ROOT/requirements.txt"
chmod +x "$CTERM_ROOT/cterm"
ln -sfn "$CTERM_ROOT/cterm" "$CTERM_TARGET"
printf '\n%s\n' "Installed: $CTERM_TARGET" 'Next: cterm new work' '      cterm attach work' '      cterm start'
case ":$PATH:" in
    *":$CTERM_BIN_DIR:"*) ;;
    *) printf '%s\n' "Add this directory to your PATH: $CTERM_BIN_DIR" ;;
esac
