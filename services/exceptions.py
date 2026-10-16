"""Service-layer exception types."""


class ServiceError(Exception):
    """Base class for all service-layer errors."""


class NotFoundError(ServiceError):
    """Raised when a requested entity does not exist."""


class ConflictError(ServiceError):
    """Raised when an operation conflicts with existing data (e.g. duplicate plate)."""


class ValidationError(ServiceError):
    """Raised when input data fails business validation."""
