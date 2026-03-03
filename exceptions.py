"""
Custom exceptions for the sync application.

This module defines a hierarchy of exceptions for consistent error handling
across the application.
"""


class SyncError(Exception):
    """Base exception for sync operations."""

    def __init__(self, message: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class APIConnectionError(SyncError):
    """Raised when API connection fails."""

    pass


class ValidationError(SyncError):
    """Raised when validation fails."""

    pass


class ConfigurationError(SyncError):
    """Raised when configuration is invalid."""

    pass


class APIResponseError(SyncError):
    """Raised when API returns an error response."""

    def __init__(
        self,
        message: str,
        status_code: int = None,
        response_body: str = None,
        details: dict = None,
    ):
        super().__init__(message, details)
        self.status_code = status_code
        self.response_body = response_body


class DataFetchError(SyncError):
    """Raised when data fetching fails."""

    pass


class DataSaveError(SyncError):
    """Raised when data saving fails."""

    pass
