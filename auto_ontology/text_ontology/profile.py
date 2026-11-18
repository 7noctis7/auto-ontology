# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Guess what kind of document was dropped, without calling a model.

The cues are ordinary words (a contract says « les parties », a paper says
« abstract »). Confidence is how many independent cues matched, capped so a
short note is never shown as certain. The person can replace the guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GENRES: tuple[str, ...] = (
    "contract",
    "scientific_paper",
    "report",
    "book_chapter",
    "financial_statement",
    "email",
    "notes",
    "other",
)

GENRE_LABELS_FR: dict[str, str] = {
    "contract": "Contrat",
    "scientific_paper": "Article scientifique",
    "report": "Rapport",
    "book_chapter": "Chapitre",
    "financial_statement": "État financier",
    "email": "Courriel",
    "notes": "Notes",
    "other": "Autre",
}

_CUES: dict[str, tuple[str, ...]] = {
    "contract": (
        "les parties",
        "contrat",
        "clause",
        "article 1",
        "hereinafter",
        "this agreement",
        "entre les soussign",
    ),
    "scientific_paper": (
        "abstract",
        "résumé",
        "doi:",
        "doi ",
        "et al",
        "keywords",
        "mots-clés",
        "méthodologie",
    ),
    "financial_statement": (
        "bilan",
        "chiffre d'affaires",
        "compte de résultat",
        "actif",
        "passif",
        "income statement",
        "balance sheet",
    ),
    "email": (
        "objet :",
        "objet:",
        "subject:",
        "de :",
        "from:",
        "cordialement",
        "sent:",
    ),
    "report": (
        "rapport",
        "recommandation",
        "executive summary",
        "synthèse",
        "conclusions",
    ),
    "book_chapter": ("chapitre ", "chapter ", "chapitre\n"),
    "notes": ("pense-bête", "mémo", "todo", "à retenir", "notes —"),
}

_DOMAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("droit", ("contrat", "clause", "juridique", "tribunal", "agreement")),
    ("finance", ("bilan", "actif", "chiffre d'affaires", "budget", "invoice")),
    ("science", ("hypothèse", "expérience", "abstract", "doi", "méthod")),
    ("culture", ("bibliothèque", "livre", "chapitre", "auteur", "édition")),
    ("santé", ("patient", "diagnostic", "clinique", "traitement")),
    ("technique", ("serveur", "logiciel", "api", "algorithme", "système")),
)

_FR = frozenset(
    "le la les des une un est dans pour qui par avec sur son ses au aux".split()
)
_EN = frozenset("the and of to in for with that this from are was were".split())
_AUTHOR = re.compile(r"(?im)^(?:auteur|author|par|by|de|from)\s*[:\-]\s*(.{3,80})$")
_SUBJECT = re.compile(r"(?im)^(?:objet|subject)\s*:\s*(.{2,110})\s*$")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_NAMED = re.compile(
    r"\b(\d{1,2})\s+(janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|"
    r"septembre|octobre|novembre|décembre|decembre|january|february|march|april|"
    r"may|june|july|august|september|october|november|december)\s+(\d{4})\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_MONTHS = {
    "janvier": 1,
    "january": 1,
    "février": 2,
    "fevrier": 2,
    "february": 2,
    "mars": 3,
    "march": 3,
    "avril": 4,
    "april": 4,
    "mai": 5,
    "may": 5,
    "juin": 6,
    "june": 6,
    "juillet": 7,
    "july": 7,
    "août": 8,
    "aout": 8,
    "august": 8,
    "septembre": 9,
    "september": 9,
    "octobre": 10,
    "october": 10,
    "novembre": 11,
    "november": 11,
    "décembre": 12,
    "decembre": 12,
    "december": 12,
}


@dataclass(frozen=True)
class DocumentProfile:
    """What the file appears to be, plus the fields a person expects to see."""

    genre: str
    genre_confidence: float
    domain: str
    domain_confidence: float
    title: str
    author: str
    date: str
    language: str
    pages: int


def profile_text(text: str, *, filename: str = "", pages: int = 0) -> DocumentProfile:
    """Classify *text*. Empty text is notes, with a low confidence."""
    folded = text.casefold()
    genre, genre_confidence = _genre(folded, text)
    domain, domain_confidence = _domain(folded)
    return DocumentProfile(
        genre=genre,
        genre_confidence=genre_confidence,
        domain=domain,
        domain_confidence=domain_confidence,
        title=_title(text, filename),
        author=_author(text),
        date=_date(text),
        language=_language(text),
        pages=pages or (max(1, len(text) // 1800) if text.strip() else 0),
    )


def _genre(folded: str, text: str) -> tuple[str, float]:
    scores = {
        genre: sum(1 for cue in cues if cue in folded) for genre, cues in _CUES.items()
    }
    best = max(scores, key=lambda genre: scores[genre])
    hits = scores[best]
    if hits <= 0:
        if len(text) < 2500:
            return "notes", 0.5
        return "other", 0.34
    return best, round(min(0.92, 0.42 + 0.16 * hits), 2)


def _domain(folded: str) -> tuple[str, float]:
    best, hits = "", 0
    for name, cues in _DOMAINS:
        found = sum(1 for cue in cues if cue in folded)
        if found > hits:
            best, hits = name, found
    if hits <= 0:
        return "", 0.0
    return best, round(min(0.9, 0.4 + 0.2 * hits), 2)


def _title(text: str, filename: str) -> str:
    subject = _SUBJECT.search(text[:2500])
    if subject:
        return subject.group(1).strip()[:110]
    for line in text.splitlines():
        cleaned = line.strip().strip("#").strip()
        if not cleaned:
            continue
        if re.match(r"(?i)^(de|from)\s*:", cleaned):
            continue
        if 8 <= len(cleaned) <= 110 and cleaned.count(" ") <= 16:
            return cleaned
        break
    stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
    return " ".join(stem.split())[:110]


def project_name_from(title: str, filename: str) -> str:
    """A short editable name: the subject or title, not the raw file name."""
    cleaned = title.strip()
    if cleaned and not re.match(r"(?i)^(de|from)\s*:", cleaned):
        return cleaned[:80]
    stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    return " ".join(stem.split())[:80] or "Projet"


def _author(text: str) -> str:
    head = "\n".join(text.splitlines()[:40])
    match = _AUTHOR.search(head)
    if not match:
        return ""
    return match.group(1).strip()[:80]


def _date(text: str) -> str:
    """A full date wins over a bare year. French dates are day, then month."""
    head = text[:8000]
    named = _NAMED.search(head)
    if named:
        month = _MONTHS[named.group(2).casefold()]
        return f"{int(named.group(1)):02d}/{month:02d}/{int(named.group(3)):04d}"
    iso = _ISO.search(head)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    slash = _SLASH.search(head)
    if slash:
        day, month, year = (
            int(slash.group(1)),
            int(slash.group(2)),
            int(slash.group(3)),
        )
        if month > 12 and day <= 12:
            day, month = month, day
        if 1 <= day <= 31 and 1 <= month <= 12:
            return f"{day:02d}/{month:02d}/{year:04d}"
    year = _YEAR.search(head)
    return year.group(1) if year else ""


def _language(text: str) -> str:
    words = re.findall(r"[A-Za-zÀ-ÿ']+", text.casefold())
    if not words:
        return ""
    sample = words[:400]
    french = sum(word in _FR for word in sample)
    english = sum(word in _EN for word in sample)
    accents = sum(ch in "éèêëàâùûôîïç" for ch in text.casefold())
    if french >= 2 and french >= english:
        return "fr"
    if accents >= 3 and french >= english:
        return "fr"
    if english >= 2 and english > french:
        return "en"
    return ""
