# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the deterministic modeling rules applied to an LLM extraction."""

from __future__ import annotations

from typing import Any

import pytest

from auto_ontology.text_ontology.models import (
    OntologyAttribute,
    OntologyClass,
    TextOntology,
)
from auto_ontology.text_ontology.normalize import (
    normalize_ontology,
    normalize_predicate,
    to_pascal_case,
    to_snake_case,
)


def _triplet(
    subject: str,
    subject_type: str,
    predicate: str,
    obj: str,
    object_type: str,
) -> dict[str, str]:
    return {
        "subject": subject,
        "subject_type": subject_type,
        "predicate": predicate,
        "object": obj,
        "object_type": object_type,
    }


def _normalize(
    payload: dict[str, Any], **kwargs: Any
) -> tuple[TextOntology, list[str]]:
    return normalize_ontology(TextOntology.model_validate(payload), **kwargs)


def _classes(ontology: TextOntology) -> dict[str, OntologyClass]:
    return {c.name: c for c in ontology.classes}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("document technique", "DocumentTechnique"),
        ("ProjetIA", "ProjetIA"),
        ("Serveur GPU", "ServeurGPU"),
        ("DOCUMENT_TECHNIQUE", "DocumentTechnique"),
        ("société", "Societe"),
        ("matériel-informatique", "MaterielInformatique"),
        ("  ", ""),
    ],
)
def test_to_pascal_case(raw: str, expected: str) -> None:
    assert to_pascal_case(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("est dirigé par", "est_dirige_par"),
        ("estDirigePar", "est_dirige_par"),
        ("appartient à", "appartient_a"),
        ("dependDe", "depend_de"),
        ("Date de création", "date_de_creation"),
        ("SIRET", "siret"),
        ("ServeurGPU", "serveur_gpu"),
        ("nombre__de  GPUs", "nombre_de_gpus"),
    ],
)
def test_to_snake_case(raw: str, expected: str) -> None:
    assert to_snake_case(raw) == expected


@pytest.mark.parametrize("raw", ["est_un", "est une", "is_a", "subClassOf", "estUn"])
def test_every_subclass_spelling_is_est_un(raw: str) -> None:
    assert normalize_predicate(raw) == "est_un"


def test_plural_class_merges_into_its_singular() -> None:
    ontology, warnings = _normalize(
        {
            "classes": [
                {"name": "Personnes", "parent": None, "description": "Des gens"},
                {"name": "Personne", "parent": None, "description": "Un humain"},
                {"name": "DocumentsTechniques", "parent": None, "description": ""},
                {"name": "Document technique", "parent": None, "description": "Doc"},
            ]
        }
    )

    classes = _classes(ontology)
    assert list(classes) == ["Personne", "DocumentTechnique"]
    # First non-empty description wins, whichever spelling carried it.
    assert classes["Personne"].description == "Des gens"
    assert classes["DocumentTechnique"].description == "Doc"
    assert "Class 'Personnes' merged into Personne." in warnings


def test_plural_is_kept_when_no_singular_exists() -> None:
    # "Processus" is singular; with no "Processu" there is nothing to merge into.
    ontology, warnings = _normalize(
        {"classes": [{"name": "Processus", "parent": None, "description": ""}]}
    )

    assert [c.name for c in ontology.classes] == ["Processus"]
    assert warnings == []


def test_known_class_is_reused_and_not_emitted_unless_used() -> None:
    ontology, _ = _normalize(
        {
            "classes": [{"name": "Personnes", "parent": None, "description": "Gens"}],
        },
        known_classes=["Personne", "Organisation"],
    )

    assert [c.name for c in ontology.classes] == ["Personne"]


def test_prompt_placeholder_parent_reads_as_null() -> None:
    ontology, _ = _normalize(
        {
            "classes": [
                {"name": "Personne", "parent": "ClasseParenteOuNull", "description": ""}
            ]
        }
    )

    assert ontology.classes[0].parent is None


def test_undeclared_parent_and_types_are_declared() -> None:
    ontology, warnings = _normalize(
        {
            "classes": [
                {"name": "Entreprise", "parent": "Organisation", "description": "x"}
            ],
            "triplets": [
                _triplet("Alice", "Personne", "travaille pour", "ACME", "Entreprise")
            ],
        }
    )

    classes = _classes(ontology)
    assert set(classes) == {"Entreprise", "Organisation", "Personne"}
    assert classes["Organisation"].parent is None
    assert any("Organisation" in w and "not declared" in w for w in warnings)


def test_est_un_between_classes_sets_the_parent() -> None:
    ontology, _ = _normalize(
        {
            "classes": [
                {"name": "ServeurGPU", "parent": None, "description": ""},
                {"name": "MaterielInformatique", "parent": None, "description": ""},
            ],
            "triplets": [
                _triplet(
                    "Serveur GPU",
                    "ServeurGPU",
                    "is a",
                    "MatérielInformatique",
                    "MaterielInformatique",
                )
            ],
        }
    )

    assert _classes(ontology)["ServeurGPU"].parent == "MaterielInformatique"
    triplet = ontology.triplets[0]
    assert (triplet.subject, triplet.predicate, triplet.object) == (
        "ServeurGPU",
        "est_un",
        "MaterielInformatique",
    )


def test_est_un_does_not_override_a_declared_parent() -> None:
    ontology, warnings = _normalize(
        {
            "classes": [
                {"name": "ServeurGPU", "parent": "Serveur", "description": ""},
                {"name": "Serveur", "parent": None, "description": ""},
                {"name": "MaterielInformatique", "parent": None, "description": ""},
            ],
            "triplets": [
                _triplet(
                    "ServeurGPU",
                    "ServeurGPU",
                    "est_un",
                    "MaterielInformatique",
                    "MaterielInformatique",
                )
            ],
        }
    )

    assert _classes(ontology)["ServeurGPU"].parent == "Serveur"
    # The second parent survives as the triplet itself.
    assert ontology.triplets[0].predicate == "est_un"
    assert any("kept Serveur" in w for w in warnings)


def test_hierarchy_cycles_and_self_parents_are_broken() -> None:
    ontology, warnings = _normalize(
        {
            "classes": [
                {"name": "A", "parent": "B", "description": ""},
                {"name": "B", "parent": "C", "description": ""},
                {"name": "C", "parent": "A", "description": ""},
                {"name": "D", "parent": "D", "description": ""},
            ]
        }
    )

    parents = {c.name: c.parent for c in ontology.classes}
    assert parents == {"A": "B", "B": "C", "C": None, "D": None}
    assert len(warnings) == 2


def test_entity_spellings_and_duplicate_triplets_collapse() -> None:
    ontology, _ = _normalize(
        {
            "triplets": [
                _triplet(
                    "NVIDIA", "Entreprise", "estDirigéPar", "Jensen  Huang", "Personne"
                ),
                _triplet(
                    "Nvidia", "Entreprise", "est_dirige_par", "Jensen Huang", "Personne"
                ),
            ]
        }
    )

    assert len(ontology.triplets) == 1
    triplet = ontology.triplets[0]
    assert (triplet.subject, triplet.predicate, triplet.object) == (
        "NVIDIA",
        "est_dirige_par",
        "Jensen Huang",
    )


def test_individual_gets_its_most_specific_type() -> None:
    ontology, _ = _normalize(
        {
            "classes": [
                {"name": "Organisation", "parent": None, "description": ""},
                {"name": "Entreprise", "parent": "Organisation", "description": ""},
            ],
            "triplets": [
                _triplet("NVIDIA", "Organisation", "emploie", "Alice", "Personne"),
                _triplet("NVIDIA", "Entreprise", "situe_a", "Santa Clara", "Ville"),
            ],
        }
    )

    assert {t.subject_type for t in ontology.triplets} == {"Entreprise"}


def test_unrelated_types_are_left_alone() -> None:
    ontology, _ = _normalize(
        {
            "triplets": [
                _triplet("Alice", "Auteur", "ecrit", "Rapport", "Document"),
                _triplet("Alice", "Employe", "travaille_pour", "ACME", "Entreprise"),
            ]
        }
    )

    assert [t.subject_type for t in ontology.triplets] == ["Auteur", "Employe"]


def test_attributes_are_snake_case_deduplicated_and_never_empty() -> None:
    ontology, warnings = _normalize(
        {
            "attributes": [
                {"entity": "NVIDIA", "key": "Année de fondation", "value": 1993},
                {"entity": "nvidia", "key": "annee_de_fondation", "value": "1993"},
                {"entity": "NVIDIA", "key": "cotee", "value": True},
                {"entity": "NVIDIA", "key": "siege", "value": "  "},
            ]
        }
    )

    assert ontology.attributes == [
        OntologyAttribute(entity="NVIDIA", key="annee_de_fondation", value="1993"),
        OntologyAttribute(entity="NVIDIA", key="cotee", value="true"),
    ]
    assert len(warnings) == 1


def test_incomplete_triplets_are_dropped() -> None:
    ontology, warnings = _normalize(
        {"triplets": [_triplet("Alice", "Personne", " ", "ACME", "Entreprise")]}
    )

    assert ontology.triplets == []
    assert len(warnings) == 1


def test_normalization_does_not_mutate_its_input() -> None:
    raw = TextOntology.model_validate(
        {
            "classes": [{"name": "Personnes", "parent": None, "description": ""}],
            "triplets": [_triplet("a", "x", "is a", "b", "y")],
        }
    )
    before = raw.model_dump()

    normalize_ontology(raw)

    assert raw.model_dump() == before
