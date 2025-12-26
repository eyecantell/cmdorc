"""Tests for metadata_parser module."""

from __future__ import annotations

from cmdorc import RunState
from cmdorc.metadata_parser import parse_metadata_file


class TestMetadataParser:
    """Tests for parse_metadata_file function."""

    def test_parse_valid_metadata(self, tmp_path):
        """Parse a valid metadata.toml file."""
        # Create metadata.toml
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "Tests"
run_id = "run-123"
state = "success"
duration_str = "1.5s"
start_time = "2025-01-01T10:00:00"
end_time = "2025-01-01T10:00:01.5"
success = true
trigger_event = "user_saves"
trigger_chain = ["user_saves", "command_success:Lint"]

[resolved_command]
command = "pytest tests/"
cwd = "/home/user/project"
timeout_secs = 300

[resolved_command.vars]
test_dir = "tests"
"""
        )

        # Create output.txt
        output_path = tmp_path / "output.txt"
        output_path.write_text("Test output\nline 2\n")

        # Parse
        result = parse_metadata_file(metadata_path)

        # Assertions
        assert result is not None
        assert result.command_name == "Tests"
        assert result.run_id == "run-123"
        assert result.state == RunState.SUCCESS
        assert result.success is True
        assert result.trigger_event == "user_saves"
        assert result.trigger_chain == ["user_saves", "command_success:Lint"]
        assert result.output == "Test output\nline 2\n"
        assert result.metadata_file == metadata_path
        assert result.output_file == output_path
        assert result._is_finalized is True

        # Check resolved command
        assert result.resolved_command is not None
        assert result.resolved_command.command == "pytest tests/"
        assert result.resolved_command.cwd == "/home/user/project"
        assert result.resolved_command.timeout_secs == 300
        assert result.resolved_command.vars == {"test_dir": "tests"}

    def test_parse_minimal_metadata(self, tmp_path):
        """Parse metadata with only required fields."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "Minimal"
run_id = "run-456"
state = "failed"
duration_str = "0.1s"
"""
        )

        result = parse_metadata_file(metadata_path)

        assert result is not None
        assert result.command_name == "Minimal"
        assert result.run_id == "run-456"
        assert result.state == RunState.FAILED
        assert result.output == ""  # No output.txt
        assert result.output_file is None
        assert result.resolved_command is None

    def test_parse_missing_required_field(self, tmp_path):
        """Return None if required field is missing."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "Incomplete"
# Missing run_id and state
duration_str = "1s"
"""
        )

        result = parse_metadata_file(metadata_path)
        assert result is None

    def test_parse_invalid_state(self, tmp_path):
        """Return None if state is invalid."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "BadState"
run_id = "run-789"
state = "invalid_state"
duration_str = "1s"
"""
        )

        result = parse_metadata_file(metadata_path)
        assert result is None

    def test_parse_file_not_found(self, tmp_path):
        """Return None if file doesn't exist."""
        metadata_path = tmp_path / "nonexistent.toml"
        result = parse_metadata_file(metadata_path)
        assert result is None

    def test_parse_corrupted_toml(self, tmp_path):
        """Return None if TOML is corrupted."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text("this is not valid TOML {{{")

        result = parse_metadata_file(metadata_path)
        assert result is None

    def test_parse_missing_output_file(self, tmp_path):
        """Handle missing output.txt gracefully."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "NoOutput"
run_id = "run-999"
state = "success"
duration_str = "1s"
"""
        )

        result = parse_metadata_file(metadata_path)

        assert result is not None
        assert result.output == ""
        assert result.output_file is None

    def test_parse_unreadable_output_file(self, tmp_path):
        """Handle unreadable output.txt gracefully."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "BadOutput"
run_id = "run-111"
state = "success"
duration_str = "1s"
"""
        )

        # Create output.txt but make it unreadable (not possible on all systems)
        output_path = tmp_path / "output.txt"
        output_path.write_bytes(b"\xff\xfe Invalid UTF-8 \xff")

        result = parse_metadata_file(metadata_path)

        # Should still parse metadata, just with empty output
        assert result is not None
        assert result.command_name == "BadOutput"

    def test_parse_cancelled_run(self, tmp_path):
        """Parse a cancelled run."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "Cancelled"
run_id = "run-222"
state = "cancelled"
duration_str = "0.5s"
success = false
comment = "User cancelled"
"""
        )

        result = parse_metadata_file(metadata_path)

        assert result is not None
        assert result.state == RunState.CANCELLED
        assert result.success is False
        assert result.comment == "User cancelled"

    def test_parse_with_error(self, tmp_path):
        """Parse a failed run with error message."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "Failed"
run_id = "run-333"
state = "failed"
duration_str = "1s"
success = false
error = "Command exited with code 1"
"""
        )

        result = parse_metadata_file(metadata_path)

        assert result is not None
        assert result.state == RunState.FAILED
        assert result.success is False
        assert result.error == "Command exited with code 1"

    def test_parse_timestamps(self, tmp_path):
        """Parse timestamps correctly."""
        metadata_path = tmp_path / "metadata.toml"
        metadata_path.write_text(
            """
command_name = "Timed"
run_id = "run-444"
state = "success"
duration_str = "2s"
start_time = "2025-01-01T12:00:00"
end_time = "2025-01-01T12:00:02"
"""
        )

        result = parse_metadata_file(metadata_path)

        assert result is not None
        assert result.start_time is not None
        assert result.end_time is not None
        assert result.duration is not None
        assert result.duration.total_seconds() == 2.0
