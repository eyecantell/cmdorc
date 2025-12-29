"""
Runtime variable resolution with environment variable support.

This module handles Phase 2 (variable merging) and Phase 3 (template substitution)
of the variable resolution pipeline. Phase 1 (load-time resolution) has been removed.

Variable merge priority (highest to lowest):
  1. Call-time variables (passed to run_command/trigger)
  2. Command-specific variables (from CommandConfig.vars)
  3. Environment variables (from os.environ)
  4. Global variables (from RunnerConfig.vars)

Example:
  >>> global_vars = {"base": "/app", "env": "dev"}
  >>> command_vars = {"env": "staging"}  # Overrides global
  >>> env_vars = {"DEBUG": "1"}
  >>> call_time = {"env": "prod"}  # Final override
  >>> result = merge_vars(global_vars, env_vars, command_vars, call_time)
  >>> result["env"]
  'prod'
"""

from __future__ import annotations

import logging
import os
import re

from .command_config import CommandConfig
from .run_result import ResolvedCommand

logger = logging.getLogger(__name__)

# Pattern for {{ variable_name }}
VAR_PATTERN = re.compile(r"\{\{\s*([\w_]+)\s*\}\}")

# Pattern for $VAR_NAME environment variable syntax (uppercase only)
ENV_VAR_PATTERN = re.compile(r"\$([A-Z_][A-Z0-9_]*)")


# =====================================================================
#   Variable Resolution Helpers
# =====================================================================


def resolve_double_brace_vars(value: str, vars_dict: dict[str, str], *, max_depth: int = 10) -> str:
    """
    Resolve {{ var }} occurrences using vars_dict.
    Only replaces double-braced variables, not single-brace placeholders.
    Supports nested resolution with a maximum depth to avoid infinite loops.

    Args:
        value: String containing {{ variable_name }} references
        vars_dict: Dictionary mapping variable names to values
        max_depth: Maximum nesting depth to prevent infinite loops (default 10)

    Returns:
        String with all {{ }} references resolved

    Raises:
        ValueError: If a variable is missing or nested resolution never stabilizes
    """

    for _ in range(max_depth):
        changed = False

        def repl(match: re.Match) -> str:
            nonlocal changed
            var_name = match.group(1)

            if var_name not in vars_dict:
                raise ValueError(f"Missing variable: '{var_name}'")

            changed = True
            return vars_dict[var_name]

        new_value = VAR_PATTERN.sub(repl, value)

        if not changed:
            return new_value  # fully resolved

        value = new_value

    # If still unresolved, we hit a cycle or unresolvable nested structure
    if VAR_PATTERN.search(value):
        # Extract unresolved variable names to help with debugging
        unresolved_vars = re.findall(r'\{\{\s*(\w+)\s*\}\}', value)
        raise ValueError(
            f"Failed to resolve variables after {max_depth} passes. "
            f"Remaining unresolved variables in '{value}': {unresolved_vars}. "
            f"This may indicate a circular dependency or missing variable definition."
        )

    return value


def merge_vars(
    global_vars: dict[str, str] | None = None,
    env_vars: dict[str, str] | None = None,
    command_vars: dict[str, str] | None = None,
    call_time_vars: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Merge variables in priority order (higher priority overrides lower).

    Merge order:
      1. Global variables (lowest priority)
      2. Environment variables
      3. Command-specific variables
      4. Call-time variables (highest priority)

    Args:
        global_vars: Global variables from RunnerConfig.vars (may contain templates)
        env_vars: Environment variables (defaults to os.environ if None)
        command_vars: Command-specific variables from CommandConfig.vars
        call_time_vars: Per-run overrides from run_command/trigger

    Returns:
        Merged dictionary with later sources overriding earlier ones.
    """
    merged: dict[str, str] = {}

    # Priority 1: Global variables (base)
    if global_vars:
        merged.update(global_vars)

    # Priority 2: Environment variables
    if env_vars is None:
        env_vars = dict(os.environ)
    merged.update(env_vars)

    # Priority 3: Command-specific variables
    if command_vars:
        merged.update(command_vars)

    # Priority 4: Call-time overrides (highest priority)
    if call_time_vars:
        merged.update(call_time_vars)

    return merged


def _preprocess_env_vars(template_str: str) -> str:
    """
    Convert $VAR_NAME syntax to {{ VAR_NAME }} for uniform resolution.

    This allows users to write $HOME instead of {{ HOME }} in configs.
    Only converts uppercase identifiers starting with $ (prevents $$shell escaping).

    Args:
        template_str: String that may contain $VAR_NAME references

    Returns:
        String with $VAR_NAME converted to {{ VAR_NAME }}

    Example:
        >>> _preprocess_env_vars("home is $HOME, cost is $$5")
        'home is {{ HOME }}, cost is $$5'
    """

    def replace_env_var(match: re.Match) -> str:
        var_name = match.group(1)
        return f"{{{{ {var_name} }}}}"

    return ENV_VAR_PATTERN.sub(replace_env_var, template_str)


def resolve_runtime_vars(
    template_str: str,
    merged_vars: dict[str, str],
    *,
    max_depth: int = 10,
) -> str:
    """
    Resolve {{ var }} and $VAR templates at runtime.

    Supports both {{ VAR }} and $VAR syntax for variable substitution.
    Nested variables are supported (e.g., {{ base }}/{{ subdir }}).

    Args:
        template_str: String containing templates
        merged_vars: Pre-merged variable dictionary (from merge_vars)
        max_depth: Maximum nesting depth for resolution (prevents infinite loops)

    Returns:
        Fully resolved string with all variables substituted

    Raises:
        ValueError: If variable is missing, cycles detected, or max depth exceeded
    """
    # First, convert $VAR_NAME to {{ VAR_NAME }} for uniform handling
    processed = _preprocess_env_vars(template_str)

    # Then resolve using local resolve_double_brace_vars function
    try:
        return resolve_double_brace_vars(processed, merged_vars, max_depth=max_depth)
    except ValueError as e:
        # Enrich error with context
        raise ValueError(f"In template '{template_str}': {e}") from e


def prepare_resolved_command(
    config: CommandConfig,
    global_vars: dict[str, str],
    call_time_vars: dict[str, str] | None = None,
    include_env: bool = True,
) -> ResolvedCommand:
    """
    Create a ResolvedCommand by merging and resolving all variables.

    This is the main function called by CommandOrchestrator._prepare_run().
    It performs Phase 2 (variable merging) and Phase 3 (template substitution).

    Steps:
      1. Merge variables in priority order
      2. Resolve command string
      3. Resolve env dict values
      4. Merge resolved env with system environment
      5. Create ResolvedCommand with frozen variable snapshot

    Args:
        config: CommandConfig with template strings (command, env vars, etc.)
        global_vars: RunnerConfig.vars (may contain templates)
        call_time_vars: Optional per-run variable overrides
        include_env: Whether to include os.environ (default True)

    Returns:
        ResolvedCommand with all templates resolved and frozen

    Raises:
        ValueError: If variable resolution fails (missing var, cycles, etc.)

    Example:
        >>> config = CommandConfig(
        ...     name="Deploy",
        ...     command="deploy --target={{ target }}",
        ...     vars={"target": "staging"}
        ... )
        >>> global_vars = {"base": "/app"}
        >>> resolved = prepare_resolved_command(config, global_vars)
        >>> resolved.command
        'deploy --target=staging'
    """
    # Step 1: Merge variables
    merged_vars = merge_vars(
        global_vars=global_vars,
        env_vars=dict(os.environ) if include_env else None,
        command_vars=config.vars,
        call_time_vars=call_time_vars,
    )

    # Step 2: Resolve command string
    resolved_command = resolve_runtime_vars(config.command, merged_vars)

    # Step 3: Resolve env dict values (keys stay as-is)
    resolved_env = {}
    for key, value in config.env.items():
        resolved_env[key] = resolve_runtime_vars(value, merged_vars)

    # Step 4: Merge resolved_env with system environment
    # This ensures the subprocess gets both system env and config-specified env
    final_env = dict(os.environ) if include_env else {}
    final_env.update(resolved_env)

    # Step 5: Create ResolvedCommand with frozen snapshot of merged variables
    return ResolvedCommand(
        command=resolved_command,
        cwd=str(config.cwd) if config.cwd else None,
        env=final_env,
        timeout_secs=config.timeout_secs,
        vars=merged_vars.copy(),  # Frozen snapshot for this run
    )
