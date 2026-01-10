"""
Metadata parser for loading persisted RunResult objects from TOML files.

Parses metadata.toml files created by RunResult.to_toml() and reconstructs
RunResult objects for history loading on startup. Reads sibling output files
for command output (filename stored in metadata.toml as output_file field).
"""

from __future__ import annotations

import datetime
import logging
import sys
from pathlib import Path

from .run_result import ResolvedCommand, RunResult, RunState

# Python 3.11+ has tomllib in stdlib, earlier versions need tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

logger = logging.getLogger(__name__)


def parse_metadata_file(metadata_path: Path) -> RunResult | None:
    """
    Parse metadata.toml and reconstruct RunResult.

    Args:
        metadata_path: Path to metadata.toml file

    Returns:
        RunResult if valid, None if parsing fails

    Notes:
        - Reads sibling output file (filename from output_file field, defaults to output.txt)
        - Gracefully handles missing or corrupted files
        - Returns None on any parse error (logs warning)
    """
    try:
        with open(metadata_path, "rb") as f:
            data = tomllib.load(f)

        # Required fields
        run_id = data.get("run_id")
        command_name = data.get("command_name")
        state_str = data.get("state")

        if not all([run_id, command_name, state_str]):
            logger.warning(f"Missing required fields in {metadata_path}")
            return None

        # Parse state
        try:
            state = RunState(state_str.lower())
        except ValueError:
            logger.warning(f"Invalid state '{state_str}' in {metadata_path}")
            return None

        # Parse timestamps
        start_time = _parse_iso_timestamp(data.get("start_time"))
        end_time = _parse_iso_timestamp(data.get("end_time"))
        duration = None
        if start_time and end_time:
            duration = end_time - start_time

        # Parse resolved command (optional)
        resolved_command = None
        if "resolved_command" in data:
            rc_data = data["resolved_command"]
            resolved_command = ResolvedCommand(
                command=rc_data.get("command", ""),
                cwd=rc_data.get("cwd"),
                env=rc_data.get("env", {}),
                timeout_secs=rc_data.get("timeout_secs"),
                vars=rc_data.get("vars", {}),
            )

        # Read output file (sibling to metadata.toml)
        # Use output_file field from metadata if present, otherwise fall back to output.txt
        output = ""
        output_filename = data.get("output_file", "output.txt")
        output_file = metadata_path.parent / output_filename
        if output_file.exists():
            try:
                output = output_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not read output file {output_file}: {e}")

        # Reconstruct RunResult
        result = RunResult(
            run_id=run_id,
            command_name=command_name,
            trigger_event=data.get("trigger_event"),
            trigger_chain=data.get("trigger_chain", []),
        )

        # Set state and metadata
        result.output = output
        result.success = data.get("success")
        result.error = data.get("error")
        result.state = state
        result.start_time = start_time
        result.end_time = end_time
        result.duration = duration
        result.resolved_command = resolved_command
        result.comment = data.get("comment", "")
        result.metadata_file = metadata_path
        result.output_file = output_file if output_file.exists() else None

        # Mark as finalized (from disk, already complete)
        result._is_finalized = True

        return result

    except FileNotFoundError:
        logger.warning(f"Metadata file not found: {metadata_path}")
        return None
    except Exception as e:
        logger.exception(f"Failed to parse metadata file {metadata_path}: {e}")
        return None


def _parse_iso_timestamp(iso_str: str | None) -> datetime.datetime | None:
    """
    Parse ISO 8601 timestamp string.

    Args:
        iso_str: ISO format timestamp string

    Returns:
        datetime object or None if invalid/missing
    """
    if not iso_str:
        return None
    try:
        return datetime.datetime.fromisoformat(iso_str)
    except ValueError:
        logger.warning(f"Invalid ISO timestamp: {iso_str}")
        return None
