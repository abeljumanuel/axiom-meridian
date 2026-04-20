"""Unit tests for privacy utilities."""

from meridian.utils.privacy import strip_private_tags


def test_strip_single_tag():
    text = "text <private>secret</private> more"
    assert strip_private_tags(text) == "text [REDACTED] more"


def test_strip_multiline():
    text = "start <private>line1\nline2\nline3</private> end"
    assert strip_private_tags(text) == "start [REDACTED] end"


def test_strip_multiple_tags():
    text = "a <private>one</private> b <private>two</private> c"
    assert strip_private_tags(text) == "a [REDACTED] b [REDACTED] c"


def test_no_tags():
    text = "just plain text"
    assert strip_private_tags(text) == "just plain text"


def test_none_input():
    assert strip_private_tags(None) is None


def test_nested_content():
    text = "<private>key=sk-xxx\ntoken=abc</private>"
    assert strip_private_tags(text) == "[REDACTED]"
