import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import git


@dataclass(kw_only=True)
class TelecommandDefinition:
    """Stores a telecommand definition. from the `telecommand_definitions.c` file."""

    name: str
    tcmd_func: str
    description: str | None = None
    number_of_args: int
    readiness_level: str
    full_docstring: str | None = None
    argument_descriptions: list[str] | None = None

    def to_dict(self: "TelecommandDefinition") -> dict[str, str | int | list[str] | None]:
        """Convert the telecommand definition to a dictionary."""
        return {
            "name": self.name,
            "tcmd_func": self.tcmd_func,
            "description": self.description,
            "number_of_args": self.number_of_args,
            "readiness_level": self.readiness_level,
            "full_docstring": self.full_docstring,
            "argument_descriptions": self.argument_descriptions,
        }

    def to_dict_table_fields(self: "TelecommandDefinition") -> dict[str, str | int]:
        """Convert the telecommand definition to a dictionary, with only the fields from the array."""  # noqa: E501
        return {
            "Command": self.name,
            "Function Name": self.tcmd_func,
            "Number of Args": self.number_of_args,
            "Readiness Level": self.readiness_level,
        }

    def has_required_fields(self: "TelecommandDefinition") -> bool:
        """Check if the telecommand definition has all the required fields."""
        return all(
            [
                self.name is not None,
                self.tcmd_func is not None,
                self.number_of_args is not None,
                self.readiness_level is not None,
            ]
        )


def read_text_file(file_path: Path | str) -> str:
    """Read text file as UTF-8 in a cross-platform way."""
    # Note: following encoding arg is very important.
    return Path(file_path).read_text(encoding="utf-8")


def remove_c_comments(text: str) -> str:
    """Remove C-style comments from a string."""
    text = re.sub(r"\s*/\*.*?\*/\s*", "\n", text, flags=re.DOTALL)  # DOTALL makes . match newlines
    return re.sub(r"\s*//.*", "", text)


def parse_telecommand_array_table(c_code: str | Path) -> list[TelecommandDefinition]:
    """Parse the list of telecommands from the `telecommand_definitions.c` file."""
    if isinstance(c_code, Path):
        c_code = read_text_file(c_code)

    c_code = remove_c_comments(c_code)

    top_level_regex = re.compile(
        r"TCMD_TelecommandDefinition_t\s+\w+\s*\[\s*\]\s*=\s*{"
        r"(?P<all_struct_declarations>(\s*{\s*[^{}]+\s*},?)+)"
        r"\s*};",
    )

    struct_body_regex = re.compile(r"{\s*(?P<struct_body>[^{}]+)\s*}")
    struct_level_regex = re.compile(r"\s*\.(?P<field_name>\w+)\s*=\s*(?P<field_value>[^,]+),?")

    telecommands: list[TelecommandDefinition] = []

    top_level_matches = list(top_level_regex.finditer(c_code))
    if len(top_level_matches) != 1:
        msg = (
            f"Expected to find exactly 1 telecommand array in the input code, but found "
            f"{len(top_level_matches)} matches."
        )
        raise ValueError(msg)

    top_level_match = top_level_matches[0]
    all_struct_declarations = top_level_match.group("all_struct_declarations")

    for struct_declaration in re.finditer(struct_body_regex, all_struct_declarations):
        struct_body = struct_declaration.group("struct_body")

        fields: dict[str, str] = {}
        for struct_match in struct_level_regex.finditer(struct_body):
            field_name = struct_match.group("field_name")
            field_value = struct_match.group("field_value").strip().strip('"')

            fields[field_name] = field_value

        telecommands.append(
            TelecommandDefinition(
                name=fields["tcmd_name"],
                tcmd_func=fields["tcmd_func"],
                number_of_args=int(fields["number_of_args"]),
                readiness_level=fields["readiness_level"],
            ),
        )

    return telecommands


def extract_c_function_docstring(function_name: str, c_code: str) -> str | None:
    """Extract the docstring for a specified function from the C code."""
    pattern = re.compile(
        rf"(?P<docstring>(///(.*)\s*)+)\s*(?P<return_type>\w+)\s+{function_name}\s*\("
    )
    match = pattern.search(c_code)
    if match:
        docstring = match.group("docstring")
        docstring_lines = [
            line.strip().lstrip("/").strip() for line in docstring.strip().split("\n")
        ]
        return "\n".join(docstring_lines)
    return None


def extract_telecommand_arg_list(docstring: str) -> list[str] | None:
    """Extract the list of argument descriptions from a telecommand docstring."""
    arg_pattern = re.compile(
        r"@param args_str.*\n(?P<args>([\s/]*- Arg (?P<arg_num>\d+): (?P<arg_description>.+)\s*)*)"
    )

    matches = []
    match = arg_pattern.search(docstring)
    if not match:
        return None

    args_text = match.group("args")
    arg_desc_pattern = re.compile(r"- Arg (?P<arg_num>\d+): (?P<arg_description>.+)\s*")

    matches.extend(
        [arg_match.group("arg_description") for arg_match in arg_desc_pattern.finditer(args_text)]
    )

    return matches


def parse_telecommand_list_from_repo(repo_path: Path) -> list[TelecommandDefinition]:
    """Read the list of telecommands array table and extract docstrings for each telecommand.

    Args:
    ----
        repo_path: The path to the root of the repository. If None, the path is set automatically.

    """
    # Assert that the input is a Path object.
    if not isinstance(repo_path, Path):
        msg = f"Expected a Path object, but got {type(repo_path)}"
        raise TypeError(msg)
    # Assert that the input is a directory.
    if not repo_path.is_dir():
        msg = f"Expected a directory, but got {repo_path}"
        raise ValueError(msg)

    telecommands_defs_path = repo_path / "firmware/Core/Src/telecommands/telecommand_definitions.c"

    # Assert that the file exists.
    if not telecommands_defs_path.is_file():
        msg = "The telecommand definitions file does not exist in the expected location."
        raise ValueError(msg)

    tcmd_list = parse_telecommand_array_table(telecommands_defs_path)

    c_files_concat: str = "\n".join(
        read_text_file(f) for f in repo_path.glob("firmware/Core/Src/**/*tele*.c")
    )

    for tcmd_idx in range(len(tcmd_list)):
        docstring = extract_c_function_docstring(
            tcmd_list[tcmd_idx].tcmd_func,
            c_files_concat,
        )
        if docstring is not None:
            tcmd_list[tcmd_idx].full_docstring = docstring
            tcmd_list[tcmd_idx].argument_descriptions = extract_telecommand_arg_list(docstring)

    return tcmd_list


def save_telecommands_to_spreadsheet(
    telecommands: list[TelecommandDefinition], save_dir: Path
) -> None:
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

    try:
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
                        tcmd.full_docstring
                        or "",  # Include the docstring, or an empty string if none
                    ]
                )

        # Notify the user of successful save
        print(f"Telecommands saved to {file_path}")  # noqa: T201

    except IOError as e:  # noqa: UP024
        msg = f"Failed to write telecommands to {file_path}: {e}"
        raise IOError(msg)  # noqa: B904, UP024


def clone_firmware_repo(base_path: Path) -> tuple[Path, git.Repo]:
    """Clone the CTS-SAT-1-OBC-Firmware repository into the shared parent directory.

    Args:
        base_path (Path): Path to the parent directory containing both repositories.

    Returns:
        tuple[Path, git.Repo]: Path to the cloned firmware repo and the git.Repo object.

    """
    firmware_repo_path = base_path / "CTS-SAT-1-OBC-Firmware"

    if not firmware_repo_path.exists():
        print(f"Cloning CTS-SAT-1-OBC-Firmware into {firmware_repo_path}")  # noqa: T201
        repo = git.Repo.clone_from(
            "https://github.com/CalgaryToSpace/CTS-SAT-1-OBC-Firmware.git",
            to_path=firmware_repo_path,
            branch="main",
            depth=1,  # Only clone the latest version of the main branch.
        )
    else:
        print(f"CTS-SAT-1-OBC-Firmware already exists at {firmware_repo_path}")  # noqa: T201
        repo = git.Repo(firmware_repo_path)

    return firmware_repo_path, repo


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


if __name__ == "__main__":
    firmware_repo_path, ground_support_repo_path = prepare_paths()

    # Parse telecommands from firmware repo
    telecommands = parse_telecommand_list_from_repo(firmware_repo_path)

    # Define spreadsheets directory inside ground support repo
    spreadsheets_dir = ground_support_repo_path / "spreadsheets"

    # Save telecommands to spreadsheets
    save_telecommands_to_spreadsheet(telecommands, spreadsheets_dir)
