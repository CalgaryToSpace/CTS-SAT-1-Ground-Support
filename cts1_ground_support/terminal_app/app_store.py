"""A singleton class to store the app's state. Also, the instance of that class."""

import time
from dataclasses import dataclass, field
from pathlib import Path

from sortedcontainers import SortedDict

from cts1_ground_support.terminal_app.app_types import UART_PORT_NAME_DISCONNECTED, RxTxLogEntry


@dataclass
class AppStore:
    """A singleton class to store the app's state (across all clients)."""

    firmware_repo_path: Path | None = None

    uart_port_name: str = UART_PORT_NAME_DISCONNECTED

    # `rxtx_log` is a dictionary, where keys are increasing ints by the order the messages were
    # added/received. Elements are popped from the start, and added to the end.
    # Type of `rxtx_log`: SortedDict[int, RxTxLogEntry]
    rxtx_log: SortedDict[int, RxTxLogEntry] = field(
        default_factory=lambda: SortedDict({0: RxTxLogEntry(b"Start of Log", "notice")})
    )
    server_start_timestamp_sec: float = field(default_factory=time.time)
    last_tx_timestamp_sec: float = 0
    tx_queue: list[bytes] = field(default_factory=list)

    uart_log_refresh_rate_ms: int = 500

    def append_to_rxtx_log(self: "AppStore", entry: RxTxLogEntry) -> None:
        """Append a new entry to the RX/TX log."""
        self.rxtx_log[self.rxtx_log.keys()[-1] + 1] = entry


app_store = AppStore()
