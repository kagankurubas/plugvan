"""
Tests that every in-page link in README.md (`[text](#x)` or `href="#x"`) points at a heading, so it
works on GitHub and on PyPI. PyPI's renderer strips `<a name="...">` targets, so headings are the
only anchors both sites keep. A heading's slug: lower-case it, keep letters, combining marks and
digits (Unicode categories L, M, N), spaces, `-` and `_`, drop everything else, then turn each
space into `-`. This reads GitHub's documented rule (letters to lower case, spaces to hyphens, other
punctuation removed) in Unicode terms. It matches the heading ids readme_renderer 46.0's comrak
produces, verified locally: non-ASCII letters stay (`Türkçe` -> `türkçe`),
an emoji goes but its variation selector U+FE0F stays, and `İ` lower-cases to `i` + U+0307, which
stays. GitHub's own ids for headings with emoji, variation selectors or `İ` were not verified.
A heading that a link targets is therefore limited to the characters both renderers are known to
treat alike, checked on the lower-cased heading: letters, digits, spaces, `-`, `_` and `/`.
Fenced code blocks are skipped (a `# comment` in a bash block is not a heading).
"""

import re
import unicodedata
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
    kept = (c for c in heading.strip().lower() if unicodedata.category(c)[0] in "LMN" or c in " -_")
    return "".join(kept).replace(" ", "-")


def link_target_problem(heading: str) -> str | None:
    """Why `heading` cannot be a link target, or None if it can."""
    lowered = heading.lower()
    if any(unicodedata.category(c).startswith("M") for c in lowered) and LINK_TARGET_HEADING.fullmatch(heading):
        return (
            "lower-casing it gives combining marks (e.g. 'İ' -> 'i' + U+0307), "
            "outside the characters both renderers are known to treat alike"
        )
    if not LINK_TARGET_HEADING.fullmatch(lowered):
        return "only letters, digits, spaces, '-', '_' and '/' are allowed"
    return None


def _prose() -> str:
    return split_fenced(README.read_text(encoding="utf-8"))[1]


def _fragments(prose: str) -> list[str]:
    return [fragment for pattern in FRAGMENT_LINKS for fragment in pattern.findall(prose)]


def test_github_slug_rule():
    assert github_slug("English") == "english"
    assert github_slug("Türkçe") == "türkçe"
    assert github_slug("Architecture / Mimari") == "architecture--mimari"
    assert github_slug("Run from a clone (contributors)") == "run-from-a-clone-contributors"
    assert github_slug("snake_case-name") == "snake_case-name"


def test_github_slug_keeps_combining_marks():
    assert github_slug("İçerik") == "i̇çerik"  # "İ".lower() is "i" + U+0307 COMBINING DOT ABOVE
    assert github_slug("🛠️ Usage") == "️-usage"  # the emoji goes, its variation selector (Mn) stays


def test_link_target_heading_rule():
    for heading in ("English", "Türkçe", "Architecture / Mimari", "Tests / Testler"):
        assert link_target_problem(heading) is None, heading
    for heading in ("🛠️ Usage", "Tests️", "Usage!", "License (MIT)", " Tests"):
        assert link_target_problem(heading) == "only letters, digits, spaces, '-', '_' and '/' are allowed", heading
    assert link_target_problem("İçerik") == (
        "lower-casing it gives combining marks (e.g. 'İ' -> 'i' + U+0307), "
        "outside the characters both renderers are known to treat alike"
    )


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
        (heading, problem) for heading in HEADING.findall(prose)
        if github_slug(heading) in targets and (problem := link_target_problem(heading))
    ]
    assert not offending, offending
