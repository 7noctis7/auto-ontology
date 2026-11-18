# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Documents × data: facts as SQL views, joined with spreadsheet tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auto_ontology.text_ontology import studio
from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.bridge import (
    ask_data,
    complete_text,
    fact_frames,
    okey,
    run_bridge_sql,
)
from auto_ontology.text_ontology.mcp_stdio import StudioMcp
from auto_ontology.text_ontology.sample import SAMPLE_TEXT
from auto_ontology.text_ontology.store import ProjectStore
from auto_ontology.text_ontology.tables import TableError, import_tabular

_BUDGETS = (
    "etablissement,budget_2026\n"
    "BIBLIOTHEQUE MUNICIPALE DE LYON,1200000\n"
    "Médiathèque de Villeurbanne,300000\n"
).encode()

_JOIN = (
    "SELECT b.budget_2026, f.object AS directrice, f.document, f.quote "
    "FROM budgets b JOIN onto_facts f ON okey(b.etablissement) = f.subject_key "
    "WHERE f.predicate = 'est_dirigee_par'"
)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    document = tmp_path / "bibliotheque.txt"
    document.write_text(SAMPLE_TEXT, encoding="utf-8")
    home = tmp_path / "home"
    assert studio.main(["import", str(document), "--fake", "--home", str(home)]) == 0
    store = ProjectStore(home)
    import_tabular(store, store.current(), "budgets.csv", _BUDGETS)
    return home


def _project(home: Path) -> tuple[ProjectStore, Any, Path]:
    store = ProjectStore(home)
    project = store.current()
    return store, project, store.project_dir(project.id)


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("ACME S.A.", "acme"),
        ("Acme", "acme"),
        ("  Orbital   Lab SAS ", "orbital lab"),
        ("Bibliothèque municipale de Lyon", "bibliotheque municipale de lyon"),
        ("Société Générale", "societe generale"),
        ("SA", "sa"),  # a name that is only a legal form stays a name
        (None, None),
    ],
)
def test_the_join_key_ignores_case_accents_punctuation_and_legal_form(
    name: str | None, key: str | None
) -> None:
    assert okey(name) == key


def test_facts_become_views_with_their_passage(home: Path) -> None:
    _store, project, _folder = _project(home)

    frames = fact_frames(project)

    facts = frames["onto_facts"]
    row = facts[facts["predicate"] == "est_dirigee_par"].iloc[0]
    assert row["subject_key"] == "bibliotheque municipale de lyon"
    assert row["document"] == "bibliotheque.txt" and row["quote"]
    assert "Camille Martin" in set(frames["onto_entities"]["name"])
    assert set(frames["onto_attributes"]["key"]) >= {"annee", "annee_debut"}


def test_one_query_joins_a_spreadsheet_with_the_documents(home: Path) -> None:
    _store, project, folder = _project(home)

    result = run_bridge_sql(folder, project, _JOIN)

    assert result.columns == ["budget_2026", "directrice", "document", "quote"]
    assert result.rows[0][:3] == [1200000, "Camille Martin", "bibliotheque.txt"]


def test_the_views_work_without_any_table(tmp_path: Path) -> None:
    document = tmp_path / "b.txt"
    document.write_text(SAMPLE_TEXT, encoding="utf-8")
    home = tmp_path / "home"
    studio.main(["import", str(document), "--fake", "--home", str(home)])
    _store, project, folder = _project(home)

    result = run_bridge_sql(folder, project, "SELECT count(*) FROM onto_facts")

    assert result.rows[0][0] == len(project.ontology.triplets)
    with pytest.raises(TableError):
        run_bridge_sql(folder, project, "SELECT * FROM read_csv('/etc/hostname')")


class Scripted:
    """A model that answers from a list, and remembers what it was asked."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.prompts.append((system, user))
        return self.replies.pop(0)


def test_a_question_is_answered_from_the_rows_with_sources(home: Path) -> None:
    _store, project, folder = _project(home)
    llm = Scripted(
        json.dumps({"sql": "DELETE FROM budgets", "explanation": "oops"}),
        f"Voici la requête :\n```sql\n{_JOIN}\n```",
        json.dumps({"answer": "Camille Martin dirige un budget de 1 200 000 €."}),
    )

    answer = ask_data(
        project, folder, "Qui dirige l'établissement au plus gros budget ?", llm
    )

    assert answer.attempts == 2
    assert "lecture seule" in llm.prompts[1][1]  # the error went back to the model
    assert "okey(" in llm.prompts[0][0] and "Table budgets" in llm.prompts[0][1]
    assert answer.answer.startswith("Camille Martin")
    assert answer.citations[0]["document"] == "bibliotheque.txt"
    assert "```sql" in answer.markdown()


def test_no_valid_query_after_the_retry_says_what_to_do(home: Path) -> None:
    _store, project, folder = _project(home)
    llm = Scripted("Je ne sais pas.", json.dumps({"sql": "SELECT * FROM absente"}))

    with pytest.raises(TableError, match="ontology sql"):
        ask_data(project, folder, "Combien ?", llm)


def test_an_unhelpful_answer_falls_back_to_the_row_count(home: Path) -> None:
    _store, project, folder = _project(home)
    llm = Scripted(json.dumps({"sql": "SELECT * FROM budgets"}), "...")

    answer = ask_data(project, folder, "Les budgets ?", llm)

    assert answer.answer == "2 ligne(s) trouvée(s) ; voir le tableau."
    assert answer.citations  # facts about the names in the rows


def test_a_langchain_model_is_called_with_two_messages() -> None:
    class Chat:
        def invoke(self, messages: list[Any]) -> Any:
            self.messages = messages
            return type("Reply", (), {"content": [{"text": "a"}, {"text": "b"}]})()

    chat = Chat()

    assert complete_text(chat, "system", "user") == "ab"
    assert [m.content for m in chat.messages] == ["system", "user"]


def test_cli_ask_data_and_sql_on_views(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        studio.main(["ask", "les budgets", "--data", "--fake", "--home", str(home)])
        == 0
    )
    out = capsys.readouterr().out
    assert "SELECT * FROM budgets LIMIT 20" in out and "1200000" in out

    assert studio.main(["sql", _JOIN, "--home", str(home)]) == 0
    assert "Camille Martin" in capsys.readouterr().out

    assert studio.main(["tables", "--home", str(home)]) == 0
    assert "Vue onto_facts" in capsys.readouterr().out


def test_api_and_mcp_reach_the_views(home: Path) -> None:
    client = TestClient(
        create_app(home=home, fake=True), base_url="http://127.0.0.1:4173"
    )
    body = client.post("/api/v1/ask/data", json={"text": "les budgets"}).json()
    assert body["result"]["rows"] and body["sql"].startswith("SELECT")
    assert client.post("/api/v1/ask/data", json={"text": ""}).status_code == 422
    assert client.post("/api/v1/sql", json={"sql": _JOIN}).json()["rows"]
    views = client.get("/api/v1/tables").json()["views"]
    assert [v["view"] for v in views][0] == "onto_facts"

    server = StudioMcp(ProjectStore(home))
    call = lambda name, **a: json.loads(  # noqa: E731
        server.call(name, a)["content"][0]["text"]
    )
    listed = call("list_tables")
    assert {v["view"] for v in listed["views"]} >= {"onto_facts", "onto_rules"}
    described = call("describe_table", table="onto_facts")
    assert described["columns"][0]["name"] == "subject"
    assert call("run_sql", sql=_JOIN)["rows"][0][1] == "Camille Martin"
