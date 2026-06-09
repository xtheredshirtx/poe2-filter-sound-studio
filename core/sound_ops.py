"""Pure, line-level sound-directive editing for filter blocks.

Shared by the per-tier sound assigner and the existing "bulk replace sound in
the visible set" action so the replace/insert logic lives in one tested place.

Everything here operates on ``lines`` (the file as a list of strings, each
including its trailing newline) plus a block's ``[start, end)`` range. No file
I/O. ``set_custom_sound`` may *insert* a line, growing the list by one — callers
applying to several blocks must process them in descending ``start`` order so an
insert can't shift the indices of blocks not yet handled.
"""

from __future__ import annotations

from core.parser import SOUND_RE_CUSTOM, SOUND_RE_PLAY

_SHOWHIDE = ("Show", "Hide")


def block_bounds(lines: list[str], start: int) -> tuple[int, int]:
    """Return ``(start, end_exclusive)`` for the block beginning at ``start``.

    The block runs to the next ``Show``/``Hide`` header or end of file.
    """
    i = start + 1
    n = len(lines)
    while i < n and not lines[i].strip().startswith(_SHOWHIDE):
        i += 1
    return start, i


def detect_indent(lines: list[str], start: int, end: int) -> str:
    """Indentation used by the block's body (tabs/spaces); defaults to a tab."""
    for j in range(start + 1, end):
        line = lines[j]
        if not line.strip():
            continue
        leading = len(line) - len(line.lstrip(" \t"))
        if leading > 0:
            return line[:leading]
    return "\t"


def set_custom_sound(
    lines: list[str],
    start: int,
    end: int,
    filename: str,
    volume: int = 300,
    *,
    preserve_volume: bool = False,
    keep_disabled: bool = False,
    active_only: bool = True,
) -> bool:
    """Give the block a ``CustomAlertSound "<filename>" <vol>``.

    Replaces existing sound directive line(s) in place (preserving indent), or
    inserts one after the conditions if the block has none.

    * ``preserve_volume`` — keep each replaced line's existing volume (fallback to
      ``volume``) instead of forcing ``volume``.
    * ``keep_disabled`` — keep a commented-out (``# CustomAlertSound``) line
      commented instead of enabling it.
    * ``active_only`` — only replace *active* (non-commented) sound lines and
      ignore commented ones (so a disabled alternate isn't accidentally enabled).

    Returns ``True`` if a line was inserted (the block had no matching sound),
    ``False`` if existing line(s) were replaced. Mutates ``lines``.
    """
    replaced = False
    for i in range(start, end):
        raw = lines[i].rstrip("\n")
        stripped = raw.strip()
        leading = raw[: len(raw) - len(raw.lstrip(" \t"))]

        m_c = SOUND_RE_CUSTOM.match(stripped)
        m_p = SOUND_RE_PLAY.match(stripped)
        if m_c:
            comment_prefix, _kw, _file, vol = m_c.groups()
        elif m_p:
            comment_prefix, _kw, _sid, vol = m_p.groups()
        else:
            continue

        if active_only and comment_prefix:
            continue

        prefix = (comment_prefix or "") if keep_disabled else ""
        vol_part = f" {vol}" if (preserve_volume and vol) else f" {volume}"
        lines[i] = f'{leading}{prefix}CustomAlertSound "{filename}"{vol_part}\n'
        replaced = True

    if not replaced:
        indent = detect_indent(lines, start, end)
        lines.insert(end, f'{indent}CustomAlertSound "{filename}" {volume}\n')
        return True
    return False


def remove_custom_sound(lines: list[str], start: int, end: int) -> int:
    """Delete *active* sound directive lines from the block. Returns the count.

    Only removes enabled ``CustomAlertSound``/``PlayAlertSound[Positional]`` lines;
    commented-out lines are left as-is. Mutates ``lines``.
    """
    removed = 0
    i = start
    stop = end
    while i < stop:
        stripped = lines[i].rstrip("\n").strip()
        m_c = SOUND_RE_CUSTOM.match(stripped)
        m_p = SOUND_RE_PLAY.match(stripped)
        is_active = (m_c is not None and not m_c.group(1)) or (m_p is not None and not m_p.group(1))
        if is_active:
            del lines[i]
            stop -= 1
            removed += 1
            continue
        i += 1
    return removed


__all__ = ["block_bounds", "detect_indent", "set_custom_sound", "remove_custom_sound"]
