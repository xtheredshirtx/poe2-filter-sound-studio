"""Round-trip-fidelity parser for PoE 2 ``.filter`` files (A.1, A.3).

The whole feature's safety rests on this module. The file is modelled as an
ordered list of :class:`RawLine` objects grouped into :class:`Block` objects.
Each ``RawLine`` keeps its exact content and exact terminator, so:

    serialize(parse(text)) == text          # byte-for-byte

No normalization of line endings, indentation, trailing whitespace, blank-line
runs, or inline comments ever happens here. Editing is done elsewhere
(``filter_visual_patcher``) at the line level; this module only *reads*.

Directive parsing is operator-aware: ``BaseType "X"`` is a substring match while
``BaseType == "X"`` is exact, and numeric directives carry their comparison
operator. This is pure code -- no I/O except the small :func:`read_text` /
:func:`write_text` helpers used by tests and the maintainer tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Directive vocabulary
# ---------------------------------------------------------------------------

#: Block headers. A block starts at one of these and runs to the next or EOF.
BLOCK_HEADERS = ("Show", "Hide")

#: Sound directives -- this feature must NEVER modify these.
SOUND_KEYWORDS = (
    "PlayAlertSound",
    "PlayAlertSoundPositional",
    "CustomAlertSound",
    "CustomAlertSoundOptional",
    "DisableDropSound",
    "EnableDropSound",
)

#: Visual directives this feature may rewrite.
VISUAL_KEYWORDS = (
    "SetTextColor",
    "SetBackgroundColor",
    "SetBorderColor",
    "SetFontSize",
    "PlayEffect",
    "MinimapIcon",
)

#: Numeric condition directives (carry a comparison operator).
NUMERIC_KEYWORDS = (
    "ItemLevel",
    "DropLevel",
    "AreaLevel",
    "WaystoneTier",
    "StackSize",
    "Quality",
    "GemLevel",
    "Sockets",
    "Width",
    "Height",
    "LinkedSockets",
    "BaseArmour",
    "BaseEvasion",
    "BaseEnergyShield",
    "BaseWard",
    "BaseDefencePercentile",
)

_OPERATORS = ("==", ">=", "<=", "=", ">", "<")

#: Condition/keyword directives recognised when *disabled* (commented-out), so a
#: plain ``# comment`` is not mistaken for a directive. Hoisted to module scope
#: so it isn't rebuilt on every line during a large-file parse.
_KNOWN_KEYWORDS = frozenset(
    BLOCK_HEADERS
    + SOUND_KEYWORDS
    + VISUAL_KEYWORDS
    + NUMERIC_KEYWORDS
    + (
        "Class",
        "BaseType",
        "Rarity",
        "Corrupted",
        "Identified",
        "Mirrored",
        "Continue",
        "HasExplicitMod",
        "HasInfluence",
        "AnyEnchantment",
        "SocketGroup",
        "UnidentifiedItemTier",
        "Replica",
        "HasEnchantment",
        "EnchantmentPassiveNode",
    )
)

# Split a file into (content, terminator) pairs without mangling anything.
_LINE_SPLIT_RE = re.compile(r"(\r\n|\r|\n)")

# A directive line: optional leading whitespace, an alphabetic keyword, the rest.
_DIRECTIVE_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<keyword>[A-Za-z]+)(?P<rest>.*)$")

# A commented-out directive, e.g. ``\t# SetTextColor 255 0 0``. Captures the
# marker so the patcher can re-enable it, but by default we treat it as a
# comment for fidelity.
_DISABLED_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<hash>#+[ \t]*)(?P<keyword>[A-Za-z]+)(?P<rest>.*)$"
)

# The idempotency sentinel this feature stamps on blocks it has restyled.
SENTINEL_RE = re.compile(r"^\s*#\s*\[ETVP\b.*\]\s*$")


# ---------------------------------------------------------------------------
# Parsed views
# ---------------------------------------------------------------------------


@dataclass
class Directive:
    """A parsed directive line (or a disabled, commented-out one).

    ``operator`` is one of ``"", "==", "=", ">", ">=", "<", "<="``. For
    ``BaseType``/``Class`` an ``==`` operator means *exact* match; anything else
    is PoE's default *substring* match. ``values`` are unquoted; ``raw_tokens``
    records whether each was quoted so we can reason about exactness.
    """

    indent: str
    keyword: str
    operator: str = ""
    values: list[str] = field(default_factory=list)
    raw_tokens: list[tuple[str, bool]] = field(default_factory=list)
    inline_comment: str = ""
    disabled: bool = False

    @property
    def exact(self) -> bool:
        """True when this directive uses the exact-match operator ``==``."""
        return self.operator == "=="

    def numeric_value(self) -> int | None:
        """First value parsed as int, or None if not numeric."""
        for v in self.values:
            try:
                return int(v)
            except ValueError:
                return None
        return None


@dataclass
class RawLine:
    """One physical line: exact content plus its exact terminator."""

    content: str
    newline: str  # "", "\n", "\r\n", or "\r"
    directive: Directive | None = None

    def raw(self) -> str:
        """The exact original text of this line, terminator included."""
        return self.content + self.newline

    @property
    def is_blank(self) -> bool:
        return self.content.strip() == ""

    @property
    def is_comment(self) -> bool:
        return self.content.lstrip().startswith("#")

    @property
    def is_sentinel(self) -> bool:
        return bool(SENTINEL_RE.match(self.content))


@dataclass
class Block:
    """A Show/Hide block: a contiguous slice of the document's line list.

    ``start``/``end`` index into :attr:`FilterDocument.lines` (``end`` is
    exclusive). The block owns every line from its header up to (but not
    including) the next header -- trailing comments and blank lines included --
    matching PoE's "until the next Show/Hide or EOF" rule.
    """

    lines: list[RawLine]
    start: int
    end: int
    index: int  # 0-based position among blocks

    # --- header -----------------------------------------------------------
    @property
    def header_line(self) -> RawLine:
        return self.lines[0]

    @property
    def header_keyword(self) -> str:
        d = self.lines[0].directive
        return d.keyword if d else self.lines[0].content.strip().split(" ", 1)[0]

    @property
    def is_hide(self) -> bool:
        return self.header_keyword.lower() == "hide"

    # --- directive access -------------------------------------------------
    def directives(self, keyword: str, include_disabled: bool = False) -> list[Directive]:
        """All enabled directives in this block with the given keyword."""
        kw = keyword.lower()
        out: list[Directive] = []
        for ln in self.lines:
            d = ln.directive
            if d is None or d.keyword.lower() != kw:
                continue
            if d.disabled and not include_disabled:
                continue
            out.append(d)
        return out

    def first(self, keyword: str) -> Directive | None:
        ds = self.directives(keyword)
        return ds[0] if ds else None

    def rarities(self) -> list[str]:
        out: list[str] = []
        for d in self.directives("Rarity"):
            out.extend(v for v in d.values)
        return out

    def class_values(self) -> list[tuple[str, bool]]:
        """(value, exact) pairs across all Class directives in the block."""
        out: list[tuple[str, bool]] = []
        for d in self.directives("Class"):
            out.extend((v, d.exact) for v in d.values)
        return out

    def basetype_values(self) -> list[tuple[str, bool]]:
        """(value, exact) pairs across all BaseType directives in the block."""
        out: list[tuple[str, bool]] = []
        for d in self.directives("BaseType"):
            out.extend((v, d.exact) for v in d.values)
        return out

    def sound_lines(self) -> list[RawLine]:
        out: list[RawLine] = []
        for ln in self.lines:
            d = ln.directive
            if d is not None and d.keyword in SOUND_KEYWORDS and not d.disabled:
                out.append(ln)
        return out

    def has_sentinel(self) -> bool:
        return any(ln.is_sentinel for ln in self.lines)

    def sentinel_line(self) -> RawLine | None:
        for ln in self.lines:
            if ln.is_sentinel:
                return ln
        return None


@dataclass
class FilterDocument:
    """The whole parsed file. Serialize me back to exact bytes."""

    lines: list[RawLine]
    blocks: list[Block]
    had_bom: bool = False

    def serialize(self) -> str:
        body = "".join(ln.raw() for ln in self.lines)
        return ("﻿" + body) if self.had_bom else body


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _split_lines(text: str) -> list[RawLine]:
    """Split text into RawLines, preserving every terminator exactly."""
    if text == "":
        return []
    parts = _LINE_SPLIT_RE.split(text)
    lines: list[RawLine] = []
    # parts alternates content, sep, content, sep, ..., trailing content.
    i = 0
    n = len(parts)
    while i < n:
        content = parts[i]
        sep = parts[i + 1] if i + 1 < n else ""
        # A trailing empty content with no separator means the text ended on a
        # newline -- there is no extra line to emit.
        if sep == "" and content == "" and i != 0:
            break
        lines.append(RawLine(content=content, newline=sep))
        i += 2
    return lines


def _split_inline_comment(rest: str) -> tuple[str, str]:
    """Split a directive's value section from a trailing ``# comment``.

    Respects quotes so a ``#`` inside a quoted value is not mistaken for a
    comment. Returns ``(values_part, comment_part)`` where ``comment_part``
    includes its leading whitespace and the ``#`` (or is empty).
    """
    in_quote = False
    for idx, ch in enumerate(rest):
        if ch == '"':
            in_quote = not in_quote
        elif ch == "#" and not in_quote:
            return rest[:idx], rest[idx:]
    return rest, ""


def _tokenize_values(values_part: str) -> list[tuple[str, bool]]:
    """Tokenize a value section into (value, was_quoted) pairs."""
    tokens: list[tuple[str, bool]] = []
    i = 0
    s = values_part
    n = len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j = s.find('"', i + 1)
            if j == -1:  # unterminated quote -- take the rest verbatim
                tokens.append((s[i + 1 :], True))
                break
            tokens.append((s[i + 1 : j], True))
            i = j + 1
        else:
            j = i
            while j < n and not s[j].isspace():
                j += 1
            tokens.append((s[i:j], False))
            i = j
    return tokens


def _parse_directive(content: str) -> Directive | None:
    """Parse one line's content into a Directive, or None if it isn't one."""
    stripped = content.strip()
    if stripped == "":
        return None

    disabled = False
    m = _DIRECTIVE_RE.match(content)
    if stripped.startswith("#"):
        # Could be a plain comment or a disabled directive. Only treat it as a
        # disabled directive if a real keyword follows the hashes.
        dm = _DISABLED_RE.match(content)
        if not dm:
            return None
        keyword = dm.group("keyword")
        if keyword not in _KNOWN_KEYWORDS:
            return None
        disabled = True
        indent = dm.group("indent")
        rest = dm.group("rest")
    elif m:
        keyword = m.group("keyword")
        indent = m.group("indent")
        rest = m.group("rest")
    else:
        return None

    values_part, comment = _split_inline_comment(rest)

    operator = ""
    vp = values_part.lstrip()
    leading_ws_len = len(values_part) - len(vp)
    for op in _OPERATORS:
        if vp.startswith(op):
            operator = op
            vp = vp[len(op) :]
            break
    # Preserve the original spacing layout only matters for serialize, which
    # uses the raw line; here we only need parsed semantics.
    raw_tokens = _tokenize_values(vp)
    values = [v for v, _q in raw_tokens]

    # Reconstruct inline_comment with its original leading whitespace so callers
    # that rebuild lines can keep it. (Patcher rebuilds from scratch instead.)
    _ = leading_ws_len  # not needed for semantics; kept for clarity
    return Directive(
        indent=indent,
        keyword=keyword,
        operator=operator,
        values=values,
        raw_tokens=raw_tokens,
        inline_comment=comment,
        disabled=disabled,
    )


def parse(text: str, had_bom: bool = False) -> FilterDocument:
    """Parse filter text into a :class:`FilterDocument`.

    ``had_bom`` records whether a UTF-8 BOM was stripped during decoding so
    :meth:`FilterDocument.serialize` can re-add it. When the BOM is left in the
    text as a ``\\ufeff`` character (e.g. text joined from ``readlines``), pass
    ``had_bom=False`` -- it round-trips as ordinary content.
    """
    lines = _split_lines(text)
    for ln in lines:
        ln.directive = _parse_directive(ln.content)

    blocks: list[Block] = []
    header_positions = [
        i
        for i, ln in enumerate(lines)
        if ln.directive is not None
        and not ln.directive.disabled
        and ln.directive.keyword in BLOCK_HEADERS
    ]
    for bi, start in enumerate(header_positions):
        end = header_positions[bi + 1] if bi + 1 < len(header_positions) else len(lines)
        blocks.append(Block(lines=lines[start:end], start=start, end=end, index=bi))

    return FilterDocument(lines=lines, blocks=blocks, had_bom=had_bom)


def serialize(doc: FilterDocument) -> str:
    """Inverse of :func:`parse` -- returns the exact original text."""
    return doc.serialize()


# ---------------------------------------------------------------------------
# I/O helpers (used by tests and tools; the app itself works on app.lines)
# ---------------------------------------------------------------------------


def read_text(path: str) -> tuple[str, bool]:
    """Read a filter file, returning ``(text, had_bom)``.

    Decodes as UTF-8, detecting and stripping a leading BOM but reporting it so
    callers can preserve it on write.
    """
    with open(path, "rb") as f:
        raw = f.read()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    if had_bom:
        raw = raw[3:]
    return raw.decode("utf-8"), had_bom


def write_text(path: str, text: str, had_bom: bool = False) -> None:
    """Write filter text as UTF-8, re-adding a BOM if one was present."""
    data = text.encode("utf-8")
    if had_bom and not text.startswith("﻿"):
        data = b"\xef\xbb\xbf" + data
    with open(path, "wb") as f:
        f.write(data)


def block_signature_counts(doc: FilterDocument) -> dict[str, int]:
    """Quick structural summary: counts of sound/visual/sentinel lines.

    Used by the validator as a cheap pre/post comparison.
    """
    counts: dict[str, int] = {"blocks": len(doc.blocks)}
    for ln in doc.lines:
        d = ln.directive
        if d is None or d.disabled:
            continue
        if d.keyword in SOUND_KEYWORDS:
            counts[f"sound:{d.keyword}"] = counts.get(f"sound:{d.keyword}", 0) + 1
    return counts


__all__ = [
    "BLOCK_HEADERS",
    "SOUND_KEYWORDS",
    "VISUAL_KEYWORDS",
    "NUMERIC_KEYWORDS",
    "SENTINEL_RE",
    "Directive",
    "RawLine",
    "Block",
    "FilterDocument",
    "parse",
    "serialize",
    "read_text",
    "write_text",
    "block_signature_counts",
]
