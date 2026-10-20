"""
Tests that README.md reads the same on GitHub and on PyPI, where it is the package's long
description. A mermaid block shows as raw code on PyPI, and a relative link or image path points
nowhere there. GitHub alerts (`> [!CAUTION]`) depend on the renderer: readme_renderer 46.0 renders
them as admonitions, and which version pypi.org runs is not verified, so the README uses plain
blockquotes, which look the same on every renderer. Fenced code blocks (``` or ~~~, any length)
are not checked for links or alerts, since their text is shown verbatim.
"""

import re
from pathlib import Path

from tests.readme_markdown import info_language, split_fenced

README = Path(__file__).resolve().parents[1] / "README.md"
ABSOLUTE_TARGET = re.compile(r"^(https?://|mailto:|#)")
LINK_TARGETS = (
    # every `](target)`: a link, an image, and the outer link of a badge `[![alt](img)](target)`
    re.compile(r"\]\(\s*<?([^)\s>]+)"),
    re.compile(r"^\s*\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.MULTILINE),  # reference definition: [id]: target
    re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']*)["']""", re.IGNORECASE),  # HTML <a href>, <img src>
)


def _text() -> str:
    return README.read_text(encoding="utf-8")


def test_no_mermaid_block():
    blocks, _ = split_fenced(_text())
    offending = [info for info, _ in blocks if info_language(info) == "mermaid"]
    assert not offending, offending


def test_no_github_alert_marker():
    _, prose = split_fenced(_text())
    offending = re.findall(r"^[ \t]*>[ \t]*\[!\w+\].*$", prose, re.MULTILINE)
    assert not offending, offending


def test_every_link_and_image_target_is_absolute_or_an_anchor():
    _, prose = split_fenced(_text())
    targets = [target for pattern in LINK_TARGETS for target in pattern.findall(prose)]
    assert targets
    relative = [target for target in targets if not ABSOLUTE_TARGET.match(target)]
    assert not relative, relative
