"""File logging utilities for daily log files."""

import os
from datetime import datetime
from pathlib import Path

import pytz
from loguru import logger

from cts1_ground_support.terminal_app.app_types import RxTxLogEntry


class DailyFileLogger:
    """Manages daily log files for RX/TX communications."""

    def __init__(self, log_directory: Path | str = "logs"):
        """Initialize the daily file logger.
        
        Args:
            log_directory: Directory where log files will be stored
        """
        self.log_directory = Path(log_directory)
        self.log_directory.mkdir(exist_ok=True)
        self.current_log_file = None
        self.current_date = None
        self._ensure_log_file()

    def _get_log_filename(self, date: datetime) -> str:
        """Generate log filename for a given date.
        
        Args:
            date: Date to generate filename for
            
        Returns:
            Filename string in format: cts1_ground_support_YYYY-MM-DD.log
        """
        return f"cts1_ground_support_{date.strftime('%Y-%m-%d')}.log"

    def _ensure_log_file(self) -> None:
        """Ensure the current log file is open and up to date."""
        now = datetime.now(tz=pytz.timezone("America/Edmonton"))
        today = now.date()
        
        if self.current_date != today:
            # Close previous file if open
            if self.current_log_file:
                self.current_log_file.close()
            
            # Open new file for today
            log_filename = self._get_log_filename(now)
            log_path = self.log_directory / log_filename
            
            # Create the file if it doesn't exist, or append if it does
            self.current_log_file = open(log_path, 'a', encoding='utf-8')
            self.current_date = today
            
            # Write session start marker
            session_start_msg = f"\n=== SESSION START: {now.strftime('%Y-%m-%d %H:%M:%S %Z')} ===\n"
            self.current_log_file.write(session_start_msg)
            self.current_log_file.flush()
            
            logger.info(f"Daily log file opened: {log_path}")

    def log_entry(self, entry: RxTxLogEntry) -> None:
        """Log an RX/TX entry to the current daily file.
        
        Args:
            entry: The RxTxLogEntry to log
        """
        self._ensure_log_file()
        
        # Format the entry for file logging (always include timestamps)
        log_line = entry.to_string(
            show_end_of_line_chars=False,  # Keep file logs clean
            show_timestamp=True,
            auto_format_json=True
        )
        
        # Add entry type prefix for clarity in logs
        type_prefix = {
            "transmit": "[TX] ",
            "receive": "[RX] ",
            "notice": "[NOTICE] ",
            "error": "[ERROR] "
        }.get(entry.entry_type, "[UNKNOWN] ")
        
        # Write to file
        self.current_log_file.write(f"{type_prefix}{log_line}\n")
        self.current_log_file.flush()

    def close(self) -> None:
        """Close the current log file."""
        if self.current_log_file:
            session_end_msg = f"=== SESSION END: {datetime.now(tz=pytz.timezone('America/Edmonton')).strftime('%Y-%m-%d %H:%M:%S %Z')} ===\n"
            self.current_log_file.write(session_end_msg)
            self.current_log_file.close()
            self.current_log_file = None

    def get_recent_log_files(self, days: int = 7) -> list[Path]:
        """Get list of recent log files.
        
        Args:
            days: Number of recent days to include
            
        Returns:
            List of log file paths, sorted by date (newest first)
        """
        log_files = []
        for log_file in self.log_directory.glob("cts1_ground_support_*.log"):
            log_files.append(log_file)
        
        # Sort by modification time, newest first
        return sorted(log_files, key=lambda x: x.stat().st_mtime, reverse=True)[:days]

    def __del__(self):
        """Destructor to ensure file is closed."""
        try:
            if hasattr(self, 'current_log_file') and self.current_log_file:
                self.current_log_file.close()
        except:
            # Ignore errors during shutdown
            pass


# Global instance to be used throughout the application
daily_logger = DailyFileLogger()