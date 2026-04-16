from __future__ import annotations

from step5_static_check.preprocess import strip_strings_and_comments


def test_strip_strings_and_comments_removes_false_positives() -> None:
    js = """// comment with .then(
var a = "document.querySelector('.foo')";
var b = 'id="bad"';
var c = `template ${value} .then(`;
/* block comment with document.body */
return promise.then(function () {});
"""

    stripped = strip_strings_and_comments(js)

    assert "comment with .then(" not in stripped
    assert "document.querySelector('.foo')" not in stripped
    assert 'id="bad"' not in stripped
    assert "document.body" not in stripped
    assert '"__STR__"' in stripped
    assert "promise.then(" in stripped


def test_strip_strings_and_comments_handles_escaped_quotes() -> None:
    js = r"""var text = "hello \"world\"";
var path = 'it\'s fine';
"""

    stripped = strip_strings_and_comments(js)

    assert "__STR__" in stripped
    assert "world" not in stripped
    assert "fine" not in stripped
