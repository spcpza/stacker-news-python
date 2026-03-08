"""Exceptions for the Stacker News SDK."""


class SNError(Exception):
    """Base exception for all Stacker News SDK errors."""


class SNAuthError(SNError):
    """Authentication failed or credentials missing."""


class SNPaymentRequired(SNError):
    """A post requires a Lightning invoice payment to go live.

    Attributes:
        pay_in_id:  The PayIn object ID (poll ``client.get_pay_in(id)``).
        bolt11:     The bolt11 invoice to pay.
        item_id:    The item ID (available after payment is confirmed).
    """

    def __init__(self, message: str, pay_in_id: str, bolt11: str, item_id: str | None = None):
        super().__init__(message)
        self.pay_in_id = pay_in_id
        self.bolt11 = bolt11
        self.item_id = item_id


class SNGraphQLError(SNError):
    """The GraphQL API returned one or more errors."""

    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.errors = errors or []
