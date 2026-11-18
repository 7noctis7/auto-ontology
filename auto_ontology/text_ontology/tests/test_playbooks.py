# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Playbooks: bundled and personal files, guided extraction, checks."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auto_ontology.text_ontology import pipeline, studio
from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.documents import load_text
from auto_ontology.text_ontology.llm_settings import resolve_llm_config
from auto_ontology.text_ontology.mcp_stdio import StudioMcp
from auto_ontology.text_ontology.models import (
    OntologyAttribute,
    OntologyClass,
    OntologyTriplet,
    TextOntology,
)
from auto_ontology.text_ontology.playbooks import (
    PlaybookError,
    available,
    get,
    parse_amount,
    parse_date,
    run_checks,
)
from auto_ontology.text_ontology.sample import FakeLLM
from auto_ontology.text_ontology.store import ProjectStore
from auto_ontology.text_ontology.studio_models import AttributeProv, SourceRef

_TODAY = date.today()


def test_three_playbooks_come_with_the_studio() -> None:
    found = available()

    assert set(found) == {"audit-contrats", "suivi-financier", "base-connaissances"}
    for playbook in found.values():
        assert playbook.checks and playbook.questions and playbook.origin == "intégré"
        assert playbook.name in playbook.guidance()
    assert "échéance" in found["audit-contrats"].guidance()


def test_a_personal_playbook_adds_or_replaces_and_a_broken_one_is_skipped(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "playbooks"
    folder.mkdir()
    (folder / "rh.yaml").write_text(
        "id: recrutement\nname: Recrutement\nchecks:\n"
        "  - id: c\n    title: Candidat sans poste\n    kind: missing_relation\n"
        "    classes: [Candidat]\n    predicates: [postule_a]\n",
        encoding="utf-8",
    )
    (folder / "contrats.yaml").write_text(
        "id: audit-contrats\nname: Mes contrats\n", encoding="utf-8"
    )
    (folder / "casse.yaml").write_text("id: [pas un id", encoding="utf-8")

    found = available(tmp_path)

    assert found["recrutement"].checks[0].kind == "missing_relation"
    assert found["audit-contrats"].name == "Mes contrats"
    assert found["audit-contrats"].origin.endswith("contrats.yaml")
    with pytest.raises(PlaybookError, match="disponibles"):
        get("inexistant", tmp_path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2027-03-31", date(2027, 3, 31)),
        ("le 31/03/2027", date(2027, 3, 31)),
        ("31.03.2027", date(2027, 3, 31)),
        ("1er avril 2027", date(2027, 4, 1)),
        ("15 Décembre 2026", date(2026, 12, 15)),
        ("3 March 2027", date(2027, 3, 3)),
        ("31/02/2027", None),
        ("2027", None),
        ("bientôt", None),
    ],
)
def test_dates_are_read_in_common_forms(text: str, expected: date | None) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("50 000 €", 50_000),
        ("1,2 M€", 1_200_000),
        ("120k", 120_000),
        ("3 millions d'euros", 3_000_000),
        ("1.200.000", 1_200_000),
        ("1.200,50 €", 1200.5),
        ("12,5 %", 12.5),
        ("aucun", None),
    ],
)
def test_amounts_are_read_with_their_scale(text: str, expected: float | None) -> None:
    assert parse_amount(text) == expected


def _contracts(store: ProjectStore) -> Any:
    """Two contracts: one due soon, large and tacitly renewed; one bare."""
    soon = (_TODAY + timedelta(days=30)).strftime("%d/%m/%Y")
    project = store.create("Contrats")
    project.ontology = TextOntology(
        classes=[
            OntologyClass(name="Contrat"),
            OntologyClass(name="ContratDeService", parent="Contrat"),
            OntologyClass(name="Organisation"),
        ],
        triplets=[
            OntologyTriplet(
                subject="Contrat Orbital",
                subject_type="ContratDeService",
                predicate="a_pour_partie",
                object="Orbital Lab",
                object_type="Organisation",
            ),
            OntologyTriplet(
                subject="Contrat Beta",
                subject_type="Contrat",
                predicate="porte_sur",
                object="Maintenance",
                object_type="Organisation",
            ),
        ],
        attributes=[
            OntologyAttribute(
                entity="Contrat Orbital", key="date_echeance", value=soon
            ),
            OntologyAttribute(
                entity="Contrat Orbital", key="montant", value="150 000 €"
            ),
            OntologyAttribute(
                entity="Contrat Orbital", key="renouvellement_tacite", value="oui"
            ),
        ],
    )
    project.attributes = [
        AttributeProv(
            entity="Contrat Orbital",
            key="date_echeance",
            value=soon,
            sources=[
                SourceRef(
                    document_id="d1",
                    filename="orbital.pdf",
                    chunk_index=1,
                    quote=f"Le contrat prend fin le {soon}.",
                )
            ],
        )
    ]
    store.save(project)
    return store.load(project.id)


def test_contract_checks_find_what_needs_a_decision(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = _contracts(store)

    report = run_checks(
        project, get("audit-contrats"), store.project_dir(project.id), today=_TODAY
    )

    found = {(f.check, f.entity) for f in report.findings}
    assert ("echeance-proche", "Contrat Orbital") in found  # a subclass counts
    assert ("sans-echeance", "Contrat Beta") in found
    assert ("sans-partie", "Contrat Beta") in found
    assert ("sans-partie", "Contrat Orbital") not in found
    assert ("renouvellement-tacite", "Contrat Orbital") in found
    assert ("gros-montant", "Contrat Orbital") in found
    soon = next(f for f in report.findings if f.check == "echeance-proche")
    assert "dans 30 jour(s)" in soon.detail and soon.document == "orbital.pdf"
    assert report.findings[0].severity == "haute"  # sorted by priority
    assert report.errors == []
    assert "## Priorité haute" in report.markdown()


def test_a_broken_sql_check_is_reported_not_fatal(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = _contracts(store)
    playbook = get("audit-contrats").model_copy(deep=True)
    playbook.checks[0].kind = "sql"
    playbook.checks[0].sql = "SELECT * FROM absente"

    report = run_checks(project, playbook, store.project_dir(project.id), today=_TODAY)

    assert report.errors and "Échéance dans les 90 jours" in report.errors[0]
    assert report.findings  # the other checks still ran


def test_the_playbook_guides_the_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Contrats")
    project.playbook = "audit-contrats"
    store.save(project)
    seen: dict[str, Any] = {}
    real = pipeline.extract_text_ontology

    def spy(text: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(text, **kwargs)

    monkeypatch.setattr(pipeline, "extract_text_ontology", spy)

    pipeline.ingest_document(
        store,
        store.load(project.id),
        load_text("c.txt", "ACME signe avec Orbital Lab."),
        config=resolve_llm_config(store),
        llm=FakeLLM(),
        model_label="démonstration",
        force=False,
        cancel_event=None,
        on_event=lambda _e: None,
    )

    assert "Contexte du projet : Audit de contrats." in seen["preface"]
    assert "Contrat" in seen["known_classes"]
    assert "a_pour_partie" in seen["known_predicates"]


def test_cli_playbook_and_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = ProjectStore(tmp_path)
    _contracts(store)
    home = str(tmp_path)

    assert studio.main(["check", "--home", home]) == 2  # no playbook yet
    assert studio.main(["playbook", "--home", home]) == 0
    assert "audit-contrats" in capsys.readouterr().out
    assert studio.main(["playbook", "use", "audit-contrats", "--home", home]) == 0
    assert "suit maintenant « Audit de contrats »" in capsys.readouterr().out
    assert studio.main(["playbook", "use", "absent", "--home", home]) == 2
    assert studio.main(["playbook", "show", "--home", home]) == 0
    assert "Contrôles :" in capsys.readouterr().out

    assert studio.main(["check", "--home", home]) == 1  # a high finding
    assert "Échéance dans les 90 jours" in capsys.readouterr().out
    assert studio.main(["check", "--json", "--home", home]) == 1
    assert json.loads(capsys.readouterr().out)["counts"]["haute"] >= 2

    assert studio.main(["brief", "--home", home]) == 0
    assert "Playbook « Audit de contrats » :" in capsys.readouterr().out

    assert studio.main(["playbook", "none", "--home", home]) == 0
    assert store.current().playbook == ""


def test_api_and_mcp_playbooks(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = _contracts(store)
    settings = store.settings()
    settings.last_project_id = project.id
    store.save_settings(settings)
    client = TestClient(create_app(home=tmp_path), base_url="http://127.0.0.1:4173")

    listed = client.get("/api/v1/playbooks").json()
    assert listed["active"] == "" and len(listed["playbooks"]) == 3
    assert client.get("/api/v1/check").status_code == 409
    view = client.put("/api/v1/playbook", json={"id": "audit-contrats"}).json()
    assert view["playbook"] == "audit-contrats"
    assert client.put("/api/v1/playbook", json={"id": "absent"}).status_code == 404
    report = client.get("/api/v1/check").json()
    assert report["counts"]["haute"] >= 2 and report["markdown"].startswith(
        "# Contrôles"
    )
    other = client.get("/api/v1/check", params={"playbook": "base-connaissances"})
    assert other.json()["playbook"] == "Base de connaissances projet"

    result = StudioMcp(store).call("check_playbook", {})
    assert not result["isError"]
    assert "Contrat Beta" in result["content"][0]["text"]
