"""Exceptions with a message meant for the user."""


class UserError(Exception):
    """Raised from a command to answer with ``str(error)`` as a private error message.

    The command tree catches it, so commands don't need their own reply/return boilerplate.
    """
