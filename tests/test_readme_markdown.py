"""
Tests for tests/readme_markdown.py, the fenced-code-block splitter the README tests share: fence
characters and lengths, the closing-fence rule, indentation, and the info string's language word.
"""

from tests.readme_markdown import info_language, split_fenced


def test_split_fenced_reads_every_fence_kind():
    text = "a\n```mermaid\nx\n```\nb\n~~~ Mermaid\ny\n~~~\n````text\n```\nz\n````\nc\n   ~~~~\nopen"
    blocks, prose = split_fenced(text)
    assert blocks == [("mermaid", "x"), ("Mermaid", "y"), ("text", "```\nz"), ("", "open")]
    assert prose == "a\nb\nc"


def test_backtick_in_a_backtick_info_string_is_not_a_fence():
    blocks, prose = split_fenced("a\n``` `x`\nb")
    assert blocks == []
    assert prose == "a\n``` `x`\nb"


def test_backtick_in_a_tilde_info_string_is_a_fence():
    assert split_fenced("~~~ `x`\nb\n~~~") == ([("`x`", "b")], "")


def test_closing_fence_may_end_with_spaces_but_no_other_text():
    assert split_fenced("```\nx\n```  \t\ny") == ([("", "x")], "y")
    assert split_fenced("```\nx\n``` y\n```") == ([("", "x\n``` y")], "")


def test_closing_fence_is_the_same_character_and_at_least_as_long():
    assert split_fenced("````\nx\n```\n````") == ([("", "x\n```")], "")
    assert split_fenced("```\nx\n`````\ny") == ([("", "x")], "y")
    assert split_fenced("~~~\nx\n```\n~~~") == ([("", "x\n```")], "")


def test_a_fence_is_indented_by_at_most_three_spaces():
    assert split_fenced("   ```\nx\n   ```") == ([("", "x")], "")
    assert split_fenced("    ```\nx") == ([], "    ```\nx")


def test_info_language_is_the_first_word_lower_cased():
    assert info_language("PowerShell") == "powershell"
    assert info_language("json title") == "json"
    assert info_language("  Mermaid  ") == "mermaid"
    assert info_language("") == ""
