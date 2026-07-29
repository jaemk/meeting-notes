#!/usr/bin/env python3
"""
Checks for glossary.py.

Every spelling in this file is invented. Real ones live only in local/ and
output/, which are gitignored — see CLAUDE.md. That is not incidental to this
suite: a glossary's whole content is proper nouns from a private recording,
so it is the one input in this repo that must never appear in a fixture.
"""

import subprocess
import sys

from testlib import OUTPUT_DIR, ROOT, Checks

import glossary as G

check = Checks()


def rules(text):
    return G.compile_rules(G.parse(text))


check.section("reading a glossary a person typed")

_src = """
# a comment, and a blank line above
Wren Ashby: Ren Ashbee, Wren Ashbee
Thornbury Cove:  Thornberry Cove , Thorn Bury Cove
"""
_map = G.parse(_src)
check("each correct spelling keeps the variants listed for it",
      _map == {"Wren Ashby": ["Ren Ashbee", "Wren Ashbee"],
               "Thornbury Cove": ["Thornberry Cove", "Thorn Bury Cove"]}, _map)
check("comments and blank lines are ignored",
      "#" not in "".join(_map) and len(_map) == 2, _map)
check("whitespace around a variant is not part of it",
      "Thornberry Cove" in _map["Thornbury Cove"], _map["Thornbury Cove"])


def refused(src):
    try:
        G.parse(src)
        return ""
    except G.GlossaryError as e:
        return str(e)


check("a line with no colon is refused, naming the line",
      "line 1" in refused("Wren Ashby Ren Ashbee"),
      refused("Wren Ashby Ren Ashbee"))
check("a correct spelling with no variants is refused as a no-op",
      "never match" in refused("Wren Ashby:"), refused("Wren Ashby:"))
check("nothing before the colon is refused",
      "before the colon" in refused(": Ren Ashbee"), refused(": Ren Ashbee"))
# Both of these would otherwise corrupt every document silently, which is the
# failure mode a hand-written file most invites.
check("listing a spelling as a variant of itself is refused",
      "variant of itself" in refused("Wren Ashby: Wren Ashby"),
      refused("Wren Ashby: Wren Ashby"))
check("one variant meaning two different words is refused, not resolved",
      "cannot also mean" in refused("Wren Ashby: Ren\nRobin Vale: Ren"),
      refused("Wren Ashby: Ren\nRobin Vale: Ren"))
check("the same variant repeated for the same word is harmless",
      refused("Wren Ashby: Ren\nWren Ashby: Ren") == "")
# Whisper's retry path emits unpunctuated lowercase (CLAUDE.md), so fixing the
# case of a proper noun is a real correction, not a self-reference.
check("a variant differing only in case is allowed, being a real correction",
      refused("Wren Ashby: wren ashby") == "",
      refused("Wren Ashby: wren ashby"))
check("and it actually restores the capitals",
      G.apply("wren ashby spoke", rules("Wren Ashby: wren ashby"))[0]
      == "Wren Ashby spoke")

check.section("correcting text without corrupting it")

_r = rules("Wren Ashby: Ren Ashbee, Wren Ashbee\nAl: Hal")
check("a listed variant is replaced with the spelling you asked for",
      G.apply("Ren Ashbee gave the report.", _r)[0]
      == "Wren Ashby gave the report.", G.apply("Ren Ashbee ...", _r))
check("matching ignores case but the replacement does not",
      G.apply("REN ASHBEE spoke.", _r)[0] == "Wren Ashby spoke.",
      G.apply("REN ASHBEE spoke.", _r))
# The reason for \b: a short variant is the common case for a nickname, and a
# substring match would rewrite the inside of unrelated words.
check("a short variant does not match inside a longer word",
      G.apply("Also, halt the halibut.", _r)[0] == "Also, halt the halibut.",
      G.apply("Also, halt the halibut.", _r))
check("but it does match as a whole word",
      G.apply("Sorry, Hal.", _r)[0] == "Sorry, Al.", G.apply("Sorry, Hal.", _r))
check("a possessive keeps its apostrophe and gains the right stem",
      G.apply("Ren Ashbee's boat", _r)[0] == "Wren Ashby's boat",
      G.apply("Ren Ashbee's boat", _r))
check("a variant split across a line break still matches",
      G.apply("Ren\nAshbee spoke", _r)[0] == "Wren Ashby spoke",
      G.apply("Ren\nAshbee spoke", _r))
check("text with nothing to correct is returned unchanged",
      G.apply("the motion carries", _r) == ("the motion carries", {}))
check("an empty glossary changes nothing and raises nothing",
      G.apply("anything at all", G.compile_rules({})) == ("anything at all", {}))

check.section("counting what was changed, so the document can say so")

_text, _counts = G.apply("Ren Ashbee met Wren Ashbee. Hal waved.", _r)
check("every replacement is counted against the correct spelling",
      _counts == {"Wren Ashby": 2, "Al": 1}, _counts)
check("and the text has them all applied",
      _text == "Wren Ashby met Wren Ashby. Al waved.", _text)
check("the one-line summary names each word and its count",
      "Wren Ashby ×2" in G.summarise(_counts), G.summarise(_counts))
check("an empty count says so rather than reading as success",
      G.summarise({}) == "no spellings corrected")

# Python's | takes the leftmost alternative that matches, not the longest, so
# without the length sort "Ren" would win and strand " Ashbee" behind it.
_overlap = rules("Wren Ashby: Ren Ashbee, Ren")
check("a longer variant wins over a shorter one that prefixes it",
      G.apply("Ren Ashbee spoke", _overlap)[0] == "Wren Ashby spoke",
      G.apply("Ren Ashbee spoke", _overlap))
check("and the shorter one still works on its own",
      G.apply("Ren spoke", _overlap)[0] == "Wren Ashby spoke",
      G.apply("Ren spoke", _overlap))

check.section("a correction is never applied twice")
# Running the same glossary over already-corrected text must be a no-op, or a
# re-render would compound. It holds because a correct spelling is not itself
# a variant — which is exactly what parse() refuses to let you write.
_once, _ = G.apply("Ren Ashbee spoke", _r)
_twice, _c2 = G.apply(_once, _r)
check("re-applying to corrected text changes nothing further",
      _twice == _once and _c2 == {}, (_twice, _c2))

check.section("finding and loading a glossary from disk")

_gpath = OUTPUT_DIR / "glossary-test.glossary.txt"
_gpath.write_text("Wren Ashby: Ren Ashbee\n")
check("a glossary names its own recording's stem first",
      G.find(str(OUTPUT_DIR / "glossary-test")) == _gpath,
      G.find(str(OUTPUT_DIR / "glossary-test")))
check("a stem with no glossary anywhere finds nothing rather than guessing",
      G.find(str(OUTPUT_DIR / "glossary-absent")) in (None,)
      or G.find(str(OUTPUT_DIR / "glossary-absent")).name == "glossary.txt",
      G.find(str(OUTPUT_DIR / "glossary-absent")))
check("loading a real file compiles rules that work",
      G.apply("Ren Ashbee", G.load(_gpath))[0] == "Wren Ashby")

_bad = OUTPUT_DIR / "glossary-bad.glossary.txt"
_bad.write_text("this line has no colon\n")
try:
    G.load(_bad)
    _load_refused = ""
except G.GlossaryError as e:
    _load_refused = str(e)
check("a malformed file is refused by load, not just by parse",
      "line 1" in _load_refused, _load_refused)
try:
    G.load(OUTPUT_DIR / "glossary-does-not-exist.txt")
    _missing = ""
except G.GlossaryError as e:
    _missing = str(e)
check("a missing file is refused with the path, not a traceback",
      "can't read" in _missing, _missing)

check.section("the command line, for checking a glossary before trusting it")


def cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "glossary.py"), *args],
                          capture_output=True, text=True)


_r1 = cli(str(_gpath))
check("checking a good glossary exits cleanly and counts it",
      _r1.returncode == 0 and "1 spellings" in _r1.stdout,
      _r1.stdout + _r1.stderr)
_r2 = cli(str(_bad))
check("checking a bad one fails loudly instead of being ignored",
      _r2.returncode != 0 and "Refusing" in (_r2.stdout + _r2.stderr),
      _r2.stdout + _r2.stderr)
_r2b = cli(str(OUTPUT_DIR / "glossary-does-not-exist.txt"))
check("a path that does not exist is refused the same way, not a traceback",
      _r2b.returncode != 0 and "Refusing" in (_r2b.stdout + _r2b.stderr),
      _r2b.stdout + _r2b.stderr)

_t = OUTPUT_DIR / "glossary-test.timestamped.txt"
_t.write_text("[00:00:00.00 --> 00:00:02.00]  Ren Ashbee spoke\n"
              "[00:00:02.00 --> 00:00:04.00]  the motion carries\n")
_r3 = cli(str(_gpath), "--against", str(_t))
check("previewing against a transcript reports what it would change",
      _r3.returncode == 0 and "Wren Ashby" in _r3.stdout, _r3.stdout)

_idle = OUTPUT_DIR / "glossary-idle.glossary.txt"
_idle.write_text("Robin Vale: Robbin Vail\n")
_r4 = cli(str(_idle), "--against", str(_t))
check("a spelling that never fires is reported, since that is how a typo hides",
      "never matched" in _r4.stdout, _r4.stdout)

check.finish()
