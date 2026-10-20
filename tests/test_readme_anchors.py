"""
Tests that every in-page link in README.md (`[text](#x)` or `href="#x"`) points at a heading, so it
works on GitHub and on PyPI. PyPI's renderer strips `<a name="...">` targets, so headings are the
only anchors both sites keep. A heading's slug follows GitHub's rule: lower-case it, delete every
character that is not a letter, digit, space, `-` or `_`, then turn each space into `-`. Letters
include non-ASCII ones (`Türkçe` -> `türkçe`), which both GitHub and readme_renderer's comrak keep.
The renderers differ on emoji and their invisible variation selectors (comrak keeps U+FE0F, the rule
above drops it), so a heading that a link targets may contain only letters, digits, spaces, `-`,
`_` and `/`. Fenced code blocks are skipped (a `# comment` in a bash block is not a heading).
"""

import re
from pathlib import Path

from tests.readme_markdown import split_fenced

README = Path(__file__).resolve().parents[1] / "README.md"
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
LINK_TARGET_HEADING = re.compile(r"[^\W_]([\w \-/]*[^\W_])?")  # letters/digits, then also spaces - _ /
FRAGMENT_LINKS = (
    re.compile(r"\]\(\s*#([^)\s]*)\)"),  # [text](#fragment)
    re.compile(r"""\bhref\s*=\s*["']#([^"']*)["']""", re.IGNORECASE),  # <a href="#fragment">
)


def github_slug(heading: str) -> str:
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _prose() -> str:
    return split_fenced(README.read_text(encoding="utf-8"))[1]


def _fragments(prose: str) -> list[str]:
    return [fragment for pattern in FRAGMENT_LINKS for fragment in pattern.findall(prose)]


def test_github_slug_rule():
    assert github_slug("English") == "english"
    assert github_slug("Türkçe") == "türkçe"
    assert github_slug("Architecture / Mimari") == "architecture--mimari"
    assert github_slug("Run from a clone (contributors)") == "run-from-a-clone-contributors"


def test_link_target_heading_rule():
    for heading in ("English", "Türkçe", "Architecture / Mimari", "Tests / Testler"):
        assert LINK_TARGET_HEADING.fullmatch(heading), heading
    for heading in ("🛠️ Usage", "Tests️", "Usage!", "License (MIT)", " Tests"):
        assert not LINK_TARGET_HEADING.fullmatch(heading), heading


def test_no_html_name_anchors():
    offending = re.findall(r"<a\s[^>]*\bname\s*=[^>]*>", _prose(), re.IGNORECASE)
    assert not offending, offending


def test_every_fragment_link_targets_a_heading_slug():
    prose = _prose()
    slugs = {github_slug(heading) for heading in HEADING.findall(prose)}
    fragments = _fragments(prose)
    assert fragments
    missing = [fragment for fragment in fragments if fragment not in slugs]
    assert not missing, (missing, sorted(slugs))


def test_link_target_headings_use_only_plain_characters():
    prose = _prose()
    targets = set(_fragments(prose))
    offending = [
        heading for heading in HEADING.findall(prose)
        if github_slug(heading) in targets and not LINK_TARGET_HEADING.fullmatch(heading)
    ]
    assert not offending, offending
