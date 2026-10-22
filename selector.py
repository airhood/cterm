"""Keyboard terminal picker using the standard library; no new dependencies."""
import curses
import sys
import unicodedata
import core


def clipped(text, cells):
    out = []
    used = 0
    for char in str(text):
        if unicodedata.category(char).startswith('C'):
            char = ' '
        width = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1)
        if used + width > cells:
            break
        out.append(char)
        used += width
    return ''.join(out)


def select_item(title, load_items, describe, verb):
    """Return one item or None; restore the terminal on cancel and errors."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise core.TerminalError('Run the picker in an interactive terminal. For scripts, specify a name/ID or --pane.')
    items = load_items()
    if not items:
        raise core.TerminalError('No terminals are available to select.')

    def run(window):
        nonlocal items
        window.keypad(True)
        curses.noecho()
        curses.cbreak()
        curses.set_escdelay(35)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        selected = 0
        top = 0
        while True:
            window.erase()
            height, width = window.getmaxyx()

            def write(row, text, attr=0):
                if 0 <= row < height and width > 1:
                    try:
                        window.addstr(row, 0, clipped(text, width - 1), attr)
                    except curses.error:
                        pass

            if height < 7 or width < 28:
                write(0, 'Please enlarge the terminal window.')
                write(height - 1, 'Esc / q: cancel')
            else:
                rows = height - 6
                top = min(top, selected)
                if selected >= top + rows:
                    top = selected - rows + 1
                write(0, title, curses.A_BOLD)
                write(1, f' {selected + 1 if items else 0}/{len(items)} items | Up/Down: move | Enter: {verb} | Esc: cancel')
                for row, index in enumerate(range(top, min(top + rows, len(items))), 3):
                    active = index == selected
                    text = (' > ' if active else '   ') + describe(items[index])
                    write(row, text, curses.A_REVERSE if active else curses.A_NORMAL)
                    if active:
                        cells = sum(0 if unicodedata.combining(c) else (2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1) for c in clipped(text, width - 1))
                        try:
                            window.chgat(row, min(cells, width - 1), max(0, width - 1 - cells), curses.A_REVERSE)
                        except curses.error:
                            pass
                write(height - 2, f'Enter: {verb}  |  Esc / q: cancel  |  R: refresh')
                write(height - 1, 'Sharing or unsharing a terminal does not stop its work.')
            window.refresh()
            try:
                key = window.get_wch()
            except KeyboardInterrupt:
                return None
            if key in ('\x1b', 'q', 'Q', '\x03'):
                return None
            if key == curses.KEY_RESIZE:
                continue
            if key in ('r', 'R'):
                items = load_items()
                selected = min(selected, max(0, len(items) - 1))
                top = 0
            elif key in (curses.KEY_DOWN, 'j') and items:
                selected = min(selected + 1, len(items) - 1)
            elif key in (curses.KEY_UP, 'k') and items:
                selected = max(selected - 1, 0)
            elif key == curses.KEY_HOME:
                selected = 0
            elif key == curses.KEY_END and items:
                selected = len(items) - 1
            elif key == curses.KEY_NPAGE and items:
                selected = min(selected + max(1, height - 6), len(items) - 1)
            elif key == curses.KEY_PPAGE:
                selected = max(selected - max(1, height - 6), 0)
            elif key in ('\n', '\r', curses.KEY_ENTER) and items and height >= 7 and width >= 28:
                return items[selected]

    return curses.wrapper(run)
