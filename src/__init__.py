"""
keepa_crawler - Python client for Keepa's Amazon product data
"""

from .client import (
    KeepaClient,
    KeepaError,
    KeepaConnectionError,
    KeepaTimeoutError,
    KeepaAPIError
)

__version__ = "1.0.0"
__all__ = [
    'KeepaClient',
    'KeepaError',
    'KeepaConnectionError',
    'KeepaTimeoutError',
    'KeepaAPIError',
    '__version__'
]
