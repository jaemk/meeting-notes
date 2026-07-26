#!/usr/bin/env python3
"""
Fill a prompt template in and write it to stdout.

`analyze.md` and friends carry @AUDIO@ / @TRANSCRIPT@ placeholders that name
the files Claude is being asked to look at. Those names come from the outside
world — a recording is whatever the phone, the download or the AirDrop called
it — so the one thing this must never do is let a filename become *code*.

Hence two rules, and they are the whole point of this module existing rather
than a `sed` line in the Makefile:

  * the values are read from the environment (MN_AUDIO, MN_TRANSCRIPT), never
    spliced into the text of a program the way a `sed -e 's|@AUDIO@|...|'`
    splices them into a sed script. A name containing an apostrophe or a
    semicolon used to end the sed expression and start a shell command; there
    is no expression here for it to end.
  * substitution is a literal scan, not a regular expression, so a value
    cannot be read as a pattern, a backreference or a replacement escape.

The scan is single-pass: a value that happens to contain @TRANSCRIPT@ is
copied out as-is rather than substituted a second time.
"""

import os
import sys
from pathlib import Path

# placeholder in the template → environment variable holding its value
PLACEHOLDERS = {
    "@AUDIO@": "MN_AUDIO",
    "@TRANSCRIPT@": "MN_TRANSCRIPT",
}


def render(text, values):
    """
    Replace each placeholder in `text` with its value from `values`, in one
    left-to-right pass. Everything else — including whatever the values
    themselves contain — is copied through byte for byte.
    """
    out, i = [], 0
    while True:
        hits = [(pos, ph) for ph, pos in
                ((ph, text.find(ph, i)) for ph in values) if pos >= 0]
        if not hits:
            out.append(text[i:])
            return "".join(out)
        pos, ph = min(hits)
        out.append(text[i:pos])
        out.append(values[ph])
        i = pos + len(ph)


def die(message):
    print(message, file=sys.stderr)
    sys.exit(2)


def main(argv=None, env=None, out=None):
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    out = sys.stdout if out is None else out

    if len(argv) != 1:
        die("usage: prompt.py <template>   "
            "(values come from $MN_AUDIO and $MN_TRANSCRIPT)")

    path = Path(argv[0])
    try:
        text = path.read_text()
    except OSError as exc:
        # A missing or unreadable template is an ordinary mistake, not a bug,
        # so it gets a sentence rather than a traceback.
        die(f"prompt.py: cannot read template '{path}': "
            f"{exc.strerror or exc}")

    values = {}
    for placeholder, var in PLACEHOLDERS.items():
        if placeholder not in text:
            continue
        value = env.get(var, "")
        if not value:
            die(f"prompt.py: '{path}' uses {placeholder} but ${var} is unset — "
                f"refusing to write a prompt that names no file")
        values[placeholder] = value

    out.write(render(text, values))


if __name__ == "__main__":
    main()
