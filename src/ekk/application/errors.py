"""Errors a caller can correct, shared by the application and its adapters.

Kept apart from ekk.model and from the loader's methods, whose bytes are
fingerprinted: a new attribute here never moves a store index.
"""


class RequestError(ValueError):
    """A request the caller can correct: an option or a value it passed (error code ``invalid_request``).

    Optional attributes, each None or empty when not known:
    ``refusal``, a stable name; ``option``, the option or request field at fault;
    ``record_ids``, full record IDs the refusal names; ``next``, the exact command
    to run instead. ``value`` is the text given for ``option``; it is never shown,
    and with one record ID it lets a transport name the caller's own command with
    only that value replaced. The message is ``str(error)``.
    """

    def __init__(self, message, *, refusal=None, option=None, record_ids=(), next=None, value=None):
        super().__init__(message)
        self.refusal, self.option, self.record_ids, self.next, self.value = refusal, option, tuple(record_ids), next, value


def unknown_id(given, candidates, option):
    """The refusal of an ID that names no current record in the selected contexts.

    ``candidates`` are the full IDs, readable from those contexts, that start with
    ``given`` (RealmService.readable_prefix_matches). Exactly one is named, with ``value``
    so a transport can offer the caller's own command with only that value
    replaced; several give only their count. Nothing is resolved automatically.
    """
    message = 'Record unavailable in selected contexts: ' + given
    if len(candidates) == 1:
        return RequestError(f'{message}; it is the start of {candidates[0]}. {option} takes the full ID.',
                            refusal='unknown_id', option=option, record_ids=candidates, value=given)
    if candidates:
        message += f'; {len(candidates)} records in them start with it. {option} takes the full ID.'
    return RequestError(message, refusal='unknown_id', option=option, value=given)
