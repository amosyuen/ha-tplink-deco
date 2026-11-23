"""TPLink Deco Exceptions"""


class EmptyDataException(Exception):
    """Empty data exception"""


class ForbiddenException(Exception):
    """Forbidden exception"""


class LoginForbiddenException(Exception):
    """Login forbidden exception"""


class LoginInvalidException(Exception):
    """Invalid login exception"""

    def __init__(self, attempts_remaining):
        self.attempts_remaining = attempts_remaining
        super().__init__(
            f"Invalid login credentials. {attempts_remaining} attempts remaining."
        )


class TimeoutException(Exception):
    """Timeout exception"""

    def __init__(self, message=""):
        super().__init__(
            "Timeout exception. If you get a lot of these see"
            f" https://github.com/amosyuen/ha-tplink-deco#timeout-error. {message}"
        )


class TransientConnectionException(Exception):
    """A truncated response or disconnect that can be retried safely."""


class InvalidClientListException(Exception):
    """A Deco returned a client list with an unsupported top-level type."""


class HttpsRequiredException(Exception):
    """The Deco router requires HTTPS but this entry permits HTTP only."""


class UnsafeRedirectException(Exception):
    """The Deco returned a redirect outside the permitted local transport."""


class UnexpectedApiException(Exception):
    """Unexpected API exception"""
