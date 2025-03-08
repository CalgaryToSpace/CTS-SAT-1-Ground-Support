"""Tool to generate a spreadsheet of telecommands."""

import csv
from datetime import datetime
from pathlib import Path

from loguru import logger

from cts1_ground_support.paths import clone_firmware_repo
from cts1_ground_support.telecommand_array_parser import parse_telecommand_list_from_repo
from cts1_ground_support.telecommand_types import TelecommandDefinition


def export_telecommands_to_csv(telecommands: list[TelecommandDefinition], save_dir: Path) -> None:
    """Save telecommands to a spreadsheet with a date-and-time-based filename.

    Args:
        telecommands (list[TelecommandDefinition]): List of telecommand definitions.
        save_dir (Path): Directory to save the spreadsheet.

    """
    # Ensure the save directory exists
    save_dir.mkdir(parents=True, exist_ok=True)

    # Define the filename based on the current date and time
    file_name = f"telecommands_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.csv"  # noqa: DTZ005
    file_path = save_dir / file_name

    # Open the file for writing
    with Path.open(file_path, mode="w", newline="") as file:
        writer = csv.writer(file)
        # Write the header row, adding "Docstring" to the columns
        writer.writerow(
            ["Name", "Function", "Number of Args", "Readiness Level", "Arguments", "Docstring"]
        )

        # Write each telecommand's details
        for tcmd in telecommands:
            writer.writerow(
                [
                    tcmd.name,
                    tcmd.tcmd_func,
                    tcmd.number_of_args,
                    tcmd.readiness_level,
                    ", ".join(tcmd.argument_descriptions or []),
                    tcmd.full_docstring or "",  # Include the docstring, or an empty string if none
                ]
            )

    # Notify the user of successful save
    logger.info(f"Telecommands saved to: {file_path}")


def prepare_paths() -> tuple[Path, Path]:
    """Prepare and return paths for the firmware and ground support repositories.

    Returns:
        tuple[Path, Path]: Paths for the firmware repository and ground support repository.

    """
    # Dynamically determine the base path as the parent of the CTS-SAT-1-Ground-Support directory
    script_path = Path(__file__).resolve()
    ground_support_repo_path = script_path.parents[1]
    base_path = ground_support_repo_path.parent

    # Validate the ground support repo path
    if not ground_support_repo_path.is_dir():
        msg = f"Ground support repo not found at {ground_support_repo_path}"
        raise FileNotFoundError(msg)

    # Clone firmware repository at the base path
    firmware_repo_path, _ = clone_firmware_repo(base_path)

    return firmware_repo_path, ground_support_repo_path


def main() -> None:
    """Parse the telecommand list from the firmware repo and save it to a spreadsheet."""
    firmware_repo_path, ground_support_repo_path = prepare_paths()

    # Parse telecommands from firmware repo
    telecommands = parse_telecommand_list_from_repo(firmware_repo_path)

    # Define spreadsheets directory inside ground support repo
    spreadsheets_dir = ground_support_repo_path / "spreadsheets"

    # Save telecommands to spreadsheets
    export_telecommands_to_csv(telecommands, spreadsheets_dir)


if __name__ == "__main__":
    main()
