# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tabular files as queryable tables, in one DuckDB file per project.

A CSV sent to the model as prose cannot be summed or filtered. Here CSV, TSV,
Excel, Parquet, SQLite and DuckDB files become tables in
``<project>/data.duckdb``, each profiled (columns, types, nulls, a few
values) so a person or an agent knows what it holds.

Queries are read-only by construction, because a model or an agent writes
them:

* the statement is parsed first and must be a single ``SELECT`` (or ``WITH``
  … ``SELECT``, set operations included);
* the connection is opened read-only, with DuckDB's external access off and
  its configuration locked, so no file, URL or extension can be reached even
  by a statement the parser let through;
* rows are capped and a query that runs too long is interrupted.
"""

from __future__ import annotations

import hashlib
import io
import re
import sqlite3
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auto_ontology.text_ontology.normalize import ascii_fold
from auto_ontology.text_ontology.studio_models import (
    ColumnProfile,
    DatasetRecord,
    Project,
)

TABULAR_SUFFIXES = frozenset(
    {
        ".csv",
        ".tsv",
        ".xlsx",
        ".xlsm",
        ".parquet",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".duckdb",
    }
)
DATA_FILE = "data.duckdb"
DEFAULT_ROW_LIMIT = 200
DEFAULT_TIMEOUT_S = 20.0
_SAMPLES = 3

# One writer per database file at a time, within this process.
_WRITE_LOCKS: dict[str, threading.Lock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


class TableError(ValueError):
    """A file could not be loaded, or a query is refused. The message is for people."""


def is_tabular(filename: str) -> bool:
    return Path(filename).suffix.lower() in TABULAR_SUFFIXES


def data_path(project_dir: Path) -> Path:
    return Path(project_dir) / DATA_FILE


def _write_lock(path: Path) -> threading.Lock:
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(str(path.resolve()), threading.Lock())


@contextmanager
def _writer(path: Path) -> Iterator[Any]:
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock(path):
        connection = duckdb.connect(str(path))
        try:
            yield connection
        finally:
            connection.close()


def _reader(path: Path) -> Any:
    import duckdb

    if not path.is_file():
        raise TableError(
            "Ce projet n'a encore aucune table. Importez un CSV ou un tableur."
        )
    return duckdb.connect(
        str(path),
        read_only=True,
        config={"enable_external_access": "false", "lock_configuration": "true"},
    )


def table_name(stem: str, sheet: str = "") -> str:
    """A safe SQL identifier: ``Ventes 2026.xlsx`` sheet ``T1`` -> ``ventes_2026_t1``."""
    raw = f"{stem}_{sheet}" if sheet else stem
    name = re.sub(r"[^a-z0-9]+", "_", ascii_fold(raw).lower()).strip("_") or "table"
    return f"t_{name}" if name[0].isdigit() else name


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _frames(filename: str, data: bytes) -> list[tuple[str, Any]]:
    """(sheet or table name, pandas DataFrame) for formats DuckDB cannot read alone."""
    import pandas as pd

    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        try:
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, engine="openpyxl")
        except Exception as exc:
            raise TableError(f"Ce classeur n'a pas pu être lu : {exc}") from exc
        return [(str(sheet), frame) for sheet, frame in sheets.items()]
    # SQLite: read with the standard library, no DuckDB extension to download.
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(data)
        handle.flush()
        try:
            source = sqlite3.connect(f"file:{handle.name}?mode=ro", uri=True)
            names = [
                row[0]
                for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            frames = [
                (name, pd.read_sql_query(f"SELECT * FROM {_quoted(name)}", source))
                for name in names
            ]
            source.close()
        except sqlite3.DatabaseError as exc:
            raise TableError(f"Cette base SQLite n'a pas pu être lue : {exc}") from exc
    return frames


def _is_sqlite(data: bytes) -> bool:
    return data[:16] == b"SQLite format 3\x00"


def _profile(connection: Any, table: str) -> tuple[int, list[ColumnProfile]]:
    quoted = _quoted(table)
    rows = int(connection.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0])
    columns = []
    for name, kind, *_ in connection.execute(f"DESCRIBE {quoted}").fetchall():
        column = _quoted(name)
        nulls, distinct = connection.execute(
            f"SELECT count(*) - count({column}), approx_count_distinct({column}) "
            f"FROM {quoted}"
        ).fetchone()
        samples = [
            str(value)
            for (value,) in connection.execute(
                f"SELECT DISTINCT {column} FROM {quoted} WHERE {column} IS NOT NULL "
                f"LIMIT {_SAMPLES}"
            ).fetchall()
        ]
        columns.append(
            ColumnProfile(
                name=name,
                type=str(kind),
                nulls=int(nulls),
                distinct=int(distinct),
                samples=samples,
            )
        )
    return rows, columns


def load_tabular(
    project_dir: Path, project: Project, filename: str, data: bytes, *, added_at: str
) -> list[DatasetRecord]:
    """Load *data* as one table per sheet or source table, profiled.

    The project's ``datasets`` are updated in place (a table loaded again from
    a changed file is replaced). A file whose content was already loaded is
    left as it is and its records are returned unchanged.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in TABULAR_SUFFIXES:
        raise TableError(f"{filename} n'est pas un fichier tabulaire.")
    digest = hashlib.sha256(data).hexdigest()
    known = [d for d in project.datasets if d.sha256 == digest]
    if known:
        return known
    stem = Path(filename).stem
    path = data_path(project_dir)
    loaded: list[tuple[str, str]] = []  # (table, sheet)
    with _writer(path) as connection:
        if suffix in {".csv", ".tsv", ".parquet", ".duckdb"} or (
            suffix == ".db" and not _is_sqlite(data)
        ):
            with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
                handle.write(data)
                handle.flush()
                source = _literal(handle.name)
                try:
                    if suffix == ".parquet":
                        loaded.append(
                            _create(connection, stem, "", f"read_parquet({source})")
                        )
                    elif suffix in {".duckdb", ".db"}:
                        connection.execute(f"ATTACH {source} AS incoming (READ_ONLY)")
                        try:
                            for (name,) in connection.execute(
                                "SELECT table_name FROM duckdb_tables() "
                                "WHERE database_name = 'incoming' ORDER BY table_name"
                            ).fetchall():
                                loaded.append(
                                    _create(
                                        connection,
                                        stem,
                                        name,
                                        f"incoming.{_quoted(name)}",
                                    )
                                )
                        finally:
                            connection.execute("DETACH incoming")
                    else:
                        delimiter = ", delim='\\t'" if suffix == ".tsv" else ""
                        loaded.append(
                            _create(
                                connection,
                                stem,
                                "",
                                f"read_csv_auto({source}{delimiter}, sample_size=-1)",
                            )
                        )
                except TableError:
                    raise
                except Exception as exc:
                    raise TableError(
                        f"{filename} n'a pas pu être chargé : {exc}"
                    ) from exc
        else:
            frames = _frames(filename, data)
            for sheet, frame in frames:
                single = len(frames) == 1 and suffix in {".xlsx", ".xlsm"}
                connection.register("incoming_frame", frame)
                try:
                    loaded.append(
                        _create(
                            connection, stem, "" if single else sheet, "incoming_frame"
                        )
                    )
                finally:
                    connection.unregister("incoming_frame")
        if not loaded:
            raise TableError(f"{filename} ne contient aucune table.")
        records = []
        for table, sheet in loaded:
            rows, columns = _profile(connection, table)
            records.append(
                DatasetRecord(
                    table=table,
                    source=filename,
                    sheet=sheet,
                    sha256=digest,
                    rows=rows,
                    columns=columns,
                    added_at=added_at,
                )
            )
    names = {record.table for record in records}
    project.datasets = [d for d in project.datasets if d.table not in names] + records
    return records


def _create(connection: Any, stem: str, sheet: str, source: str) -> tuple[str, str]:
    table = table_name(stem, sheet)
    connection.execute(
        f"CREATE OR REPLACE TABLE {_quoted(table)} AS SELECT * FROM {source}"
    )
    return table, sheet


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------


@dataclass
class SqlResult:
    """Rows of a read-only query, capped."""

    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "sql": self.sql,
            "columns": self.columns,
            "rows": [[_jsonable(v) for v in row] for row in self.rows],
            "truncated": self.truncated,
        }

    def as_table(self) -> str:
        """A plain-text table for a terminal."""
        header = [str(c) for c in self.columns]
        body = [[_cell(v) for v in row] for row in self.rows]
        widths = [
            max([len(header[i])] + [len(row[i]) for row in body])
            for i in range(len(header))
        ]
        lines = ["  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True))]
        lines.append("  ".join("-" * w for w in widths))
        lines += [
            "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True))
            for row in body
        ]
        if self.truncated:
            lines.append(f"… (limité à {len(self.rows)} lignes)")
        return "\n".join(lines)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


_FORBIDDEN_FUNCTIONS = re.compile(
    r"^(read_|glob$|sniff_|parquet_|iceberg_|delta_|sqlite_|postgres_|mysql_|"
    r"httpfs|load_|install_)",
    re.IGNORECASE,
)


def _looks_like_path(name: str) -> bool:
    """DuckDB reads ``FROM '/x/y.csv'`` as a file: a table name never has these."""
    return any(mark in name for mark in ("/", "\\", "://", "~")) or bool(
        re.search(r"\.(csv|tsv|json|parquet|txt|db|duckdb|sqlite|xlsx?)$", name, re.I)
    )


def check_select(sql: str) -> str:
    """*sql* if it is one read-only ``SELECT``; a :class:`TableError` otherwise.

    The engine-level lock (read-only, no external access) is the real guard;
    this gives a clear message instead of a DuckDB error, and refuses table
    functions that read files before they reach the engine.
    """
    import sqlglot
    from sqlglot import exp

    text = sql.strip().rstrip(";").strip()
    if not text:
        raise TableError("La requête est vide.")
    try:
        statements = [s for s in sqlglot.parse(text, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise TableError(f"Requête SQL illisible : {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise TableError("Une seule requête à la fois.")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise TableError("Seules les requêtes SELECT sont permises (lecture seule).")
    writes = tuple(
        getattr(exp, name)
        for name in (
            "Insert",
            "Update",
            "Delete",
            "Create",
            "Drop",
            "Alter",
            "Command",
            "Set",
            "Pragma",
            "Copy",
            "Attach",
            "Detach",
            "Merge",
            "TruncateTable",
        )
        if hasattr(exp, name)
    )
    for node in statement.walk():
        if isinstance(node, writes):
            raise TableError(
                "Seules les requêtes SELECT sont permises (lecture seule)."
            )
        if isinstance(node, exp.Func):
            name = node.sql_name() if not isinstance(node, exp.Anonymous) else node.name
            if _FORBIDDEN_FUNCTIONS.match(str(name)):
                raise TableError(
                    f"La fonction {name} n'est pas permise : elle lit des fichiers."
                )
        if isinstance(node, exp.Table) and _looks_like_path(node.name):
            raise TableError("Lire un fichier par son chemin n'est pas permis.")
    return text


def run_sql(
    project_dir: Path,
    sql: str,
    *,
    limit: int = DEFAULT_ROW_LIMIT,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    prepare: Any = None,
) -> SqlResult:
    """Run one read-only ``SELECT`` on the project's tables, capped and timed.

    *prepare*, if given, is called with the connection first (it can register
    functions; the connection is read-only and cannot reach files).
    """
    text = check_select(sql)
    connection = _reader(data_path(project_dir))
    timer = threading.Timer(timeout_s, connection.interrupt)
    try:
        if prepare is not None:
            prepare(connection)
        timer.start()
        try:
            cursor = connection.execute(text)
            rows = cursor.fetchmany(limit + 1)
        except Exception as exc:
            if "interrupt" in str(exc).lower():
                raise TableError(
                    f"Requête interrompue après {timeout_s:.0f} s."
                ) from exc
            raise TableError(
                f"La requête a échoué : {str(exc).splitlines()[0]}"
            ) from exc
        columns = [description[0] for description in cursor.description or []]
    finally:
        timer.cancel()
        connection.close()
    return SqlResult(
        sql=text,
        columns=columns,
        rows=[list(row) for row in rows[:limit]],
        truncated=len(rows) > limit,
    )


def describe_tables(project: Project) -> str:
    """The project's tables for a prompt or a terminal: columns, types, samples."""
    lines = []
    for record in project.datasets:
        origin = f"{record.source}" + (
            f", feuille {record.sheet}" if record.sheet else ""
        )
        lines.append(f"Table {record.table} ({record.rows} lignes, depuis {origin}) :")
        for column in record.columns:
            samples = ", ".join(column.samples)
            lines.append(
                f"  - {column.name} {column.type}"
                + (f" — ex. {samples}" if samples else "")
            )
    return "\n".join(lines)


def import_tabular(
    store: Any, project: Project, filename: str, data: bytes
) -> list[DatasetRecord]:
    """Load a tabular file into *project* and save it: the one path for every entry point.

    The studio's upload, ``ontology import``, the watched folder and the API
    all come here, so a table is profiled and recorded the same way. The
    project is reloaded first, so a save made meanwhile is not lost.
    """
    from auto_ontology.text_ontology.store import now_iso

    current = store.load(project.id)
    records = load_tabular(
        store.project_dir(current.id), current, filename, data, added_at=now_iso()
    )
    store.save(current, snapshot=True)
    project.datasets = current.datasets
    return records
