"""Tools for parsing JSON strings from blobs of text."""

from collections.abc import Iterator
from dataclasses import dataclass

import orjson


@dataclass(kw_only=True)
class ParsedJson:
    """A parsed JSON object."""

    data: dict | list
    start_idx: int
    end_idx: int
    original_str: str


def extract_json_blobs(content: str) -> Iterator[ParsedJson]:
    """Extract JSON values from a string."""
    # Source: https://stackoverflow.com/a/64920157
    start_idx = 0
    while start_idx < len(content):
        if content[start_idx] == "{":
            for end_idx in range(len(content) - 1, start_idx, -1):
                if content[end_idx] == "}":
                    try:
                        data = orjson.loads(content[start_idx : end_idx + 1])
                        yield ParsedJson(
                            data=data,
                            start_idx=start_idx,
                            end_idx=end_idx + 1,
                            original_str=content[start_idx : end_idx + 1],
                        )
                        start_idx = end_idx
                        break
                    except orjson.JSONDecodeError:
                        pass
        start_idx += 1


def auto_format_json_in_blob(blob: str) -> str:
    """Automatically format JSON in a blob of text."""
    json_parts = list(extract_json_blobs(blob))

    for json_part in json_parts:
        formatted_data: str = orjson.dumps(json_part.data, option=orjson.OPT_INDENT_2).decode(
            "utf-8"
        )
        blob = blob.replace(json_part.original_str, formatted_data)

    return blob
