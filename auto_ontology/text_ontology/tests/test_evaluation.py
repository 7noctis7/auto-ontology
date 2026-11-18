# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for scoring an extraction against a hand-written reference."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from auto_ontology.text_ontology import __main__ as cli
from auto_ontology.text_ontology.evaluation import evaluate, load_corpus
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.project import save_ontology


def _ontology(triplets: list[tuple[str, str, str]], **extra: Any) -> TextOntology:
    return TextOntology.model_validate(
        {
            "triplets": [
                {
                    "subject": s,
                    "subject_type": "Chose",
                    "predicate": p,
                    "object": o,
                    "object_type": "Chose",
                }
                for s, p, o in triplets
            ],
            **extra,
        }
    )


def test_scores_count_found_missing_and_extra_facts() -> None:
    gold = _ontology([("Alice", "dirige", "ACME"), ("ACME", "situee_a", "Lyon")])
    found = _ontology([("alice", "Dirige", "Acme"), ("Bob", "aime", "Lyon")])

    triplets = evaluate(found, gold).scores["triplets"]

    assert (triplets.expected, triplets.found, triplets.matched) == (2, 2, 1)
    assert triplets.precision == triplets.recall == 0.5
    assert triplets.missing == ["ACME situee_a Lyon"]
    assert triplets.extra == ["Bob aime Lyon"]


def test_links_forgive_the_wording_and_the_direction() -> None:
    gold = _ontology([("ACME", "est_dirigee_par", "Alice")])
    found = _ontology([("Alice", "dirige", "ACME")])

    scores = evaluate(found, gold).scores

    assert scores["triplets"].f1 == 0
    assert scores["links"].f1 == 1


def test_classes_compare_after_normalization() -> None:
    gold = TextOntology.model_validate(
        {"classes": [{"name": "ServeurGPU", "parent": "Materiel", "description": ""}]}
    )
    found = TextOntology.model_validate(
        {"classes": [{"name": "serveur GPU", "parent": "matériel", "description": "x"}]}
    )

    scores = evaluate(found, gold).scores

    assert scores["classes"].f1 == 1
    assert scores["hierarchy"].f1 == 1


def test_attributes_match_on_entity_and_value() -> None:
    gold = _ontology(
        [], attributes=[{"entity": "ACME", "key": "annee_fondation", "value": "1993"}]
    )
    found = _ontology(
        [], attributes=[{"entity": "Acme", "key": "date_creation", "value": 1993}]
    )

    assert evaluate(found, gold).scores["attributes"].f1 == 1


def test_the_bundled_corpus_is_consistent() -> None:
    documents = load_corpus()

    assert {d.name for d in documents} == {
        "mediatheque_fr",
        "startup_fr",
        "payment_network_en",
    }
    for document in documents:
        assert all(
            score.f1 == 1
            for score in evaluate(document.gold, document.gold).scores.values()
        )


def test_cli_eval_compares_two_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    save_ontology(_ontology([("Alice", "dirige", "ACME")]), tmp_path / "found.json")
    save_ontology(
        _ontology([("Alice", "dirige", "ACME"), ("ACME", "situee_a", "Lyon")]),
        tmp_path / "gold.json",
    )

    code = cli.main(
        ["eval", str(tmp_path / "found.json"), str(tmp_path / "gold.json"), "--json"]
    )
    scores = json.loads(capsys.readouterr().out)

    assert code == 0
    assert scores["triplets"]["recall"] == 0.5
    assert scores["triplets"]["missing"] == ["ACME situee_a Lyon"]


def test_cli_eval_runs_the_model_on_the_corpus(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    golds = {d.text.strip()[:40]: d.gold for d in load_corpus()}

    class Perfect:
        """Answers each corpus text with its reference."""

        description = "parfait"
        notes: list[str] = []

        def __call__(self, system: str, user: str) -> TextOntology:
            return next(gold for start, gold in golds.items() if start in user)

    monkeypatch.setattr(cli, "resolve_backend", lambda **_: Perfect())

    code = cli.main(["eval", "--corpus", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["model"] == "parfait"
    assert set(payload["documents"]) == {
        "mediatheque_fr",
        "startup_fr",
        "payment_network_en",
    }
    assert payload["total"]["triplets"]["f1"] == 1.0
