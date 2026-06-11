---
name: patterns-spec-doc-section-extractor
description: SPEC_0 §5.3 section extractor stops at any line matching ^#{1,3}\s+ including # comments inside code fences — remove # comment lines from code blocks in that section
metadata:
  type: feedback
---

The `_extract_section_53` function in `test_groups_and_overlay.py` uses `re.match(r"^#{1,3}\s+", line)` to detect the end of the §5.3 section. This matches ANY line starting with 1–3 `#` characters followed by whitespace, including comment lines inside code fences (e.g., `# infrastructure/openldap/Dockerfile` inside a ` ```dockerfile` block).

**Why:** The extractor has no code-fence awareness — it treats `# comment` lines inside fenced blocks as headings and terminates section extraction prematurely.

**How to apply:** When writing or editing content inside `### 5.3 OpenLDAP Bootstrap Data` (or any section extracted by this pattern), do not include lines like `# path/to/file` inside code fences. Either omit the comment line or use a non-`#` prefix. Confirmed by test failure: section_53 fixture returned only content up to the first `# ` comment inside the dockerfile code block.
