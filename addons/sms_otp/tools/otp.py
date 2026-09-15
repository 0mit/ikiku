# Part of iKiKu. Licensed under AGPL-3.0.
"""The error every SMS provider raises when a verification code cannot be sent."""


class SmsOtpError(Exception):
    """`status` is the provider's own code, or 0 when no answer came back.

    A provider's subclass names the provider and lists the statuses that mean the
    number itself was refused, so a caller can ask for the number again without
    knowing any provider's codes.
    """

    provider = None
    BAD_NUMBER_STATUSES = ()

    def __init__(self, method, status, message):
        super().__init__('%s: %s %s' % (method, status, message))
        self.method = method
        self.status = status
        self.message = message

    @property
    def bad_number(self):
        return self.status in self.BAD_NUMBER_STATUSES
