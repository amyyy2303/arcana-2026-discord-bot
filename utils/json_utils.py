import io
import json
import csv
import ast
from typing import Tuple, Dict, Any, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import discord
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False
    discord = None


def calculate_depth(data: Any, current_depth: int = 1) -> int:
    """Calculate maximum nesting depth of JSON structures."""
    if isinstance(data, dict):
        if not data:
            return current_depth
        return max(calculate_depth(v, current_depth + 1) for v in data.values())
    elif isinstance(data, list):
        if not data:
            return current_depth
        return max(calculate_depth(item, current_depth + 1) for item in data)
    return current_depth


def validate_json(raw_text: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validates JSON string.
    Returns: (is_valid, message, stats_dict)
    """
    if not raw_text or not raw_text.strip():
        return False, "Input is empty.", None

    text = raw_text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON at line {e.lineno}, column {e.colno} (char {e.pos}):\n{e.msg}"
        return False, error_msg, None
    except Exception as e:
        return False, f"Parsing error: {str(e)}", None

    stats = {
        "root_type": type(data).__name__,
        "byte_size": len(text.encode("utf-8")),
        "max_depth": calculate_depth(data),
    }

    if isinstance(data, dict):
        stats["key_count"] = len(data)
    elif isinstance(data, list):
        stats["item_count"] = len(data)

    return True, "Valid JSON", stats


def format_json(raw_text: str, indent: int = 2, sort_keys: bool = False) -> Tuple[bool, str]:
    """Format and prettify JSON."""
    if not raw_text or not raw_text.strip():
        return False, "Input is empty."

    try:
        data = json.loads(raw_text.strip())
        formatted = json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=False)
        return True, formatted
    except json.JSONDecodeError as e:
        return False, f"JSON Syntax Error at line {e.lineno}, col {e.colno}: {e.msg}"
    except Exception as e:
        return False, f"Error formatting JSON: {str(e)}"


def minify_json(raw_text: str) -> Tuple[bool, str]:
    """Minify JSON into a single compact line."""
    if not raw_text or not raw_text.strip():
        return False, "Input is empty."

    try:
        data = json.loads(raw_text.strip())
        minified = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return True, minified
    except json.JSONDecodeError as e:
        return False, f"JSON Syntax Error at line {e.lineno}, col {e.colno}: {e.msg}"
    except Exception as e:
        return False, f"Error minifying JSON: {str(e)}"


def csv_to_json(csv_text: str, indent: int = 2) -> Tuple[bool, str]:
    """Convert CSV data to JSON array of objects."""
    if not csv_text or not csv_text.strip():
        return False, "CSV input is empty."

    try:
        f = io.StringIO(csv_text.strip())
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            return False, "No data rows found in CSV."
        json_output = json.dumps(rows, indent=indent, ensure_ascii=False)
        return True, json_output
    except Exception as e:
        return False, f"Error converting CSV to JSON: {str(e)}"


def json_to_csv(json_text: str) -> Tuple[bool, str]:
    """Convert JSON array of objects to CSV."""
    if not json_text or not json_text.strip():
        return False, "JSON input is empty."

    try:
        data = json.loads(json_text.strip())
        if isinstance(data, dict):
            # Wrap single dict in a list
            data = [data]
        elif not isinstance(data, list):
            return False, "JSON root must be an array of objects or an object to convert to CSV."

        if not data:
            return False, "JSON array is empty."

        # Collect all unique keys across all records
        fieldnames = []
        for row in data:
            if isinstance(row, dict):
                for k in row.keys():
                    if k not in fieldnames:
                        fieldnames.append(k)

        if not fieldnames:
            return False, "Items in JSON array must be objects with keys."

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            if isinstance(row, dict):
                writer.writerow({k: row.get(k, "") for k in fieldnames})
        return True, output.getvalue()
    except Exception as e:
        return False, f"Error converting JSON to CSV: {str(e)}"


def yaml_to_json(yaml_text: str, indent: int = 2) -> Tuple[bool, str]:
    """Convert YAML string to JSON string."""
    if not HAS_YAML:
        return False, "YAML support is not installed (missing pyyaml)."
    if not yaml_text or not yaml_text.strip():
        return False, "YAML input is empty."

    try:
        data = yaml.safe_load(yaml_text.strip())
        json_output = json.dumps(data, indent=indent, ensure_ascii=False)
        return True, json_output
    except Exception as e:
        return False, f"Error converting YAML to JSON: {str(e)}"


def json_to_yaml(json_text: str) -> Tuple[bool, str]:
    """Convert JSON string to YAML string."""
    if not HAS_YAML:
        return False, "YAML support is not installed (missing pyyaml)."
    if not json_text or not json_text.strip():
        return False, "JSON input is empty."

    try:
        data = json.loads(json_text.strip())
        yaml_output = yaml.dump(data, sort_keys=False, allow_unicode=True)
        return True, yaml_output
    except Exception as e:
        return False, f"Error converting JSON to YAML: {str(e)}"


def python_dict_to_json(py_text: str, indent: int = 2) -> Tuple[bool, str]:
    """Safely convert a Python dict/list literal representation to JSON."""
    if not py_text or not py_text.strip():
        return False, "Input is empty."

    try:
        parsed = ast.literal_eval(py_text.strip())
        json_output = json.dumps(parsed, indent=indent, ensure_ascii=False)
        return True, json_output
    except Exception as e:
        return False, f"Error evaluating Python literal: {str(e)}"


def prepare_discord_payload(
    content: str, filename: str = "output.json", syntax: str = "json"
) -> Tuple[str, Any]:
    """
    Prepares Discord response:
    - If content fits inside 1900 chars, formats inside markdown code block.
    - If content exceeds 1900 chars, returns a notification message and a discord.File attachment.
    """
    code_block = f"```{syntax}\n{content}\n```"
    if len(code_block) <= 1950:
        return code_block, None

    byte_data = io.BytesIO(content.encode("utf-8"))
    if HAS_DISCORD and discord:
        discord_file = discord.File(fp=byte_data, filename=filename)
    else:
        discord_file = byte_data
    return "Output exceeds Discord message character limit (2000 chars). Download the formatted file below:", discord_file
