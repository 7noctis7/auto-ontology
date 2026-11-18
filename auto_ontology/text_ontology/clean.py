# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Clean text copied out of a PDF before it is extracted.

PDF text carries noise a model tries to turn into facts: diagram labels
(``Hash01``, ``Prev Hash Nonce``), code, formulas, numeric tables, page
numbers, citation markers and the reference list. Its lines are also cut at
the page width, so paragraphs are lost and chunks break mid-thought.

:func:`clean_text` drops that noise and rejoins wrapped lines into
paragraphs. It only removes or rejoins: no word of the prose is changed.
The heuristics are conservative, so some noise can survive, but prose
sentences are kept.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

_REFERENCES_HEADING = re.compile(
    r"^\s*(references|bibliography|works cited|références|bibliographie)\s*:?\s*$",
    re.IGNORECASE,
)
_PAGE_NUMBER = re.compile(r"^\s*(?:page\s*)?\d{1,4}\s*$", re.IGNORECASE)
_CITATION = re.compile(r"\s?\[\d+(?:\s*[-–,]\s*\d+)*\]")
_NUMBERED_HEADING = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+\S")
_CODE_PATTERNS = [
    re.compile(r"^\s*#\s*(?:include|define|import)\b"),
    re.compile(r"^\s*(?:for|while|if|switch)\s*\("),
    re.compile(
        r"^\s*(?:double|int|float|void|char|long|bool|unsigned)\s+[\w*]+\s*[(=;,]"
    ),
    re.compile(r"^\s*[{}]+;?\s*$"),
    re.compile(r"^\s*(?:def|class)\s+\w+.*:\s*$"),
    re.compile(r"^\s*return\b[^.]*;\s*$"),
]
_BULLET = re.compile(r"^\s*(?:[-•*–·▪◦]|\(?\d{1,3}[.)])\s+\S")
_LINE_HYPHEN = re.compile(r"([^\W\d_]+)-\n([^\W\d_]+-?)")
_WORD = re.compile(r"[^\W\d_]+")
_COMPOUND = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)+")
_MATH = re.compile(r"[=<>≤≥≠∑∏∞∫√±×÷⋅−^{}|]")
_SENTENCE_END = re.compile(r"[.!?:…]\s*$")


@dataclass
class CleanResult:
    """The cleaned text, and how many lines each rule removed."""

    text: str
    removed: dict[str, int] = field(default_factory=dict)

    def summary_fr(self) -> str | None:
        """The same summary in French, for the studio."""
        total = sum(self.removed.values())
        if not total:
            return None
        return (
            f"Bruit de PDF retiré : {total} élément{'s' if total > 1 else ''} "
            "(schémas, code, formules, renvois, bibliographie)."
        )

    def summary(self) -> str | None:
        """``"Text cleaned: removed 12 diagram-label lines, ..."`` or ``None``."""
        parts = [
            f"{n} {kind}{'s' if n > 1 else ''}" for kind, n in self.removed.items()
        ]
        return f"Text cleaned: removed {', '.join(parts)}." if parts else None


def _is_code(line: str) -> bool:
    if any(p.search(line) for p in _CODE_PATTERNS):
        return True
    # A statement: ends with `;` and assigns or calls something.
    return line.rstrip().endswith(";") and bool(re.search(r"[=()]", line))


def _is_formula(line: str) -> bool:
    """A formula or a numeric table row, not a sentence that uses a symbol."""
    stripped = line.strip()
    words = re.findall(r"[^\W\d_]{2,}", stripped)
    if _MATH.search(stripped) and len(words) < 6:
        return True
    visible = [c for c in stripped if not c.isspace()]
    letters = sum(c.isalpha() for c in visible)
    return bool(visible) and letters / len(visible) < 0.5 and len(stripped) <= 80


def _is_fragment(line: str) -> bool:
    """What is left of a formula once its symbols are gone: ``qz``, ``z k``."""
    return all(len(token) <= 2 for token in line.split())


@dataclass(frozen=True)
class _Vocabulary:
    """What the text spells elsewhere: whole words and hyphenated compounds."""

    words: frozenset[str]
    compounds: frozenset[str]


def _vocabulary(text: str) -> _Vocabulary:
    unbroken = _LINE_HYPHEN.sub(" ", text)
    return _Vocabulary(
        words=frozenset(w.lower() for w in _WORD.findall(unbroken)),
        compounds=frozenset(c.lower() for c in _COMPOUND.findall(unbroken)),
    )


def _join_hyphenated(left: str, right: str, vocabulary: _Vocabulary) -> str:
    """Rejoin a word cut by a hyphen at a line end, keeping a real compound's hyphen.

    ``computa-`` + ``tional`` is a typesetter's cut; ``proof-`` + ``of-work``
    and ``double-`` + ``spending`` are compounds. The text itself decides:
    the joined word spelled whole elsewhere means a cut; the hyphenated form
    elsewhere, or a second part that is a word of its own, means a compound.
    Anything else is taken for a cut, as most line-end hyphens are.
    """
    first_words, second_words = _WORD.findall(left), _WORD.findall(right)
    first = first_words[-1].lower() if first_words else ""
    second = second_words[0].lower() if second_words else ""
    if not (first and second):
        return left + "-" + right
    continues = right.lstrip().startswith(second_words[0] + "-")  # of-work
    if first + second in vocabulary.words:
        return left + right
    if (
        continues
        or f"{first}-{second}" in vocabulary.compounds
        or second in vocabulary.words
    ):
        return left + "-" + right
    return left + right


def rejoin_line_breaks(text: str) -> str:
    """Rejoin words cut by a hyphen at a line end (see :func:`_join_hyphenated`)."""
    vocabulary = _vocabulary(text)
    return _LINE_HYPHEN.sub(
        lambda m: _join_hyphenated(m.group(1), m.group(2), vocabulary), text
    )


def _is_short_label(line: str) -> bool:
    """A line that reads like a diagram label: a few words, no sentence end."""
    stripped = line.strip()
    if (
        _NUMBERED_HEADING.match(stripped)
        or _SENTENCE_END.search(stripped)
        or _BULLET.match(stripped)  # a list item, not a label
    ):
        return False
    return len(stripped.split()) <= 4


def _drop_label_runs(lines: list[str], removed: dict[str, int]) -> list[str]:
    """Drop runs of 3+ consecutive short lines, except before the first prose.

    Lines before the first long line are the title block (title, authors,
    contact) and are kept: they hold facts too.
    """
    first_prose = next(
        (i for i, line in enumerate(lines) if len(line.split()) >= 7),
        len(lines),
    )
    kept: list[str] = []
    index = 0
    while index < len(lines):
        if (
            index < first_prose
            or not _is_short_label(lines[index])
            or not lines[index].strip()
        ):
            kept.append(lines[index])
            index += 1
            continue
        end = index
        while end < len(lines) and lines[end].strip() and _is_short_label(lines[end]):
            end += 1
        if end - index >= 3:
            removed["diagram-label line"] = (
                removed.get("diagram-label line", 0) + end - index
            )
        else:
            kept.extend(lines[index:end])
        index = end
    return kept


def _paragraphs(lines: list[str], vocabulary: _Vocabulary) -> list[str]:
    """Rejoin lines wrapped at the page width into paragraphs."""
    prose = [len(line) for line in lines if len(line.split()) > 6]
    width = statistics.quantiles(prose, n=4)[2] if len(prose) >= 4 else 0
    paragraphs: list[str] = []
    current = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            if current:
                paragraphs.append(current)
                current = ""
            continue
        standalone = _NUMBERED_HEADING.match(line) and len(line.split()) <= 8
        if standalone or (width and len(line.split()) <= 6 and not current):
            if current:
                paragraphs.append(current)
            paragraphs.append(line)
            current = ""
            continue
        if not current:
            current = line
        elif current.endswith("-") and line[:1].islower():
            current = _join_hyphenated(current[:-1], line, vocabulary)
        else:
            current += " " + line
        # A sentence ending well short of the page width ends the paragraph.
        if width and _SENTENCE_END.search(line) and len(raw.rstrip()) < 0.8 * width:
            paragraphs.append(current)
            current = ""
    if current:
        paragraphs.append(current)
    return paragraphs


def clean_text(text: str) -> CleanResult:
    """Drop PDF noise from *text* and rejoin its wrapped lines into paragraphs."""
    removed: dict[str, int] = {}

    def count(kind: str, n: int = 1) -> None:
        removed[kind] = removed.get(kind, 0) + n

    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    vocabulary = _vocabulary(text)
    lines = text.split("\n")

    # The reference list runs to the end once its heading is past the middle.
    for index, line in enumerate(lines):
        if index > len(lines) // 2 and _REFERENCES_HEADING.match(line):
            count("reference-list line", len(lines) - index)
            lines = lines[:index]
            break

    kept: list[str] = []
    for line in lines:
        if not line.strip():
            kept.append("")
        elif _PAGE_NUMBER.match(line):
            count("page number")
        elif _is_code(line):
            count("code line")
        elif _is_formula(line):
            count("formula line")
        elif _is_fragment(line):
            count("fragment")
        else:
            cleaned, citations = _CITATION.subn("", line)
            if citations:
                count("citation marker", citations)
            kept.append(cleaned)

    kept = _drop_label_runs(kept, removed)
    return CleanResult(
        text="\n\n".join(_paragraphs(kept, vocabulary)).strip() + "\n",
        removed=removed,
    )
