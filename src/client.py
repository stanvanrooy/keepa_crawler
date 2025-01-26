"""
A client for interacting with Keepa's API to retrieve historical Amazon product
data.
"""

import json
import datetime
import zlib
import os
import struct
import threading
import logging
from typing import Optional, Dict, Tuple, List, Any
from curl_cffi.requests import Session, WebSocket, WsCloseCode

__version__ = "1.0.0"
logger = logging.getLogger(__name__)


class KeepaError(Exception):
    """Base exception for all Keepa client errors."""


class KeepaConnectionError(KeepaError):
    """Exception raised for connection-related errors."""


class KeepaTimeoutError(KeepaError):
    """Exception raised when a request times out."""


class KeepaAPIError(KeepaError):
    """Exception raised due to invalid API response."""


class KeepaClient:
    """
    A client to connect to Keepa's WebSocket API and retrieve historical
    pricing data.

    Args:
        user_agent (str, optional): User agent string for the WebSocket
            connection. Defaults to a predefined Firefox user agent.
        reconnect_interval (int): Seconds to wait between reconnection attempts
            Defaults to 5.

    Raises:
        KeepaConnectionError: If initial connection to the WebSocket fails.
    """

    WS_URL = "wss://push2.keepa.com/apps/cloud/"
    PARAMS = {'app': 'keepaWebsite', 'version': '2.0'}
    USER_AGENT = (
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:134.0) Gecko/20100101 '
        'Firefox/134.0'
    )
    KEEPA_EPOCH = datetime.datetime(2011, 1, 1).timestamp()
    RECONNECT_INTERVAL = 5

    TYPES = [
        "AMAZON", "NEW", "USED", "SALES", "LISTPRICE", "COLLECTIBLE",
        "REFURBISHED", "NEW_FBM_SHIPPING", "LIGHTNING_DEAL", "WAREHOUSE",
        "NEW_FBA", "COUNT_NEW", "COUNT_USED", "COUNT_REFURBISHED",
        "COUNT_COLLECTIBLE", "EXTRA_INFO_UPDATES", "RATING", "COUNT_REVIEWS",
        "BUY_BOX_SHIPPING", "USED_NEW_SHIPPING", "USED_VERY_GOOD_SHIPPING",
        "USED_GOOD_SHIPPING", "USED_ACCEPTABLE_SHIPPING",
        "COLLECTIBLE_NEW_SHIPPING", "COLLECTIBLE_VERY_GOOD_SHIPPING",
        "COLLECTIBLE_GOOD_SHIPPING", "COLLECTIBLE_ACCEPTABLE_SHIPPING",
        "REFURBISHED_SHIPPING", "EBAY_NEW_SHIPPING", "EBAY_USED_SHIPPING",
        "TRADE_IN", "RENT", "BUY_BOX_USED_SHIPPING", "PRIME_EXCL"
    ]
    INDEX_TO_TYPE = {i: t for i, t in enumerate(TYPES)}

    GET_PRODUCT_TEMPLATE = {
        "path": "product",
        "history": True,
        "type": "ws",
        "basic": True,
        "compact": True,
        "domainId": 1,
        "maxAge": 3,
        "refreshProduct": False,
        "id": 3407,
        "version": "20250108"
    }

    def __init__(
        self,
        user_agent: Optional[str] = None,
        reconnect_interval: int = 5
    ):
        self.user_agent = user_agent or self.USER_AGENT
        self.reconnect_interval = reconnect_interval

        self.session = Session()
        self.ws: Optional[WebSocket] = None
        self.products: Dict[str, dict] = {}
        self.pending_events: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ws_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._connect()

    def _connect(self) -> None:
        """Establish WebSocket connection and start background thread."""
        if self._ws_thread and self._ws_thread.is_alive():
            return

        headers = {
            'Sec-WebSocket-Protocol': self.generate_token(),
            'User-Agent': self.user_agent,
        }

        try:
            self.ws = self.session.ws_connect(
                url=self.WS_URL,
                headers=headers,
                params=self.PARAMS,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                default_headers=True,
            )
        except Exception as e:
            logger.error("Initial connection failed: %s", e)
            raise KeepaConnectionError("Connection failed") from e

        self._running.set()
        self._ws_thread = threading.Thread(
            target=self._ws_run_forever,
            name="KeepaWebSocketThread",
            daemon=True
        )
        self._ws_thread.start()
        logger.info("WebSocket connection established")

    def _ws_run_forever(self) -> None:
        """Main loop for WebSocket connection management."""
        while self._running.is_set():
            try:
                if self.ws:
                    self.ws.run_forever()
            except Exception as e:
                logger.error("WebSocket error: %s", e)

            if self._running.is_set():
                logger.info(
                    "Attempting reconnection in %d seconds...",
                    self.reconnect_interval
                )
                threading.Event().wait(self.reconnect_interval)
                self._reconnect()

    def _reconnect(self) -> None:
        """Handle reconnection by resetting state and establishing new
        connection."""
        with self._lock:
            self.products.clear()
            for pending_entry in self.pending_events.values():
                pending_entry['event'].set()
            self.pending_events.clear()

        try:
            if self.ws:
                self.ws.close()
        except Exception as e:
            logger.error("Error closing old WebSocket: %s", e)

        try:
            self._connect()
        except Exception as e:
            logger.error("Reconnection failed: %s", e)

    def close(self) -> None:
        """Cleanly shutdown the client and release resources."""
        self._running.clear()

        try:
            if self.ws:
                self.ws.close()
        except Exception as e:
            logger.error("Error closing WebSocket: %s", e)

        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)
            if self._ws_thread.is_alive():
                logger.warning("WebSocket thread did not terminate cleanly")

        try:
            self.session.close()
        except Exception as e:
            logger.error("Error closing session: %s", e)

        logger.info("Client shutdown complete")

    def get_historical_prices(
        self,
        asin: str,
        timeout: Optional[float] = 30
    ) -> Dict[str, List[Tuple[datetime.datetime, int]]]:
        """
        Retrieve historical price data for a given ASIN.

        Args:
            asin: The Amazon Standard Identification Number.
            timeout: Maximum wait time in seconds. Defaults to 30.

        Returns:
            Dictionary mapping price types to historical data points.

        Raises:
            KeepaConnectionError: If not connected.
            ValueError: If duplicate request.
            KeepaTimeoutError: On response timeout.
            KeepaAPIError: On invalid data.
        """
        if not self._running.is_set() or not self.ws:
            raise KeepaConnectionError("Not connected to WebSocket server")

        message = self.GET_PRODUCT_TEMPLATE.copy()
        message['asin'] = asin
        compressed_msg = self._compress(json.dumps(message))

        with self._lock:
            if asin in self.pending_events:
                raise ValueError(f"Request already pending for ASIN: {asin}")

            event = threading.Event()
            self.pending_events[asin] = {'event': event, 'error': None}

        try:
            self.ws.send(compressed_msg)
            logger.debug("Sent request for ASIN: %s", asin)
        except Exception as e:
            with self._lock:
                del self.pending_events[asin]
            raise KeepaConnectionError("Failed to send request") from e

        if not event.wait(timeout=timeout):
            with self._lock:
                if asin in self.pending_events:
                    del self.pending_events[asin]
            raise KeepaTimeoutError(
                f"No response for ASIN: {asin} within {timeout}s"
            )

        with self._lock:
            pending_entry = self.pending_events.pop(asin, None)
            product_data = self.products.pop(asin, None)

        if pending_entry and pending_entry['error'] is not None:
            raise pending_entry['error']  # type: ignore

        if not product_data:
            raise KeepaAPIError(
                f"Empty product data received for ASIN: {asin}"
            )

        return product_data

    def _on_message(self, ws: WebSocket, message: bytes) -> None:
        """Handle incoming WebSocket messages."""
        try:
            decompressed = self._decompress(message)
            data = json.loads(decompressed)

            if 'products' not in data:
                logger.debug("Received message without products: %s", data)
                return

            product = data['products'][0]
            asin = product['asin']
            price_data = {}
            error = None

            try:
                for i, csv_entry in enumerate(product['csv']):
                    price_type = self.INDEX_TO_TYPE[i]
                    if product['csv'][i] is None:
                        price_data[price_type] = []
                    else:
                        price_data[price_type] = [
                            (self.keepa_to_datetime(ts), price)
                            for ts, price in zip(
                                csv_entry[::2],
                                csv_entry[1::2]
                            )
                        ]
            except Exception as e:
                error = e
                logger.error("Error processing CSV data for ASIN %s: %s",
                             asin, e)

            with self._lock:
                if asin in self.pending_events:
                    pending_entry = self.pending_events[asin]
                    if error:
                        pending_entry['error'] = error
                    else:
                        self.products[asin] = price_data
                    pending_entry['event'].set()
                    logger.info("Received data for ASIN: %s", asin)

        except Exception as e:
            logger.error("Message processing error: %s", e)

    def _on_error(self, ws: WebSocket, error: Exception) -> None:
        """Handle WebSocket errors."""
        logger.error("WebSocket error: %s", error)

    def _on_close(
        self,
        ws: WebSocket,
        close_code: WsCloseCode,
        close_reason: str
    ) -> None:
        """Handle WebSocket closure."""
        if self._running.is_set():
            logger.info(
                "WebSocket closed (code: %s, reason: %s)",
                close_code,
                close_reason
            )

    @staticmethod
    def generate_token() -> str:
        """Generate a random WebSocket token."""
        random_bytes = os.urandom(32)
        numbers = struct.unpack('16H', random_bytes)
        return ''.join(f"{n:04x}" for n in numbers)

    @classmethod
    def keepa_to_datetime(
        cls,
        keepa_timestamp_minutes: int
    ) -> datetime.datetime:
        """Convert Keepa timestamp (minutes since epoch) to datetime."""
        timestamp = (keepa_timestamp_minutes * 60) + cls.KEEPA_EPOCH
        return datetime.datetime.utcfromtimestamp(timestamp)

    @staticmethod
    def _compress(message: str) -> bytes:
        """Compress message using zlib."""
        return zlib.compress(message.encode(), level=zlib.Z_BEST_COMPRESSION)

    @staticmethod
    def _decompress(data: bytes) -> str:
        """Decompress zlib-compressed data."""
        return zlib.decompress(data, wbits=-zlib.MAX_WBITS).decode()
