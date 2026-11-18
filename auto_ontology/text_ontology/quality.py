# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Quality expectations checked after a document is merged.

A failed check does not delete what was read. It marks the run incomplete
and leaves a line a person can read. Thresholds have defaults.
"""

from __future__ import annotations

import shutil

from auto_ontology.text_ontology.studio_models import Project, StepNote


def expectation_report(project: Project) -> list[StepNote]:
    """The default checks. ``status`` is ``ok`` or ``failed``."""
    notes: list[StepNote] = []
    failed = sum(len(document.chunks_failed) for document in project.documents)
    total = sum(document.chunks_total for document in project.documents) or 1
    ratio = failed / total
    notes.append(
        StepNote(
            name="chunks",
            status="ok" if ratio <= 0.5 else "failed",
            detail=f"{failed} morceau(x) en échec sur {total}.",
        )
    )
    empty = 0
    sourced = 0
    for item in project.triplets:
        sourced += 1
        if not item.sources or not item.sources[0].quote.strip():
            empty += 1
    notes.append(
        StepNote(
            name="citations",
            status="ok" if empty == 0 else "failed",
            detail=f"{empty} fait(s) sans citation sur {sourced}.",
        )
    )
    cycle = _cycle(project)
    notes.append(
        StepNote(
            name="hierarchie",
            status="failed" if cycle else "ok",
            detail="Cycle est_un." if cycle else "Pas de cycle est_un.",
        )
    )
    return notes


def apply_expectations(project: Project, document_id: str) -> list[StepNote]:
    """Store the report on the document and surface failures as warnings."""
    report = expectation_report(project)
    for document in project.documents:
        if document.id != document_id:
            continue
        document.expectations = report
        failed = [item for item in report if item.status == "failed"]
        if failed:
            if document.status == "ok":
                document.status = "incomplete"
            for item in failed:
                line = f"Attente « {item.name} » : {item.detail}"
                if line not in document.warnings:
                    document.warnings.append(line)
    return report


def ocr_hint() -> str:
    """What to say when a PDF has no text layer. No OCR is run from here."""
    if shutil.which("tesseract"):
        return (
            " Tesseract est présent sur cette machine : vous pouvez relancer "
            "l'import pour tenter un OCR."
        )
    return (
        " OCR indisponible : aucun binaire Tesseract n'est installé, "
        "donc un scan ne peut pas être lu."
    )


def _cycle(project: Project) -> bool:
    parents: dict[str, str] = {}
    for cls in project.ontology.classes:
        if cls.parent:
            parents[cls.name] = cls.parent
    for triplet in project.ontology.triplets:
        if triplet.predicate == "est_un":
            parents.setdefault(triplet.subject, triplet.object)
    for start in list(parents):
        seen: set[str] = set()
        current: str | None = start
        while current and current not in seen:
            seen.add(current)
            current = parents.get(current)
            if current == start:
                return True
    return False
