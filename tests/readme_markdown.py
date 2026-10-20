"""
Fenced code blocks in Markdown, as CommonMark reads them, for the README tests. A fence is three or
more backticks or tildes, indented by at most three spaces; a backtick fence's info string cannot
contain a backtick. The block ends at a line of the same character, at least as long, with nothing
after it but spaces. An unclosed block runs to the end of the text. The info string is what
follows the opening fence; its first word, lower-cased, is the block's language.

Known limits (the README does not use these forms today):
- A fence inside a blockquote (`> ```mermaid`) or inside a list item indented by four or more
  spaces is not recognized; its lines count as prose.
- The README tests built on this module do not apply GitHub's `-1`/`-2` suffixes for duplicate
  heading slugs, and read only ATX headings (`## Title`), not Setext headings (underlined).
"""

import re

OPENING_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def info_language(info: str) -> str:
    """The first word of a fence's info string, lower-cased (`PowerShell` -> `powershell`), or ''."""
    words = info.split(maxsplit=1)
    return words[0].lower() if words else ""


def split_fenced(text: str) -> tuple[list[tuple[str, str]], str]:
    """(fenced blocks as (info string, body), the text outside them with each block's lines removed)."""
    blocks, prose, current = [], [], None  # current: (fence, info, body lines)
    for line in text.splitlines():
        if current is None:
            opening = OPENING_FENCE.match(line)
            # a backtick fence's info string cannot contain a backtick
            if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
                current = (opening.group(1), opening.group(2).strip(), [])
            else:
                prose.append(line)
        elif re.fullmatch(rf" {{0,3}}{re.escape(current[0][0])}{{{len(current[0])},}}[ \t]*", line):
            blocks.append((current[1], "\n".join(current[2])))
            current = None
        else:
            current[2].append(line)
    if current is not None:
        blocks.append((current[1], "\n".join(current[2])))
    return blocks, "\n".join(prose)
