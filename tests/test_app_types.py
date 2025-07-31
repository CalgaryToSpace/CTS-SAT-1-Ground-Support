# import pytest

# import os
# import glob
# import time

# from cts1_ground_support.terminal_app.app_types import RxTxLogEntry

# def test_rxtx_log_entry_creates_file(tmp_path, monkeypatch):
#     # Patch time.time to a fixed value for predictable filename
#     fixed_time = 1710000000.123
#     monkeypatch.setattr(time, "time", lambda: fixed_time)

#     # Change working directory to tmp_path so file is created there
#     old_cwd = os.getcwd()
#     os.chdir(tmp_path)
#     try:
#         # Create a log entry
#         entry = RxTxLogEntry(b"test log", "notice")
#         # The file should be named as per the timestamp
#         expected_filename = f"rx_tx_log_{fixed_time}.txt"
#         files = list(tmp_path.glob("rx_tx_log_*.txt"))
#         assert len(files) == 1
#         assert files[0].name == expected_filename
#         # Check file contents
#         content = files[0].read_text()
#         assert "test log" in content
#     finally:
#         os.chdir(old_cwd)
