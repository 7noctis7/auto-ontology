# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One ontology per project: read, write and merge extraction results.

A project ontology is an ordinary extraction file. Merging is the same
normalization as a single extraction, run over the union, so two documents
that name ``Personnes`` and ``Personne`` end up with one class.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.normalize import (
    multi_parent_summary,
    normalize_ontology,
)


def load_ontology(path: str | Path) -> TextOntology:
    """Read an ontology file written by the extractor (or by hand)."""
    return TextOntology.model_validate_json(Path(path).read_text(encoding="utf-8"))


def dump_ontology(ontology: TextOntology) -> str:
    """The ontology as indented JSON, accents kept readable."""
    return json.dumps(ontology.model_dump(), ensure_ascii=False, indent=2) + "\n"


def save_ontology(ontology: TextOntology, path: str | Path) -> None:
    """Write *ontology* to *path*, creating its parent directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dump_ontology(ontology), encoding="utf-8")


def merge_ontologies(
    ontologies: Iterable[TextOntology],
    known_classes: Sequence[str] = (),
) -> tuple[TextOntology, list[str]]:
    """Merge several ontologies into one, and say what was reconciled.

    Earlier ontologies win ties: the first spelling of a class or an entity,
    the first parent and the first non-empty description are kept. Pass the
    project file first and new extractions after it to keep its vocabulary.
    """
    union = TextOntology()
    for ontology in ontologies:
        union.classes.extend(ontology.classes)
        union.triplets.extend(ontology.triplets)
        union.attributes.extend(ontology.attributes)
    ontology, warnings = normalize_ontology(union, known_classes)
    warnings = list(dict.fromkeys(warnings))
    if (summary := multi_parent_summary(ontology)) is not None:
        warnings.append(summary)
    return ontology, warnings
