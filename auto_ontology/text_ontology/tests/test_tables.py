# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Spreadsheets as read-only tables in the project's DuckDB file."""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auto_ontology.text_ontology import studio
from auto_ontology.text_ontology.app.server import create_app
from auto_ontology.text_ontology.store import ProjectStore
from auto_ontology.text_ontology.tables import (
    TableError,
    _reader,
    check_select,
    data_path,
    import_tabular,
    run_sql,
    table_name,
)

_CSV = (
    b"client,plafond,ville\nACME,50000,Lyon\nOrbital Lab,120000,Toulouse\nBeta,,Paris\n"
)


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "home")


def _load(store: ProjectStore, filename: str, data: bytes) -> list:
    project = store.current() or store.open_named("Données")
    return import_tabular(store, project, filename, data)


def test_a_csv_becomes_a_profiled_table(store: ProjectStore) -> None:
    (record,) = _load(store, "Clients 2026.csv", _CSV)

    assert record.table == "clients_2026"
    assert record.rows == 3
    columns = {c.name: c for c in record.columns}
    assert columns["plafond"].type in {"BIGINT", "INTEGER"}
    assert columns["plafond"].nulls == 1
    assert "ACME" in columns["client"].samples
    assert store.current().datasets[0].table == "clients_2026"


def test_the_same_file_twice_is_loaded_once_and_a_change_replaces_it(
    store: ProjectStore,
) -> None:
    _load(store, "clients.csv", _CSV)
    _load(store, "clients.csv", _CSV)
    _load(store, "clients.csv", _CSV + b"Gamma,1,Nice\n")

    project = store.current()
    assert [d.table for d in project.datasets] == ["clients"]
    assert project.datasets[0].rows == 4


def test_tsv_parquet_excel_sqlite_and_duckdb_files_load(store: ProjectStore) -> None:
    import duckdb
    import pandas as pd

    frame = pd.DataFrame({"produit": ["A", "B"], "prix": [10.5, 20.0]})
    parquet = io.BytesIO()
    frame.to_parquet(parquet)
    excel = io.BytesIO()
    with pd.ExcelWriter(excel, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Prix", index=False)
        frame.to_excel(writer, sheet_name="Stock", index=False)
    sqlite_path = store.home / "source.sqlite"
    store.home.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("CREATE TABLE commandes (id INTEGER, montant REAL)")
        connection.execute("INSERT INTO commandes VALUES (1, 99.5)")
    duck_path = store.home / "source.duckdb"
    with duckdb.connect(str(duck_path)) as connection:
        connection.execute(
            "CREATE TABLE stocks AS SELECT 'A' AS produit, 3 AS quantite"
        )

    _load(store, "achats.tsv", b"fournisseur\tmontant\nX\t10\n")
    _load(store, "catalogue.parquet", parquet.getvalue())
    _load(store, "tarifs.xlsx", excel.getvalue())
    _load(store, "ventes.sqlite", sqlite_path.read_bytes())
    _load(store, "entrepot.duckdb", duck_path.read_bytes())

    tables = {d.table: d.rows for d in store.current().datasets}
    assert tables == {
        "achats": 1,
        "catalogue": 2,
        "tarifs_prix": 2,
        "tarifs_stock": 2,
        "ventes_commandes": 1,
        "entrepot_stocks": 1,
    }


def test_an_unreadable_file_says_so(store: ProjectStore) -> None:
    with pytest.raises(TableError, match="classeur"):
        _load(store, "abime.xlsx", b"not an excel file")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Ventes 2026", "ventes_2026"), ("2026 bilan", "t_2026_bilan"), ("Été", "ete")],
)
def test_table_names_are_safe_identifiers(raw: str, expected: str) -> None:
    assert table_name(raw) == expected


def test_queries_are_read_only_capped_and_timed(store: ProjectStore) -> None:
    _load(store, "clients.csv", _CSV)
    folder = store.project_dir(store.current().id)

    result = run_sql(folder, "SELECT client FROM clients WHERE plafond > 60000")
    assert result.columns == ["client"] and result.rows == [["Orbital Lab"]]

    capped = run_sql(folder, "SELECT * FROM range(1000)", limit=10)
    assert len(capped.rows) == 10 and capped.truncated

    with pytest.raises(TableError, match="interrompue"):
        run_sql(
            folder,
            "SELECT count(*) FROM range(100000000) a, range(100000) b",
            timeout_s=0.3,
        )


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM clients",
        "DROP TABLE clients",
        "SELECT 1; DROP TABLE clients",
        "COPY clients TO 'x.csv'",
        "ATTACH 'x.db'",
        "SELECT * FROM read_csv('/etc/hostname')",
        "SELECT * FROM '/etc/hostname'",
        "SELECT * FROM glob('/home/*')",
        "PRAGMA database_list",
    ],
)
def test_writes_and_file_reads_are_refused(query: str) -> None:
    with pytest.raises(TableError):
        check_select(query)


def test_the_engine_itself_refuses_files_and_writes(store: ProjectStore) -> None:
    """Defense in depth: even a statement past the checker cannot reach files."""
    _load(store, "clients.csv", _CSV)
    connection = _reader(data_path(store.project_dir(store.current().id)))
    try:
        for statement in (
            "SELECT * FROM read_csv('/etc/hostname')",
            "CREATE TABLE x AS SELECT 1",
            "SET enable_external_access = true",
        ):
            with pytest.raises(Exception):  # noqa: B017 - any refusal will do
                connection.execute(statement)
    finally:
        connection.close()


def test_cli_import_tables_and_sql(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sheet = tmp_path / "clients.csv"
    sheet.write_bytes(_CSV)
    home = tmp_path / "home"

    assert studio.main(["import", str(sheet), "--home", str(home)]) == 0
    assert "table clients (3 lignes)" in capsys.readouterr().out

    assert studio.main(["tables", "--home", str(home)]) == 0
    listing = capsys.readouterr().out
    assert "Table clients (3 lignes" in listing
    assert "- plafond BIGINT" in listing and "ACME" in listing

    assert (
        studio.main(
            [
                "sql",
                "SELECT client FROM clients ORDER BY plafond DESC LIMIT 1",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    assert "Orbital Lab" in capsys.readouterr().out

    assert studio.main(["sql", "DELETE FROM clients", "--home", str(home)]) == 1
    assert "lecture seule" in capsys.readouterr().err


def test_the_studio_loads_an_uploaded_spreadsheet_without_a_model(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(home=tmp_path), base_url="http://127.0.0.1:4173")

    response = client.post(
        "/api/ingest", files={"file": ("clients.csv", _CSV, "text/csv")}
    )

    assert response.status_code == 200, response.text
    assert "clients (3 lignes)" in response.json()["notice"]
    assert [t["table"] for t in client.get("/api/v1/tables").json()["tables"]] == [
        "clients"
    ]
    rows = client.post(
        "/api/v1/sql", json={"sql": "SELECT sum(plafond) AS total FROM clients"}
    ).json()
    assert rows["rows"] == [[170000]]
    refused = client.post("/api/v1/sql", json={"sql": "DROP TABLE clients"})
    assert refused.status_code == 400
