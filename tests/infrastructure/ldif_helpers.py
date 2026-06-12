"""tests/infrastructure/ldif_helpers.py — shared LDIF parsing utilities.

WHY centralised: two test files (test_openldap_ldif.py and
tests/infrastructure/openldap/test_groups_and_overlay.py) need to parse
infrastructure/openldap/bootstrap.ldif.  The stronger RFC-2849-correct parser
lives here so both files share a single implementation.

The parser handles:
- Blank lines: end the current entry and start a new one.
- Comment lines (starting with '#'): skipped WITHOUT ending the current entry.
- Continuation lines (RFC-2849 §2.1: line starting with a single space): folded
  into the preceding attribute value — leading space stripped, remainder appended
  to the last stored value.
"""

from __future__ import annotations

from pathlib import Path


def load_ldif_lines(ldif_file: Path) -> list[str]:
    """Return every line from *ldif_file*, with newlines stripped.

    Args:
        ldif_file: Absolute path to the LDIF file to read.

    Returns:
        A list of stripped lines (no trailing newlines).
    """
    return ldif_file.read_text(encoding="utf-8").splitlines()


def parse_ldif_blocks(lines: list[str]) -> dict[str, dict[str, list[str]]]:
    """Parse LDIF lines into blocks keyed by dn value.

    Returns a dict mapping ``dn_value`` → ``{attr_name: [value, ...]}``.

    RFC-2849 behaviours handled:
    - Blank lines end the current entry and start a new one.
    - Comment lines (starting with ``#``) are skipped without ending the
      current entry — a comment inside an entry is a comment, not a record
      separator.
    - Continuation lines (RFC-2849 §2.1: a line starting with a single space)
      are folded into the preceding attribute value: the leading space is
      stripped and the remainder is appended to the last value stored.

    Args:
        lines: Output of :func:`load_ldif_lines` — stripped text lines.

    Returns:
        Mapping of DN string to attribute dict.
    """
    blocks: dict[str, dict[str, list[str]]] = {}
    current_dn: str | None = None
    current_block: dict[str, list[str]] = {}
    last_attr: str | None = None  # tracks the attribute to fold continuations into

    for line in lines:
        # RFC-2849 continuation line: starts with exactly one space
        if line.startswith(" ") and current_dn is not None and last_attr is not None:
            # Fold the continuation value onto the last attribute value collected
            continuation = line[1:]  # strip the single leading space
            if current_block.get(last_attr):
                current_block[last_attr][-1] += continuation
            continue

        stripped = line.strip()

        # Blank line → end of current entry
        if not stripped:
            if current_dn is not None:
                blocks[current_dn] = current_block
                current_dn = None
                current_block = {}
                last_attr = None
            continue

        # Comment line → skip; does NOT end the current entry
        if stripped.startswith("#"):
            continue

        if ":" not in stripped:
            continue

        attr, _, value = stripped.partition(":")
        attr = attr.strip().lower()
        value = value.strip()

        if attr == "dn":
            if current_dn is not None:
                blocks[current_dn] = current_block
            current_dn = value
            current_block = {"dn": [value]}
            last_attr = "dn"
        elif current_dn is not None:
            current_block.setdefault(attr, []).append(value)
            last_attr = attr

    if current_dn is not None:
        blocks[current_dn] = current_block

    return blocks
