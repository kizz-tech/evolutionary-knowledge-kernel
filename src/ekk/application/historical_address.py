"""Lexical historical addresses: no filesystem, owner inference or fuzzy lookup."""
import posixpath
import re


def historical_path(path, containing_path=None):
    if not isinstance(path, str) or not path or len(path) > 4096 or '\x00' in path or '\\' in path:
        raise ValueError('invalid historical path')
    if path.startswith('/'):
        raise ValueError('historical path must be relative to its named origin')
    if containing_path is not None:
        parent = historical_path(containing_path)
        path = posixpath.join(posixpath.dirname(parent), path)
    normalized = posixpath.normpath(path)
    if normalized in ('.', '..') or normalized.startswith('../'):
        raise ValueError('historical path escapes its origin')
    return normalized


def source_selection(raw, selector):
    """Only exact byte ranges are interpreted; other grammars stay explicit data.

    Obsidian heading/block semantics vary with renderer and duplicate headings.
    Preserving such a selector is useful without pretending a whole-file read
    has resolved it. Byte ranges are end-exclusive in the immutable source.
    """
    if selector is None:
        return {'state': 'whole_object', 'selector': None, 'start': 0, 'end': len(raw)}
    if not isinstance(selector, str) or not selector or len(selector) > 2000:
        raise ValueError('selector must be bounded nonempty text')
    match = re.fullmatch(r'bytes:(\d+):(\d+)', selector)
    if not match:
        return {'state': 'unsupported', 'selector': selector}
    start, end = map(int, match.groups())
    if not 0 <= start < end <= len(raw):
        return {'state': 'unavailable', 'selector': selector}
    return {'state': 'resolved', 'selector': selector, 'start': start, 'end': end}
