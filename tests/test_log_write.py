from pathlib import Path

log_dir = Path("C:/Users/megan/OneDrive/Documents/CTS_SAT_1_Logs")
log_dir.mkdir(parents=True, exist_ok=True)  # Create the directory if it doesn't exist

test_file = log_dir / "test_write.txt"

try:
    with open(test_file, "w") as f:
        f.write("This is a test.\n")
    print(f"Success! Wrote to {test_file}")
except Exception as e:
    print(f"Failed to write to {test_file}: {e}")