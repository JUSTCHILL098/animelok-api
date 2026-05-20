"""Typed API exceptions."""

from __future__ import annotations


class ScraperError(Exception):
    """Raised when a remote page cannot be scraped or parsed."""


class NotFoundError(ScraperError):
    """Raised when a requested anime or episode cannot be found."""


class StreamExtractionError(ScraperError):
    """Raised when the multi stream cannot be resolved."""

