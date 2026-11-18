# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The studio's MCP server: protocol, tools, confirmed writes, reports."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from auto_ontology.text_ontology import mcp_stdio, studio
from auto_ontology.text_ontology.agent_writes import AGENT_FILENAME
from auto_ontology.text_ontology.api import access_allowed
from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.cache import FileChunkCache
from auto_ontology.text_ontology.confirm import ConfirmationError, Confirmations
from auto_ontology.text_ontology.mcp_stdio import StudioMcp
from auto_ontology.text_ontology.models import TextOntology
from auto_ontology.text_ontology.reports import ReportError, comparison, meeting
from auto_ontology.text_ontology.sample import SAMPLE_TEXT
from auto_ontology.text_ontology.store import BUSY_FILE, ProjectStore
from auto_ontology.text_ontology.tables import import_tabular


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """The sample library, imported through the demo model, plus one table."""
    document = tmp_path / "bibliotheque.txt"
    document.write_text(SAMPLE_TEXT, encoding="utf-8")
    home = tmp_path / "home"
    assert studio.main(["import", str(document), "--fake", "--home", str(home)]) == 0
    store = ProjectStore(home)
    import_tabular(
        store, store.current(), "prets.csv", b"lecteur,livres\nAlice,3\nBob,5\n"
    )
    return home


def _rpc(server: StudioMcp, method: str, params: dict[str, Any] | None = None) -> Any:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    return server.handle(message)


def _call(server: StudioMcp, tool: str, /, **arguments: Any) -> dict[str, Any]:
    response = _rpc(server, "tools/call", {"name": tool, "arguments": arguments})
    return response["result"]


def _payload(result: dict[str, Any]) -> Any:
    assert not result["isError"], result["content"][0]["text"]
    return json.loads(result["content"][0]["text"])


# --- Protocol -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("asked", "answered"),
    [
        ("2025-06-18", "2025-06-18"),
        ("2024-11-05", "2024-11-05"),
        ("1999", "2025-06-18"),
    ],
)
def test_initialize_negotiates_the_version(
    home: Path, asked: str, answered: str
) -> None:
    server = StudioMcp(ProjectStore(home))

    result = _rpc(server, "initialize", {"protocolVersion": asked})["result"]

    assert result["protocolVersion"] == answered
    assert result["serverInfo"]["name"] == "auto-ontology-studio"
    assert "confirm_token" in result["instructions"]


def test_notifications_get_no_answer_and_bad_requests_get_errors(home: Path) -> None:
    server = StudioMcp(ProjectStore(home))

    assert (
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    )
    assert server.handle([1, 2])["error"]["code"] == -32600  # type: ignore[index]
    assert _rpc(server, "resources/list")["error"]["code"] == -32601
    unknown = _rpc(server, "tools/call", {"name": "drop_everything"})
    assert unknown["error"]["code"] == -32602


def test_read_only_by_default_with_annotations(home: Path) -> None:
    tools = _rpc(StudioMcp(ProjectStore(home)), "tools/list")["result"]["tools"]
    names = {tool["name"] for tool in tools}

    assert {"search", "get_concept", "run_sql", "brief", "export_report"} <= names
    assert not names & {"remember_fact", "certify_rule"}
    assert not names & {"neighbours", "ask"}  # older names: answered, not listed
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)


def test_writes_are_listed_only_when_allowed(home: Path) -> None:
    tools = _rpc(StudioMcp(ProjectStore(home), allow_writes=True), "tools/list")
    writes = {
        t["name"]: t["annotations"]["readOnlyHint"] for t in tools["result"]["tools"]
    }

    assert writes["remember_fact"] is False and writes["certify_rule"] is False
    refused = _rpc(
        StudioMcp(ProjectStore(home)), "tools/call", {"name": "certify_rule"}
    )
    assert refused["error"]["code"] == -32602


def test_structured_content_follows_the_negotiated_version(home: Path) -> None:
    server = StudioMcp(ProjectStore(home))
    _rpc(server, "initialize", {"protocolVersion": "2024-11-05"})
    assert "structuredContent" not in _call(server, "list_tables")

    _rpc(server, "initialize", {"protocolVersion": "2025-06-18"})
    result = _call(server, "list_tables")
    assert result["structuredContent"]["tables"][0]["table"] == "prets"


# --- Read tools -----------------------------------------------------------------


def test_read_tools_answer_from_the_current_project(home: Path) -> None:
    server = StudioMcp(ProjectStore(home))

    concept = _payload(_call(server, "get_concept", name="camille martin"))
    assert concept["found"] and concept["name"] == "Camille Martin"
    assert {"key": "annee_debut", "value": "2016"} in concept["attributes"]
    assert concept["documents"] == ["bibliotheque.txt"]
    assert _payload(_call(server, "neighbours", name="Lyon"))["found"]  # old name

    facts = _payload(_call(server, "facts", name="Lyon"))
    assert facts["total"] == len(facts["facts"]) >= 2
    assert _payload(_call(server, "search", query="Lovelace"))["entities"]
    assert "Camille" in _call(server, "ask", question="Camille")["content"][0]["text"]
    assert _payload(_call(server, "brief", since="1h"))["markdown"].startswith(
        "# Brief"
    )

    columns = _payload(_call(server, "describe_table", table="prets"))["columns"]
    assert [c["name"] for c in columns] == ["lecteur", "livres"]
    rows = _payload(_call(server, "run_sql", sql="SELECT sum(livres) AS n FROM prets"))
    assert rows["rows"] == [[8]]


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("run_sql", {"sql": "DELETE FROM prets"}, "lecture seule"),
        ("describe_table", {"table": "absente"}, "Table inconnue"),
        ("brief", {"since": "un jour"}, "24h"),
        ("search", {}, "Indiquez query"),
        ("export_report", {"kind": "comparison", "names": ["Lyon"]}, "deux noms"),
    ],
)
def test_refusals_are_tool_errors_with_a_reason(
    home: Path, name: str, arguments: dict[str, Any], message: str
) -> None:
    result = _call(StudioMcp(ProjectStore(home)), name, **arguments)

    assert result["isError"] and message in result["content"][0]["text"]


def test_an_empty_home_says_how_to_start(tmp_path: Path) -> None:
    result = _call(StudioMcp(ProjectStore(tmp_path)), "list_tables")

    assert result["isError"] and "ontology open" in result["content"][0]["text"]


# --- Confirmed writes ---------------------------------------------------------------


def _writer(home: Path) -> tuple[StudioMcp, ProjectStore]:
    store = ProjectStore(home)
    return StudioMcp(store, allow_writes=True), store


_FACT = {
    "subject": "Camille Martin",
    "predicate": "anime",
    "object": "Club de lecture",
    "object_type": "Organisation",
    "source": "Réunion d'équipe du 17 novembre",
}


def test_a_fact_is_previewed_then_written_once_and_undoable(home: Path) -> None:
    server, store = _writer(home)
    project_id = store.current().id
    revision = store.revision(project_id)

    preview = _payload(_call(server, "remember_fact", **_FACT))
    assert preview["applied"] is False and preview["confirm_token"]
    assert "Camille Martin anime Club de lecture" in preview["summary"]
    assert store.revision(project_id) == revision  # nothing written

    done = _payload(
        _call(server, "remember_fact", **_FACT, confirm_token=preview["confirm_token"])
    )
    assert done["applied"] is True
    project = store.current()
    fact = next(t for t in project.triplets if t.object == "Club de lecture")
    assert fact.sources[0].filename == AGENT_FILENAME
    assert fact.sources[0].quote == _FACT["source"]
    assert project.action_log[-1].actor == "mcp"
    assert project.action_log[-1].name == "remember_fact"

    again = _call(
        server, "remember_fact", **_FACT, confirm_token=preview["confirm_token"]
    )
    assert again["isError"]  # the project changed, and the token was spent

    store.undo(project_id)
    assert not any(t.object == "Club de lecture" for t in store.current().triplets)


def test_a_token_is_bound_to_its_arguments_and_to_the_project_state(home: Path) -> None:
    server, store = _writer(home)
    token = _payload(_call(server, "remember_fact", **_FACT))["confirm_token"]

    other = {**_FACT, "object": "Club d'échecs"}
    changed = _call(server, "remember_fact", **other, confirm_token=token)
    assert changed["isError"] and "ne correspond pas" in changed["content"][0]["text"]

    token = _payload(_call(server, "remember_fact", **_FACT))["confirm_token"]
    project = store.current()
    store.save(project)  # the page saved in between
    stale = _call(server, "remember_fact", **_FACT, confirm_token=token)
    assert stale["isError"] and "modifié depuis l'aperçu" in stale["content"][0]["text"]


def test_an_attribute_can_be_remembered(home: Path) -> None:
    server, store = _writer(home)
    arguments = {
        "entity": "Lyon",
        "key": "Population",
        "value": "522 000",
        "source": "INSEE",
    }
    token = _payload(_call(server, "remember_fact", **arguments))["confirm_token"]

    _payload(_call(server, "remember_fact", **arguments, confirm_token=token))

    attribute = next(a for a in store.current().attributes if a.entity == "Lyon")
    assert (attribute.key, attribute.value) == ("population", "522 000")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({**_FACT, "source": ""}, "source"),
        ({**_FACT, "object_type": ""}, "indiquez object_type"),
        ({**_FACT, "predicate": ""}, "Indiquez predicate"),
    ],
)
def test_a_fact_without_source_or_type_is_refused(
    home: Path, arguments: dict[str, Any], message: str
) -> None:
    server, _store = _writer(home)

    result = _call(server, "remember_fact", **arguments)

    assert result["isError"] and message in result["content"][0]["text"]


def test_a_rule_is_certified_once_and_appears_in_the_brief(home: Path) -> None:
    server, store = _writer(home)
    rule = {
        "text": "Un prêt dépasse 3 semaines seulement avec l'accord de la direction.",
        "source": "bibliotheque.txt",
        "tags": ["prêts"],
    }

    token = _payload(_call(server, "certify_rule", **rule))["confirm_token"]
    done = _payload(_call(server, "certify_rule", **rule, confirm_token=token))
    assert done["applied"] and done["id"]

    token = _payload(_call(server, "certify_rule", **rule))["confirm_token"]
    twice = _payload(_call(server, "certify_rule", **rule, confirm_token=token))
    assert twice["applied"] is False and twice["already_certified"]
    assert len(store.current().rules) == 1

    brief = _payload(_call(server, "brief", since="1h"))
    assert any("accord de la direction" in line for line in brief["rules"])
    report = _payload(_call(server, "export_report", kind="meeting"))
    assert "accord de la direction" in report["markdown"]


def test_writes_wait_for_an_extraction_in_another_process(home: Path) -> None:
    server, store = _writer(home)
    project_id = store.current().id
    marker = store.project_dir(project_id) / BUSY_FILE
    marker.write_text(json.dumps({"pid": os.getpid(), "at": "now"}))

    busy = _call(server, "remember_fact", **_FACT)
    assert busy["isError"] and "extraction est en cours" in busy["content"][0]["text"]

    old = time.time() - 3600
    os.utime(marker, (old, old))  # not refreshed for an hour: a crashed process
    assert not _call(server, "remember_fact", **_FACT)["isError"]

    dead = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        capture_output=True,
        text=True,
        check=True,
    )
    marker.write_text(json.dumps({"pid": int(dead.stdout)}))
    assert store.busy_reason(project_id) is None


def test_the_marker_lasts_as_long_as_the_extraction(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    project = store.create("Busy")

    with store.busy(project.id):
        assert store.busy_reason(project.id) is not None
    assert store.busy_reason(project.id) is None
    assert not (store.project_dir(project.id) / BUSY_FILE).exists()


# --- Confirmation tokens ---------------------------------------------------------------


def test_tokens_expire_and_cannot_be_forged() -> None:
    expired = Confirmations(ttl_s=-1)
    token = expired.issue("t", {"a": 1}, project="p", revision="r")
    with pytest.raises(ConfirmationError, match="expiré"):
        expired.redeem(token, "t", {"a": 1}, project="p", revision="r")

    first, second = Confirmations(), Confirmations()
    token = first.issue("t", {"a": 1}, project="p", revision="r")
    with pytest.raises(ConfirmationError, match="ne correspond pas"):
        second.redeem(token, "t", {"a": 1}, project="p", revision="r")  # restarted
    with pytest.raises(ConfirmationError, match="illisible"):
        first.redeem("garbage", "t", {"a": 1}, project="p", revision="r")
    first.redeem(
        token, "t", {"a": 1, "confirm_token": token}, project="p", revision="r"
    )


# --- Reports ----------------------------------------------------------------------


def test_the_meeting_report_sorts_one_documents_facts(home: Path) -> None:
    report = meeting(ProjectStore(home).current())

    assert report.title == "Compte rendu — bibliotheque.txt"
    sections = dict(report.sections)
    assert "Camille Martin" in sections["Participants"]
    assert any("1843" in line for line in sections["Chiffres et dates"])
    assert "« " in report.markdown()  # facts carry their passage
    with pytest.raises(ReportError, match="Aucun document"):
        meeting(ProjectStore(home).current(), "absent.pdf")


def test_the_meeting_report_says_why_it_may_be_empty(home: Path) -> None:
    store = ProjectStore(home)
    project = store.current()
    assert meeting(project).note == ""

    project.documents[0].genre = "book_chapter"
    assert "pas à une réunion" in meeting(project).markdown()
    project.documents[0].status = "running"
    assert meeting(project).note.startswith("Extraction en cours")


def test_the_comparison_puts_entities_side_by_side(home: Path) -> None:
    report = comparison(
        ProjectStore(home).current(), ["Ada Lovelace", "charles babbage", "Inconnu"]
    )

    assert report.data["entities"] == ["Ada Lovelace", "Charles Babbage"]
    assert report.data["missing"] == ["Inconnu"]
    assert report.table.startswith("| | Ada Lovelace | Charles Babbage |")
    assert "| a ecrit | Notes sur la machine analytique | — |" in report.table


def test_cli_report_and_rules(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cr.md"
    assert (
        studio.main(["report", "meeting", "--out", str(out), "--home", str(home)]) == 0
    )
    assert out.read_text(encoding="utf-8").startswith("# Compte rendu")
    capsys.readouterr()

    assert (
        studio.main(["report", "compare", "Lyon", "France", "--home", str(home)]) == 0
    )
    assert "| | Lyon | France |" in capsys.readouterr().out
    assert studio.main(["report", "compare", "Lyon", "--home", str(home)]) == 2

    text = "Tout livre rare se consulte sur place."
    assert (
        studio.main(
            ["rules", "add", text, "--source", "règlement", "--home", str(home)]
        )
        == 0
    )
    capsys.readouterr()
    assert studio.main(["rules", "--home", str(home)]) == 0
    listing = capsys.readouterr().out
    assert text in listing and "règlement" in listing
    rule_id = listing.split()[0]
    assert studio.main(["rules", "retire", rule_id, "--home", str(home)]) == 0
    capsys.readouterr()
    assert studio.main(["rules", "--home", str(home)]) == 0
    assert "Aucune règle" in capsys.readouterr().out


def test_api_rules_and_reports(home: Path) -> None:
    client = TestClient(
        create_app(home=home, fake=True), base_url="http://127.0.0.1:4173"
    )

    created = client.post(
        "/api/v1/rules", json={"text": "Les prêts durent trois semaines."}
    )
    assert created.status_code == 200 and created.json()["applied"]
    rules = client.get("/api/v1/rules").json()["rules"]
    assert [r["text"] for r in rules] == ["Les prêts durent trois semaines."]
    assert (
        client.delete(f"/api/v1/rules/{rules[0]['id']}").json()["status"] == "retired"
    )
    assert client.get("/api/v1/rules").json()["rules"] == []
    assert client.delete("/api/v1/rules/absente").status_code == 404

    assert client.get("/api/v1/report/meeting").json()["document"] == "bibliotheque.txt"
    compared = client.get(
        "/api/v1/report/compare", params={"names": ["Lyon", "France"]}
    )
    assert compared.json()["entities"] == ["Lyon", "France"]
    assert (
        client.get("/api/v1/report/compare", params={"names": ["Lyon"]}).status_code
        == 422
    )


# --- The stdin loop and robustness ---------------------------------------------------------


def test_the_server_loop_answers_line_by_line(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_tables", "arguments": {}},
        },
    ]
    stdin = "\n".join(json.dumps(line) for line in lines) + "\nnot json\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    mcp_stdio.serve_mcp(home)

    answers = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [a.get("id") for a in answers] == [1, 2, None]
    assert answers[1]["result"]["structuredContent"]["tables"][0]["table"] == "prets"
    assert answers[2]["error"]["code"] == -32700


def test_the_chunk_cache_keeps_the_recently_used(tmp_path: Path) -> None:
    cache = FileChunkCache(tmp_path / "cache", max_entries=10)
    for index in range(10):
        cache.put(f"k{index}", TextOntology())
        old = time.time() - 1000 + index
        os.utime(tmp_path / "cache" / f"k{index}.json", (old, old))
    assert cache.get("k0") is not None  # used again: now the most recent

    cache.put("k10", TextOntology())

    kept = {path.stem for path in (tmp_path / "cache").glob("*.json")}
    assert len(kept) == 9 and {"k0", "k10"} <= kept and "k1" not in kept


def test_finished_jobs_are_forgotten_past_a_limit() -> None:
    from auto_ontology.text_ontology.app import server

    class FakeJob:
        def __init__(self, finished: bool) -> None:
            self.finished = finished

    class FakeStudio:
        jobs = {f"j{i}": FakeJob(i != 30) for i in range(31)}

    server._prune_jobs(FakeStudio())  # type: ignore[arg-type]

    assert len(FakeStudio.jobs) == server._KEPT_JOBS
    assert "j30" in FakeStudio.jobs  # a running job is never dropped
    assert "j0" not in FakeStudio.jobs


def test_the_api_token_is_compared_whole() -> None:
    assert access_allowed("10.0.0.2", "Bearer s3cret", "s3cret")
    assert not access_allowed("10.0.0.2", "Bearer s3cre", "s3cret")
    assert not access_allowed("10.0.0.2", "", "s3cret")
    assert access_allowed("127.0.0.1", "", "s3cret")
