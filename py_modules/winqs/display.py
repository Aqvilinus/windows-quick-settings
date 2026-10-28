"""Current refresh rate of the built-in display (else the first active one), read only.

The Frame Limit slider goes up to it. The plugin never changes the refresh rate (see CLAUDE.md). It comes from the same
DisplayConfig query hdr.py makes.
"""
from .hdr import active_path


def info():
    """{'hz': current refresh rate}."""
    r = active_path().targetInfo.refreshRate
    if not r.Denominator:
        raise OSError("the display reports no refresh rate")
    return {"hz": round(r.Numerator / r.Denominator)}
