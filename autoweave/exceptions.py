"""Shared exception types for AutoWeave."""


class AutoweaveError(Exception):
    """Base error for library-specific failures."""


class ConfigurationError(AutoweaveError):
    """Raised when canonical config or runtime wiring is invalid."""


class StateTransitionError(AutoweaveError):
    """Raised when a state-machine transition is rejected."""
