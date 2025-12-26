"""
History loader for loading persisted command runs from disk on startup.

Loads RunResult objects from metadata.toml files and populates CommandRuntime
history based on keep_in_memory settings.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .command_config import OutputStorageConfig
from .command_runtime import CommandRuntime
from .metadata_parser import parse_metadata_file

logger = logging.getLogger(__name__)


class HistoryLoader:
    """Loads persisted command history from disk on startup."""

    def __init__(self, runtime: CommandRuntime, output_storage: OutputStorageConfig):
        """
        Initialize history loader.

        Args:
            runtime: CommandRuntime instance to populate with loaded history
            output_storage: OutputStorageConfig with directory and retention settings
        """
        self._runtime = runtime
        self._output_storage = output_storage

    def load_all(self) -> dict[str, int]:
        """
        Load persisted history for all registered commands.

        Strategy:
        - Load up to keep_in_memory runs from disk (based on actual files available)
        - Ignore disk's keep_history setting (only controls future writes)
        - If keep_in_memory=0, skip loading (no in-memory history)
        - If keep_in_memory=-1, load all available files (unlimited)
        - If keep_in_memory=N>0, load min(N, files_available)

        Returns:
            Dict mapping command_name -> number of runs loaded
        """
        if not self._output_storage.is_enabled:
            logger.debug("Output storage disabled, skipping history load")
            return {}

        base_dir = Path(self._output_storage.directory)
        if not base_dir.exists():
            logger.debug(f"Output directory {base_dir} does not exist, skipping history load")
            return {}

        loaded_counts = {}

        for command_name in self._runtime.list_commands():
            count = self._load_command_history(command_name, base_dir)
            if count > 0:
                loaded_counts[command_name] = count

        total = sum(loaded_counts.values())
        if total > 0:
            logger.info(f"Loaded {total} persisted runs for {len(loaded_counts)} commands")

        return loaded_counts

    def _load_command_history(self, command_name: str, base_dir: Path) -> int:
        """
        Load history for a single command.

        Args:
            command_name: Name of command to load
            base_dir: Base output directory

        Returns:
            Number of runs loaded
        """
        config = self._runtime.get_command(command_name)
        if not config:
            return 0

        # Determine how many runs to load based on keep_in_memory
        memory_limit = config.keep_in_memory

        # Case 1: No in-memory history → don't load anything
        if memory_limit == 0:
            logger.debug(f"Skipping history load for '{command_name}' (keep_in_memory=0)")
            return 0

        # Build command output directory
        command_dir = base_dir / command_name
        if not command_dir.exists():
            logger.debug(f"No output directory for '{command_name}', skipping")
            return 0

        # Find all run directories (sorted by mtime, oldest first)
        try:
            run_dirs = sorted(
                [d for d in command_dir.iterdir() if d.is_dir()],
                key=lambda p: p.stat().st_mtime,  # Oldest first
            )
        except OSError as e:
            logger.warning(f"Could not list run directories for '{command_name}': {e}")
            return 0

        if not run_dirs:
            logger.debug(f"No run directories found for '{command_name}'")
            return 0

        # Select runs to load based on memory_limit
        # Case 2: Unlimited memory → load all available
        if memory_limit == -1:
            runs_to_load = run_dirs
        # Case 3: Limited memory → load min(memory_limit, files_available)
        else:
            # Load the most recent runs (up to memory_limit)
            runs_to_load = run_dirs[-memory_limit:] if len(run_dirs) > memory_limit else run_dirs

        # Parse metadata files
        loaded_results = []
        for run_dir in runs_to_load:
            metadata_file = run_dir / "metadata.toml"
            if not metadata_file.exists():
                logger.debug(f"No metadata.toml in {run_dir}, skipping")
                continue

            result = parse_metadata_file(metadata_file)
            if result:
                loaded_results.append(result)

        if not loaded_results:
            return 0

        # Populate runtime with loaded results (oldest to newest for deque)
        # The loaded_results are already in chronological order (oldest first)
        for result in loaded_results:
            # Add to history deque (respects maxlen automatically)
            self._runtime.add_to_history(command_name, result)

            # Update latest_result with newest (last one will be the newest)
            if result.end_time:
                current_latest = self._runtime._latest_result.get(command_name)
                if not current_latest or (result.end_time > current_latest.end_time):
                    self._runtime._latest_result[command_name] = result

        limit_str = "unlimited" if memory_limit == -1 else str(memory_limit)
        logger.debug(
            f"Loaded {len(loaded_results)} runs for '{command_name}' "
            f"(keep_in_memory={limit_str}, available={len(run_dirs)})"
        )
        return len(loaded_results)
