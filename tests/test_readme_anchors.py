"""
Tests that every in-page link in README.md (`[text](#x)` or `href="#x"`) points at a heading, so it
works on GitHub and on PyPI. PyPI's renderer strips `<a name="...">` targets, so headings are the
only anchors both sites keep. A heading's slug follows GitHub's rule: lower-case it, delete every
character that is not a letter, digit, space, `-` or `_`, then turn each space into `-`. Headings
are kept short and ASCII so the slug is the same on both renderers. Fenced code blocks are skipped
(a `# comment` in a bash block is not a heading).
"""

import re
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"
FENCED_BLOCK = re.compile(r"^```.*?^```$", re.MULTILINE | re.DOTALL)
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
FRAGMENT_LINKS = (
    re.compile(r"\]\(\s*#([^)\s]*)\)"),  # [text](#fragment)
    re.compile(r"""\bhref\s*=\s*["']#([^"']*)["']""", re.IGNORECASE),  # <a href="#fragment">
)


def github_slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _prose() -> str:
    return FENCED_BLOCK.sub("", README.read_text(encoding="utf-8"))


def test_github_slug_rule():
    assert github_slug("English") == "english"
    assert github_slug("Run from a clone (contributors)") == "run-from-a-clone-contributors"
    assert github_slug("Architecture & Data Flow") == "architecture--data-flow"


def test_no_html_name_anchors():
    offending = re.findall(r"<a\s[^>]*\bname\s*=[^>]*>", _prose(), re.IGNORECASE)
    assert not offending, offending


def test_every_fragment_link_targets_a_heading_slug():
    prose = _prose()
    slugs = {github_slug(heading) for heading in HEADING.findall(prose)}
    fragments = [fragment for pattern in FRAGMENT_LINKS for fragment in pattern.findall(prose)]
    assert fragments
    missing = [fragment for fragment in fragments if fragment not in slugs]
    assert not missing, (missing, sorted(slugs))
