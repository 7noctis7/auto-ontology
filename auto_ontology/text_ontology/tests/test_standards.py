# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OWL export, SHACL notes, alignments and competency questions."""

from __future__ import annotations

from rdflib import Graph

from auto_ontology.text_ontology.export import to_turtle
from auto_ontology.text_ontology.models import (
    OntologyClass,
    OntologyTriplet,
    TextOntology,
)
from auto_ontology.text_ontology.profile import profile_text
from auto_ontology.text_ontology.sample import FakeLLM, sample_ontology
from auto_ontology.text_ontology.similar import merge_candidates
from auto_ontology.text_ontology.standards import (
    alignment_suggestions,
    competency_rows,
    local_name,
    shacl_checks,
)
from auto_ontology.text_ontology.studio_export import _turtle, to_jsonld
from auto_ontology.text_ontology.studio_models import (
    CompetencyQuestion,
    DocumentRecord,
    Project,
    SourceRef,
    TripletProv,
)


def _project() -> Project:
    ontology = sample_ontology()
    return Project(
        id="p",
        name="Exemple",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        ontology=ontology,
        questions=[CompetencyQuestion(id="q1", text="Qui dirige la bibliothèque ?")],
    )


def test_local_names_drop_underscores_and_keep_case() -> None:
    assert local_name("est_dirige_par", "property") == "estDirigePar"
    assert (
        local_name("Bibliothèque municipale", "individual") == "BibliothequeMunicipale"
    )
    assert "_" not in local_name("annee_fondation", "property")


def test_turtle_round_trip_parses_and_keeps_classes() -> None:
    text = to_turtle(sample_ontology(), title="Exemple")
    graph = Graph()
    graph.parse(data=text, format="turtle")
    again = Graph()
    again.parse(data=graph.serialize(format="turtle"), format="turtle")
    assert len(graph) == len(again)
    turtle = graph.serialize(format="turtle")
    assert "owl:Class" in text
    assert "skos:prefLabel" in text
    assert "owl:ObjectProperty" in text
    assert "estDirigeePar" in text
    assert "Jensen_Huang" not in text
    assert len(turtle) > 100


def test_studio_turtle_records_provenance() -> None:
    project = _project()
    project.documents.append(
        DocumentRecord(
            id="doc1",
            filename="exemple.txt",
            added_at="2026-01-01T00:00:00+00:00",
            model="fake",
            prompt_version="sample",
        )
    )
    project.triplets.append(
        TripletProv(
            subject="Camille Martin",
            predicate="dirige",
            object="Bibliothèque municipale",
            sources=[
                SourceRef(
                    document_id="doc1",
                    filename="exemple.txt",
                    chunk_index=0,
                    quote="Camille Martin dirige la bibliothèque",
                )
            ],
        )
    )
    text = _turtle(project)
    assert "prov:wasDerivedFrom" in text
    assert "prov:wasGeneratedBy" in text
    assert "prov:SoftwareAgent" in text
    assert "sample" in text
    graph = Graph()
    graph.parse(data=text, format="turtle")
    assert len(graph) > 0


def test_jsonld_has_a_context() -> None:
    document = to_jsonld(_project())
    assert '"@context"' in document
    assert '"@graph"' in document
    assert "owl" in document
    graph = Graph()
    graph.parse(data=document, format="json-ld")
    assert len(graph) > 0


def test_instance_is_not_a_merge_candidate_for_its_class() -> None:
    pairs = merge_candidates(_project())
    for pair in pairs:
        assert pair["a"] != "Document"
        assert pair["b"] != "Document"
        assert pair["auto"] is False


def test_shacl_flags_a_missing_definition_and_not_a_mixed_merge() -> None:
    project = _project()
    names = {item.name for item in shacl_checks(project)}
    assert "sous-classe" in names
    assert "definitions" in names
    suggestions = alignment_suggestions(project)
    assert any(item["prefix"] == "foaf:Person" for item in suggestions)
    assert all(item["auto"] is False for item in suggestions)
    rows = competency_rows(project)
    assert rows[0]["answerable"] is True


def test_fake_extracts_distinct_graphs() -> None:
    llm = FakeLLM()
    contract = llm.invoke(_messages("Contrat. Jeanne Martin signe la clause."))
    mail = llm.invoke(_messages("De : ada@example.test\nObjet : vernissage\n"))
    assert contract.triplets != mail.triplets
    assert any(
        item.subject == "Jeanne Martin" or item.object == "Jeanne Martin"
        for item in contract.triplets
    )


def test_french_dates_and_email_subject() -> None:
    profile = profile_text(
        "Signé en 2016.\nLe contrat prend effet le 12/03/2026.\n",
        filename="contrat_pret_bibliotheque.pdf",
    )
    assert profile.date == "12/03/2026"
    named = profile_text("Réunion le 12 mars 2026 à Lyon.\n", filename="note.txt")
    assert named.date == "12/03/2026"
    mail = profile_text(
        "De : ada@example.test\nObjet : Réunion exposition\nCordialement\n",
        filename="courriel_reunion_exposition.txt",
    )
    assert mail.title == "Réunion exposition"


def _messages(text: str) -> list[object]:
    class _Msg:
        content = f"<texte_source>{text}</texte_source>"

    return [_Msg()]


def test_subclass_cycle_is_reported() -> None:
    ontology = TextOntology(
        classes=[
            OntologyClass(name="A", parent="C", description="a"),
            OntologyClass(name="B", parent="A", description="b"),
            OntologyClass(name="C", parent="B", description="c"),
        ],
        triplets=[
            OntologyTriplet(
                subject="A",
                subject_type="A",
                predicate="est_un",
                object="C",
                object_type="C",
            )
        ],
    )
    project = Project(
        id="p",
        name="Cycle",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        ontology=ontology,
    )
    failed = [item.name for item in shacl_checks(project) if item.status == "failed"]
    assert "sous-classe" in failed
