class ProspectorError(Exception):
    """Base error for expected application failures."""


class ValidationError(ProspectorError):
    """Raised when lead input violates domain invariants."""


class LeadNotFoundError(ProspectorError):
    """Raised when an operation targets an unknown lead."""

