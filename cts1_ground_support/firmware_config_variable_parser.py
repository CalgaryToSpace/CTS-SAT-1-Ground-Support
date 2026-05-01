"""Parse integer and string configuration variables from a configuration.c file.

Extracts entries from CONFIG_int_config_variables[] and CONFIG_str_config_variables[],
and enriches them with docstrings found in any C source files.
"""

import dataclasses
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from cts1_ground_support.telecommand_array_parser import remove_c_comments

_DEFAULT_STR_MAX_LENGTHS = {
    "CONFIG_str_demo_var_1": 25 - 1,
    "CONFIG_str_demo_var_2": 50 - 1,
    "COMMS_beacon_friendly_message_str": 42 - 1,
    "TCMD_active_agenda_filename": 200 - 1,
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class IntConfigVariable:
    """Represents a single integer configuration variable."""

    variable_name: str
    docstring: str | None = None


@dataclass
class StrConfigVariable:
    """Represents a single string configuration variable."""

    variable_name: str

    # `max_length` in bytes, excluding null-terminator. Note that the C structs include the
    # null-terminator in the length, so we subtract 1.
    max_length: int | None = None

    docstring: str | None = None


# ---------------------------------------------------------------------------
# Docstring extraction  (/// style only, same contract as telecommand parser)
# ---------------------------------------------------------------------------


def extract_variable_docstring(variable_name: str, c_code: str) -> str | None:
    """Return the docstring that immediately precedes *variable_name*'s declaration/definition.

    Handles both plain declarations and extern + initialized definitions.
    """
    pattern = re.compile(
        rf"(?P<docstring>(///.*\n)+)"  # one or more /// lines
        rf"\s*"  # optional blank line
        rf"(?:extern\s+)?"  # optional 'extern'
        rf"(?:const\s+)?"  # optional 'const'
        rf"\w[\w\s]*\s+{re.escape(variable_name)}"  # type + name
        rf"\s*(?:=|;|\[)"  # = value, ; declaration, or [ for arrays
    )
    match = pattern.search(c_code)
    if match is None:
        return None

    raw = match.group("docstring")
    lines = [line.strip().lstrip("/").strip() for line in raw.strip().splitlines()]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Config array parsers
# ---------------------------------------------------------------------------

# Matches a single struct entry inside CONFIG_int_config_variables[]
_INT_ENTRY_RE = re.compile(
    r"\{"
    r"[^{}]*?"
    r'\.variable_name\s*=\s*"(?P<name>[^"]+)"'
    r"[^{}]*?"
    r"\}",
    re.DOTALL,
)

# Matches a single struct entry inside CONFIG_str_config_variables[]
_STR_ENTRY_RE = re.compile(
    r"\{"
    r"[^{}]*?"
    r'\.variable_name\s*=\s*"(?P<name>[^"]+)"'
    r"[^{}]*?"
    r"(?:\.max_length\s*=\s*(?P<max_len>[^,}\n]+))?"
    r"[^{}]*?"
    r"\}",
    re.DOTALL,
)

# Matches the outer CONFIG_int_config_variables array body
_INT_ARRAY_RE = re.compile(
    r"CONFIG_integer_config_entry_t\s+CONFIG_int_config_variables\s*\[\s*\]\s*=\s*\{"
    r"(?P<body>(?:[^{}]|\{[^{}]*\})*)"
    r"\}\s*;",
    re.DOTALL,
)

# Matches the outer CONFIG_str_config_variables array body
_STR_ARRAY_RE = re.compile(
    r"CONFIG_string_config_entry_t\s+CONFIG_str_config_variables\s*\[\s*\]\s*=\s*\{"
    r"(?P<body>(?:[^{}]|\{[^{}]*\})*)"
    r"\}\s*;",
    re.DOTALL,
)


def parse_int_config_array(c_code: str) -> list[IntConfigVariable]:
    """Extract all entries from CONFIG_int_config_variables[]."""
    c_code = remove_c_comments(c_code)

    m = _INT_ARRAY_RE.search(c_code)
    if not m:
        msg = "Could not find CONFIG_int_config_variables[] in the provided C code."
        raise ValueError(msg)

    body = m.group("body")
    return [
        IntConfigVariable(variable_name=entry.group("name"))
        for entry in _INT_ENTRY_RE.finditer(body)
    ]


def parse_str_config_array(c_code: str) -> list[StrConfigVariable]:
    """Extract all entries from CONFIG_str_config_variables[]."""
    c_code_no_block = remove_c_comments(c_code)

    m = _STR_ARRAY_RE.search(c_code_no_block)
    if not m:
        msg = "Could not find CONFIG_str_config_variables[] in the provided C code."
        raise ValueError(msg)

    body = m.group("body")
    results: list[StrConfigVariable] = []
    for entry in _STR_ENTRY_RE.finditer(body):
        name = entry.group("name")
        raw_max = entry.group("max_len")

        max_length: int | None = None
        if raw_max:
            raw_max = raw_max.strip()
            try:
                # Note: Subtract one to account for null terminator.
                max_length = int(raw_max) - 1
            except ValueError:
                max_length = None

        if max_length is None:
            # Hack: Fetch it from a dict we store here.  # noqa: FIX004
            # If not registered in that dict, returns None.
            max_length = _DEFAULT_STR_MAX_LENGTHS.get(name)

        results.append(StrConfigVariable(variable_name=name, max_length=max_length))
    return results


# ---------------------------------------------------------------------------
# High-level: parse arrays + enrich with docstrings
# ---------------------------------------------------------------------------


def parse_config_variables(
    config_c_code: str,
    extra_c_sources: str = "",
) -> tuple[list[IntConfigVariable], list[StrConfigVariable]]:
    """Parse both int and string config variable arrays, then attach docstrings.

    Args:
        config_c_code:   Contents of configuration.c (or equivalent).
        extra_c_sources: Concatenated contents of any additional C files that
                         may contain variable declarations with docstrings.

    Returns:
        (int_vars, str_vars): lists of enriched config variable objects.

    """
    all_c = config_c_code + "\n" + extra_c_sources

    int_vars = parse_int_config_array(config_c_code)
    str_vars = parse_str_config_array(config_c_code)

    for var in int_vars:
        doc = extract_variable_docstring(var.variable_name, all_c)
        if doc:
            var.docstring = doc

    for var in str_vars:
        doc = extract_variable_docstring(var.variable_name, all_c)
        if doc:
            var.docstring = doc

    return int_vars, str_vars


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        fw_repo_path = Path(sys.argv[1])
        sys.stderr.write(f"Using repo passed as CLI argument: {fw_repo_path}\n")
    else:
        fw_repo_path = Path(input("Path to repo: ").strip())

    config_path = fw_repo_path / "firmware/Core/Src/config/configuration.c"
    src = config_path.read_text(encoding="utf-8")

    all_c_files = fw_repo_path.glob("firmware/Core/Src/**/*.c")
    all_c_files_contents = "\n\n".join(f.read_text(encoding="utf-8") for f in all_c_files)

    int_vars, str_vars = parse_config_variables(src, all_c_files_contents)

    output = {
        "int_config_variables": [dataclasses.asdict(v) for v in int_vars],
        "str_config_variables": [dataclasses.asdict(v) for v in str_vars],
    }
    sys.stdout.write(json.dumps(output, indent=2) + "\n")
