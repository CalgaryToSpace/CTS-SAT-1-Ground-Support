"""Type definitions for the app."""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from loguru import logger

import pytz

from cts1_ground_support.bytes import bytes_to_nice_str
from cts1_ground_support.json_parser import auto_format_json_in_blob
from cts1_ground_support.terminal_app import log_config
from pathlib import Path

UART_PORT_NAME_DISCONNECTED = "disconnected"


@dataclass
class RxTxLogEntry:
    """A class to store an entry in the RX/TX log."""

    raw_bytes: bytes
    entry_type: Literal["transmit", "receive", "notice", "error"]
    timestamp_sec: float = field(default_factory=lambda: time.time())

    def save_to_file(self: "RxTxLogEntry", file_path: str) -> None:
        """Save the log entry to a file, appending each entry on a new line."""
        logger.info(f"Saving log entry to {file_path}")
        with open(file_path, "a") as f:
            f.write(self.to_string(show_end_of_line_chars=True, show_timestamp=False, auto_format_json=False) + "\n")

    def __init__(self, raw_bytes: bytes, entry_type: Literal["transmit", "receive", "notice", "error"]):
        self.raw_bytes = raw_bytes
        self.entry_type = entry_type
        self.timestamp_sec = time.time()
        self.timestamp_day = datetime.fromtimestamp(self.timestamp_sec, tz=pytz.timezone("America/Edmonton")).strftime("%Y-%m-%d")
        # Use configurable log directory
        try:
            log_dir = log_config.log_dir
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir / f"rx_tx_log_{self.timestamp_day}.txt"
        except Exception as e:
            logger.error(f"Failed to use configured log_dir, falling back to current directory: {e}")
            log_file_path = Path(f"rx_tx_log_{self.timestamp_day}.txt")
        self.save_to_file(str(log_file_path))

    @property
    def css_style(self: "RxTxLogEntry") -> dict:
        """Get the CSS style for the log entry (mostly just color currently)."""
        if self.entry_type == "transmit":
            return {"color": "cyan"}
        if self.entry_type == "receive":
            return {"color": "#AAFFAA"}  # green

        if self.entry_type == "notice":
            return {"color": "yellow"}

        if self.entry_type == "error":
            return {"color": "#FF6666"}

        msg = f"Invalid entry type: {self.entry_type}"
        raise ValueError(msg)

    def to_string(
        self: "RxTxLogEntry",
        *,
        show_end_of_line_chars: bool,
        show_timestamp: bool,
        auto_format_json: bool,
    ) -> str:
        """Get the text representation of the log entry."""
        prefix = ""
        if show_timestamp:
            dt = datetime.fromtimestamp(self.timestamp_sec, tz=pytz.timezone("America/Edmonton"))
            # Format the datetime object to include milliseconds
            prefix = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + ": "

        if self.entry_type == "notice":
            return f"{prefix}==================== {self.raw_bytes.decode()} ===================="
        # TODO: make these equals-signs a fixed width
        if self.entry_type == "error":
            return f"{prefix}==================== {self.raw_bytes.decode()} ===================="

        nice_str = bytes_to_nice_str(
            self.raw_bytes,
            show_end_of_line_chars=show_end_of_line_chars,
        )
        if auto_format_json:
            nice_str = auto_format_json_in_blob(nice_str)
        return f"{prefix}" + nice_str
