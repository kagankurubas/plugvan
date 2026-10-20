"""
Tests that README.md reads the same on GitHub and on PyPI, where it is the package's long
description. PyPI does not render GitHub-only syntax: a mermaid block shows as raw code, an alert
(`> [!CAUTION]`) as a quote with a literal marker, and a relative link or image path points nowhere.
Fenced code blocks are not checked for links, since their text is shown verbatim.
"""

import re
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"
ABSOLUTE_TARGET = re.compile(r"^(https?://|mailto:|#)")
FENCED_BLOCK = re.compile(r"^```.*?^```$", re.MULTILINE | re.DOTALL)
LINK_TARGETS = (
    re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)"),  # inline link or image: [text](target), ![alt](target)
    re.compile(r"^\s*\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.MULTILINE),  # reference definition: [id]: target
    re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']*)["']""", re.IGNORECASE),  # HTML <a href>, <img src>
)


def _text() -> str:
    return README.read_text(encoding="utf-8")


def test_no_mermaid_block():
    offending = re.findall(r"^[ \t]*```[ \t]*mermaid\b.*$", _text(), re.MULTILINE | re.IGNORECASE)
    assert not offending, offending


def test_no_github_alert_marker():
    offending = re.findall(r"^[ \t]*>[ \t]*\[!\w+\].*$", _text(), re.MULTILINE)
    assert not offending, offending


def test_every_link_and_image_target_is_absolute_or_an_anchor():
    prose = FENCED_BLOCK.sub("", _text())
    targets = [target for pattern in LINK_TARGETS for target in pattern.findall(prose)]
    assert targets
    relative = [target for target in targets if not ABSOLUTE_TARGET.match(target)]
    assert not relative, relative
