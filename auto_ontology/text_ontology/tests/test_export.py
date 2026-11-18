# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Mermaid, Turtle, Cypher and HTML exports."""

from __future__ import annotations

import json
import re

import pytest

from auto_ontology.text_ontology.export import (
    ExportFormat,
    export_ontology,
    to_cypher,
    to_html,
    to_mermaid,
    to_turtle,
)
from auto_ontology.text_ontology.models import TextOntology


def _ontology() -> TextOntology:
    return TextOntology.model_validate(
        {
            "classes": [
                {"name": "Organisation", "parent": None, "description": ""},
                {
                    "name": "Entreprise",
                    "parent": "Organisation",
                    "description": 'Société "privée"',
                },
                {"name": "Personne", "parent": None, "description": "Individu"},
                {"name": "Produit", "parent": None, "description": ""},
                {"name": "ServeurGPU", "parent": None, "description": ""},
            ],
            "triplets": [
                {
                    "subject": "NVIDIA",
                    "subject_type": "Entreprise",
                    "predicate": "est_dirige_par",
                    "object": "Jensen Huang",
                    "object_type": "Personne",
                },
                {
                    "subject": "ServeurGPU",
                    "subject_type": "ServeurGPU",
                    "predicate": "est_un",
                    "object": "Produit",
                    "object_type": "Produit",
                },
                {
                    "subject": "DGX",
                    "subject_type": "ServeurGPU",
                    "predicate": "est_un",
                    "object": "Produit",
                    "object_type": "Produit",
                },
            ],
            "attributes": [
                {"entity": "NVIDIA", "key": "annee_fondation", "value": "1993"},
                {"entity": "NVIDIA", "key": "code", "value": "007"},
                {"entity": "NVIDIA", "key": "devise", "value": 'Dire "oui"'},
            ],
        }
    )


def test_mermaid_draws_classes_individuals_and_both_link_kinds() -> None:
    mermaid = to_mermaid(_ontology())

    assert mermaid.startswith("flowchart LR\n")
    assert '{{"Entreprise"}}' in mermaid
    assert "NVIDIA<br/><i>Entreprise</i>" in mermaid
    assert "devise: Dire #quot;oui#quot;" in mermaid
    assert re.search(r'e\d+ -->\|"est_dirige_par"\| e\d+', mermaid)
    # Entreprise est_un Organisation, ServeurGPU est_un Produit, DGX est_un Produit
    assert len(re.findall(r"-\.->\|est_un\|", mermaid)) == 3


def test_turtle_states_classes_hierarchy_individuals_and_typed_literals() -> None:
    turtle = to_turtle(_ontology(), base_iri="http://example.org/test#")

    assert "@prefix : <http://example.org/test#> ." in turtle
    assert ":Entreprise a owl:Class" in turtle
    assert "rdfs:subClassOf :Organisation" in turtle
    assert "rdfs:subClassOf :Produit" in turtle
    assert ":estDirigePar a owl:ObjectProperty" in turtle
    assert 'rdfs:label "est_dirige_par"' in turtle
    assert "rdfs:domain :Entreprise" in turtle
    assert "rdfs:range :Personne" in turtle
    assert ":anneeFondation a owl:DatatypeProperty" in turtle
    assert ":NVIDIA a owl:NamedIndividual , :Entreprise" in turtle
    assert ":estDirigePar :JensenHuang" in turtle
    assert ':anneeFondation "1993"^^xsd:integer' in turtle
    # A leading zero means an identifier: it stays a string.
    assert ':code "007" ;' in turtle
    assert r'rdfs:comment "Société \"privée\""' in turtle
    assert ":DGX a owl:NamedIndividual , :ServeurGPU , :Produit" in turtle


def test_turtle_rejects_a_base_iri_that_would_break_the_document() -> None:
    with pytest.raises(ValueError):
        to_turtle(_ontology(), base_iri="http://example.org/> .")


def test_turtle_local_names_are_unique_per_name() -> None:
    ontology = TextOntology.model_validate(
        {
            "triplets": [
                {
                    "subject": "C++",
                    "subject_type": "Langage",
                    "predicate": "inspire",
                    "object": "C",
                    "object_type": "Langage",
                }
            ]
        }
    )

    turtle = to_turtle(ontology)

    assert ":C a owl:NamedIndividual" in turtle
    assert ":C2 a owl:NamedIndividual" in turtle


def test_cypher_is_idempotent_and_escaped() -> None:
    cypher = to_cypher(_ontology())

    assert "CREATE CONSTRAINT classe_name IF NOT EXISTS" in cypher
    assert "CREATE (" not in cypher  # MERGE only: replaying changes nothing
    assert (
        'MERGE (c:Classe {name: "Entreprise"}) SET c.description = "Société \\"privée\\"";'
        in cypher
    )
    assert (
        'MATCH (c:Classe {name: "Entreprise"}), (p:Classe {name: "Organisation"}) '
        "MERGE (c)-[:EST_UN]->(p);"
    ) in cypher
    assert 'e:`Entreprise`, e.`annee_fondation` = 1993, e.`code` = "007"' in cypher
    assert "MERGE (a)-[:`EST_DIRIGE_PAR`]->(b);" in cypher
    assert 'MERGE (e:Entite {name: "DGX"}) SET e:`ServeurGPU`, e:`Produit`;' in cypher


def test_html_embeds_the_graph_without_letting_names_inject_markup() -> None:
    ontology = TextOntology.model_validate(
        {
            "triplets": [
                {
                    "subject": "</script><script>alert(1)</script>",
                    "subject_type": "Chose",
                    "predicate": "lie_a",
                    "object": "B & C",
                    "object_type": "Chose",
                }
            ]
        }
    )

    page = to_html(ontology, title="<Projet>")

    assert "<title>&lt;Projet&gt;</title>" in page
    assert "<script>alert(1)" not in page
    payload = re.search(
        r'<script type="application/json" id="ontology-data">(.*?)</script>', page
    )
    assert payload is not None
    data = json.loads(payload.group(1))
    labels = {n["label"] for n in data["nodes"]}
    assert "</script><script>alert(1)</script>" in labels
    assert {"kind": "relation", "label": "lie_a"}.items() <= data["edges"][-1].items()


def test_html_title_that_looks_like_a_placeholder_stays_a_title() -> None:
    page = to_html(TextOntology(), title="__DATA__")

    assert "<title>__DATA__</title>" in page


@pytest.mark.parametrize("export_format", list(ExportFormat))
def test_every_format_renders_an_empty_ontology(export_format: ExportFormat) -> None:
    assert export_ontology(TextOntology(), export_format)


def test_a_hand_edited_file_is_normalized_before_export() -> None:
    ontology = TextOntology.model_validate(
        {
            "triplets": [
                {
                    "subject": "Alice",
                    "subject_type": "personnes",
                    "predicate": "travaille pour",
                    "object": "ACME",
                    "object_type": "Entreprise",
                }
            ]
        }
    )

    turtle = to_turtle(ontology)

    assert ":Personnes a owl:Class" in turtle
    assert ":travaillePour a owl:ObjectProperty" in turtle


def test_html_lists_every_parent_and_every_type() -> None:
    ontology = TextOntology.model_validate(
        {
            "classes": [
                {"name": "Chaine", "parent": None, "description": ""},
                {"name": "Block", "parent": None, "description": ""},
                {"name": "ProofOfWorkChain", "parent": "Block", "description": ""},
                {"name": "ProofOfWorkChain", "parent": "Chaine", "description": ""},
            ],
            "triplets": [
                {
                    "subject": "Chaîne principale",
                    "subject_type": "ProofOfWorkChain",
                    "predicate": "est_un",
                    "object": "Chaine",
                    "object_type": "Chaine",
                }
            ],
        }
    )

    page = to_html(ontology)
    payload = re.search(
        r'<script type="application/json" id="ontology-data">(.*?)</script>', page
    )
    assert payload is not None
    data = json.loads(payload.group(1))
    by_label = {n["label"]: n for n in data["nodes"]}

    assert by_label["ProofOfWorkChain"]["parents"] == ["Block", "Chaine"]
    assert by_label["Chaîne principale"]["types"] == ["ProofOfWorkChain", "Chaine"]
    kinds = [e["kind"] for e in data["edges"]]
    assert kinds.count("est_un") == 2 and kinds.count("type") == 2
    # The legend sits outside the graph container, which the library empties.
    assert page.index('<div id="graph"></div>') < page.index('class="legend"')
