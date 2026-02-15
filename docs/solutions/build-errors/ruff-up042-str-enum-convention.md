---
title: "Suppressing Ruff UP042 for (str, Enum) Convention"
category: build-errors
tags: [ruff, linting, enum, python, pyproject-toml]
module: broker.types
symptom: "Ruff UP042 warning on all (str, Enum) classes"
root_cause: "Project convention uses (str, Enum) but ruff recommends StrEnum"
date_solved: 2026-02-14
---

# Suppressing Ruff UP042 for (str, Enum) Convention

## Problem

After implementing Step 2 domain types using the `(str, Enum)` pattern (the
established project convention per CLAUDE.md), ruff started flagging every enum
class with rule **UP042**, suggesting to use `StrEnum` instead.

```python
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
```

Ruff output:

```
UP042: Class `Side` inherits from both `str` and `Enum`. Use `StrEnum` instead.
```

This affected all string-based enum classes across the `broker.types` module and
anywhere else the pattern appeared.

## Symptom

Running `ruff check` produces UP042 warnings on every `(str, Enum)` class
definition, causing CI lint checks to fail.

## Investigation

1. **Rule origin** -- UP042 is part of ruff's `UP` (pyupgrade) rule set, which
   suggests modernizing Python code. Since `StrEnum` was added in Python 3.11
   and the project targets Python 3.12+, ruff considers `(str, Enum)` outdated.

2. **Why we chose `(str, Enum)`** -- The project convention was deliberately
   established in CLAUDE.md for these reasons:

   - **Serialization-friendly**: `(str, Enum)` values serialize cleanly to JSON
     via `value` without surprises. The `str()` behavior is explicit.
   - **Explicit is better than implicit**: With `(str, Enum)`, calling `str()`
     on an enum member returns the full representation
     (e.g., `Side.BUY`), while `.value` returns `"buy"`. With `StrEnum`,
     `str()` returns just `"buy"` automatically, which can mask bugs where
     code accidentally uses `str()` instead of `.value`.
   - **Codebase consistency**: All existing enums across the project use this
     pattern. Mixing `(str, Enum)` and `StrEnum` would create inconsistency.
   - **Behavioral differences**: `StrEnum` members compare equal to plain
     strings (`Side.BUY == "buy"` is `True` with both, but `StrEnum` also makes
     `str(Side.BUY) == "buy"`). The `(str, Enum)` pattern gives more control
     over when string coercion happens.

3. **Options considered**:
   - Per-line `# noqa: UP042` comments on every enum class -- rejected because
     it adds noise to every enum definition across the codebase.
   - Global ignore in `pyproject.toml` -- chosen as the clean solution.

## Solution

Add `"UP042"` to the ruff ignore list in `backend/pyproject.toml`:

```toml
[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "N",    # pep8-naming
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "SIM",  # flake8-simplify
    "RUF",  # ruff-specific
]
ignore = [
    "UP042", # project convention: (str, Enum) not StrEnum
]
```

The inline comment documents the reason for the suppression so future developers
understand it is intentional.

## Root Cause

Ruff's `UP` (pyupgrade) rule set includes UP042, which recommends replacing
`class Foo(str, Enum)` with `class Foo(StrEnum)` for Python 3.11+ targets. This
conflicts with the project's deliberate convention of using `(str, Enum)` for
all string-based enumerations, as documented in CLAUDE.md under Python Style.

## Prevention

- When establishing project conventions that conflict with linter defaults,
  suppress the rule **globally** in `pyproject.toml` rather than adding per-line
  `# noqa` comments. This keeps the codebase clean and documents the decision in
  one place.
- Always include a brief comment next to the ignored rule explaining why it is
  suppressed (e.g., `# project convention: (str, Enum) not StrEnum`).
- If the project ever decides to migrate to `StrEnum`, remove `"UP042"` from
  the ignore list and let ruff flag all instances for batch migration.
