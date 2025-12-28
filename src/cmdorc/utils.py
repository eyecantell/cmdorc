# cmdorc/utils.py
"""General-purpose utilities for cmdorc."""


def format_duration(secs: float) -> str:
    """Format seconds into a human-readable duration string.

    Args:
        secs: Number of seconds to format

    Returns:
        Human-readable string like "452ms", "2.4s", "1m 23s", "2h 5m", "1d 3h", "2w 3d"

    Examples:
        >>> format_duration(0.5)
        '500ms'
        >>> format_duration(90)
        '1m 30s'
        >>> format_duration(3661)
        '1h 1m'
    """
    if secs < 1:
        return f"{secs * 1000:.0f}ms"
    if secs < 60:
        return f"{secs:.1f}s"
    mins, secs = divmod(int(secs), 60)
    if mins < 60:
        return f"{mins}m {secs}s"
    hrs, mins = divmod(mins, 60)
    if hrs < 24:
        return f"{hrs}h {mins}m"
    days, hrs = divmod(hrs, 24)
    if days < 7:
        return f"{days}d {hrs}h"
    weeks, days = divmod(days, 7)
    return f"{weeks}w {days}d" if days else f"{weeks}w"
