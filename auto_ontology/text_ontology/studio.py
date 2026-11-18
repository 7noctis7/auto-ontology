# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Open the local ontology studio in a browser.

::

    uv run ontology serve

The page is served from this process. Projects are JSON files under
``~/AutoOntology``. No Postgres, no login and no chat worker is started.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

from auto_ontology.text_ontology.store import default_home


def serve(
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    open_browser: bool = True,
    home: Path | None = None,
    fake: bool = False,
    watch: str | None = None,
) -> None:
    """Bind the studio and, unless asked not to, open it in the browser."""
    import uvicorn

    from auto_ontology.text_ontology.app.server import create_app

    root = Path(home) if home is not None else default_home()
    if watch:
        from auto_ontology.text_ontology.store import ProjectStore

        settings = ProjectStore(root).settings()
        settings.watch_dir = watch
        ProjectStore(root).save_settings(settings)
    chosen = port if port is not None else int(os.environ.get("ONTOLOGY_PORT", "4173"))
    url = f"http://{host}:{chosen}/"
    print(f"Ontologie — {url}")
    print(f"Projets — {root}")
    if fake:
        print("Mode démonstration : aucun modèle n'est appelé.")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "Attention : le studio n'a pas de connexion par mot de passe et devient "
            "joignable depuis le réseau. Ne l'exposez que sur un réseau de confiance ; "
            "ajoutez dans ONTOLOGY_ALLOWED_HOSTS les noms par lesquels on l'ouvre."
        )
    print("Arrêt : Ctrl+C")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    app = create_app(home=root, fake=fake, bound_host=host)
    from auto_ontology.text_ontology.watch import start_watcher

    start_watcher(app.state.studio)
    uvicorn.run(app, host=host, port=chosen, log_level="info")


def main(argv: list[str] | None = None) -> int:
    """``ontology serve``."""
    # The repo-root .env holds REASONING_* (an LM Studio endpoint, say), as for
    # ``python -m auto_ontology.text_ontology``; without this it was ignored.
    from auto_ontology.env import load_env

    load_env()
    raw = list(sys.argv[1:] if argv is None else argv)
    from auto_ontology.text_ontology.__main__ import STUDIO_COMMANDS, first_command
    from auto_ontology.text_ontology.__main__ import main as text_main

    if first_command(raw) not in STUDIO_COMMANDS:
        # extract, merge, export, clean, eval, a bare file, or the help that
        # lists every command: one entry point for both groups.
        return text_main(raw)
    parser = argparse.ArgumentParser(
        prog="ontology",
        description="Studio local : déposez un document, voyez l'ontologie.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser(
        "serve", help="Ouvre l'application dans le navigateur."
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=None)
    serve_parser.add_argument(
        "--no-browser", action="store_true", help="Ne pas ouvrir le navigateur."
    )
    serve_parser.add_argument(
        "--home",
        default=None,
        help="Dossier des projets (défaut : ~/AutoOntology ou ONTOLOGY_HOME).",
    )
    serve_parser.add_argument(
        "--fake",
        action="store_true",
        help="Extraction de démonstration, sans appeler de modèle.",
    )
    serve_parser.add_argument(
        "--watch",
        default=None,
        help="Dossier importé automatiquement (les fichiers déjà connus sont ignorés).",
    )
    import_parser = commands.add_parser(
        "import", help="Extrait plusieurs fichiers dans le projet courant."
    )
    import_parser.add_argument("paths", nargs="*")
    import_parser.add_argument(
        "--paste", action="store_true", help="Importe aussi le texte du presse-papiers."
    )
    import_parser.add_argument("--home", default=None)
    import_parser.add_argument("--fake", action="store_true")
    ask_parser = commands.add_parser(
        "ask", help="Répond depuis les faits du projet, avec la source."
    )
    ask_parser.add_argument("question")
    ask_parser.add_argument("--home", default=None)
    mcp_parser = commands.add_parser(
        "mcp", help="Serveur MCP sur l'entrée standard, en lecture seule."
    )
    mcp_parser.add_argument("--home", default=None)
    open_parser = commands.add_parser(
        "open",
        help="Ouvre un dossier de travail : projet du même nom, import, "
        "surveillance et studio, en une commande.",
    )
    open_parser.add_argument("folder", help="Dossier à importer et à surveiller.")
    open_parser.add_argument("--port", type=int, default=None)
    open_parser.add_argument("--no-browser", action="store_true")
    open_parser.add_argument("--home", default=None)
    open_parser.add_argument(
        "--fake", action="store_true", help="Sans modèle (démonstration)."
    )
    brief_parser = commands.add_parser(
        "brief",
        help="Nouveautés et points à vérifier depuis une date (24h par défaut).",
    )
    brief_parser.add_argument(
        "--since", default="24h", help="24h, 7d, 2w, today, 2026-11-01…"
    )
    brief_parser.add_argument("--json", action="store_true")
    brief_parser.add_argument("--home", default=None)
    diff_parser = commands.add_parser(
        "diff", help="Classes, faits et attributs ajoutés ou retirés depuis une date."
    )
    diff_parser.add_argument(
        "--since", default="7d", help="24h, 7d, 2w, today, 2026-11-01…"
    )
    diff_parser.add_argument("--json", action="store_true")
    diff_parser.add_argument("--home", default=None)
    tables_parser = commands.add_parser(
        "tables", help="Liste les tables du projet courant (colonnes, types, exemples)."
    )
    tables_parser.add_argument("--home", default=None)
    sql_parser = commands.add_parser(
        "sql", help="Une requête SELECT en lecture seule sur les tables du projet."
    )
    sql_parser.add_argument(
        "query", help='Par exemple : "SELECT * FROM ventes LIMIT 5"'
    )
    sql_parser.add_argument("--limit", type=int, default=200)
    sql_parser.add_argument(
        "--format", choices=["table", "json", "csv"], default="table"
    )
    sql_parser.add_argument("--home", default=None)
    sdk_parser = commands.add_parser(
        "sdk", help="Écrit un client Python à partir du schéma du projet courant."
    )
    sdk_parser.add_argument("--home", default=None)
    sdk_parser.add_argument("--out", default="ontologie_client.py")
    args = parser.parse_args(raw)
    if args.command == "serve":
        serve(
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
            home=Path(args.home) if args.home else None,
            fake=args.fake,
            watch=args.watch,
        )
    elif args.command == "import":
        pasted = None
        if args.paste:
            from auto_ontology.text_ontology.daily import ClipboardError, read_clipboard

            try:
                pasted = read_clipboard()
            except ClipboardError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        if not args.paths and pasted is None:
            print("error: indiquez des fichiers ou --paste.", file=sys.stderr)
            return 2
        import_paths(
            [Path(path) for path in args.paths],
            home=Path(args.home) if args.home else None,
            fake=args.fake,
            pasted=pasted,
        )
    elif args.command in ("brief", "diff"):
        return daily_report(
            args.command,
            since=args.since,
            as_json=args.json,
            home=Path(args.home) if args.home else None,
        )
    elif args.command == "ask":
        print(ask_project(args.question, home=Path(args.home) if args.home else None))
    elif args.command == "mcp":
        from auto_ontology.text_ontology.mcp_stdio import serve_mcp

        serve_mcp(Path(args.home) if args.home else None)
    elif args.command == "sdk":
        write_sdk(Path(args.out), home=Path(args.home) if args.home else None)
    elif args.command == "tables":
        return show_tables(home=Path(args.home) if args.home else None)
    elif args.command == "sql":
        return query_tables(
            args.query,
            limit=args.limit,
            output=args.format,
            home=Path(args.home) if args.home else None,
        )
    elif args.command == "open":
        return open_folder(
            Path(args.folder),
            port=args.port,
            open_browser=not args.no_browser,
            home=Path(args.home) if args.home else None,
            fake=args.fake,
        )
    return 0


def daily_report(kind: str, *, since: str, as_json: bool, home: Path | None) -> int:
    """``ontology brief`` and ``ontology diff`` on the current project."""
    from auto_ontology.text_ontology.daily import as_json as to_json
    from auto_ontology.text_ontology.daily import brief, diff, parse_since

    found = _current_project(home)
    if found is None:
        return 1
    store, project = found
    try:
        moment = parse_since(since)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = (
        brief(project, moment)  # type: ignore[arg-type]
        if kind == "brief"
        else diff(project, store.project_dir(project.id), moment)  # type: ignore[arg-type, attr-defined]
    )
    sys.stdout.write(to_json(report.as_dict()) if as_json else report.markdown())
    return 0


def _current_project(home: Path | None) -> tuple[object, object] | None:
    from auto_ontology.text_ontology.store import ProjectStore

    store = ProjectStore(home or default_home())
    project = store.current()
    if project is None:
        print(
            "Aucun projet. Lancez d'abord `ontology open <dossier>` ou `ontology import`.",
            file=sys.stderr,
        )
        return None
    return store, project


def show_tables(*, home: Path | None) -> int:
    """``ontology tables``: what the current project's tables hold."""
    from auto_ontology.text_ontology.tables import describe_tables

    found = _current_project(home)
    if found is None:
        return 1
    _store, project = found
    print(
        describe_tables(project)
        or "Aucune table : importez un CSV, un Excel ou une base SQLite."
    )  # type: ignore[arg-type]
    return 0


def query_tables(query: str, *, limit: int, output: str, home: Path | None) -> int:
    """``ontology sql``: one read-only SELECT, printed as a table, JSON or CSV."""
    import csv
    import json

    from auto_ontology.text_ontology.tables import TableError, run_sql

    found = _current_project(home)
    if found is None:
        return 1
    store, project = found
    try:
        result = run_sql(store.project_dir(project.id), query, limit=limit)  # type: ignore[attr-defined]
    except TableError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if output == "json":
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    elif output == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(result.columns)
        writer.writerows(result.rows)
    else:
        print(result.as_table())
    return 0


def open_folder(
    folder: Path,
    *,
    port: int | None = None,
    open_browser: bool = True,
    home: Path | None = None,
    fake: bool = False,
) -> int:
    """``ontology open <folder>``: one command from a folder to a studio.

    The project takes the folder's name (reopened next time), the watcher
    imports the files already there and those that arrive, and the page
    opens on that project.
    """
    from auto_ontology.text_ontology.store import ProjectStore

    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        print(f"Dossier introuvable : {folder}", file=sys.stderr)
        return 1
    root = Path(home) if home is not None else default_home()
    project = ProjectStore(root).open_named(folder.name)
    print(f"Projet « {project.name} » — dossier surveillé : {folder}")
    serve(
        port=port,
        open_browser=open_browser,
        home=root,
        fake=fake,
        watch=str(folder),
    )
    return 0


def import_paths(
    paths: list[Path], *, home: Path | None, fake: bool, pasted: str | None = None
) -> None:
    """Extract each file into the current project. Same pipeline as the page."""
    from auto_ontology.text_ontology.documents import load_bytes
    from auto_ontology.text_ontology.llm_settings import (
        build_llm,
        model_label,
        resolve_llm_config,
    )
    from auto_ontology.text_ontology.pipeline import ingest_document
    from auto_ontology.text_ontology.sample import FakeLLM
    from auto_ontology.text_ontology.store import ProjectStore

    from auto_ontology.text_ontology.tables import import_tabular, is_tabular

    store = ProjectStore(home or default_home())
    project = store.current() or store.create("Import")
    documents = [path for path in paths if not is_tabular(path.name)]
    for path in paths:
        if is_tabular(path.name):
            # A spreadsheet becomes a table: no model needed.
            for record in import_tabular(store, project, path.name, path.read_bytes()):
                print(f"{path.name} → table {record.table} ({record.rows} lignes)")
    if not documents and pasted is None:
        return
    config = resolve_llm_config(store)
    llm = FakeLLM() if fake else build_llm(config)
    label = "démonstration" if fake else model_label(llm, config)
    from datetime import datetime

    from auto_ontology.text_ontology.documents import load_text

    sources = [
        (path.name, lambda path=path: load_bytes(path.name, path.read_bytes()))
        for path in documents
    ]
    if pasted is not None:
        name = f"presse-papiers {datetime.now():%Y-%m-%d %H%M}.txt"
        sources.append((name, lambda: load_text(name, pasted)))
    for name, read in sources:
        project = store.load(project.id)
        loaded = read()
        ingest_document(
            store,
            project,
            loaded,
            config=config,
            llm=llm,
            model_label=label,
            # Both are required: without them `ontology import` failed on
            # every file with a TypeError, and never imported anything.
            force=False,
            cancel_event=None,
            on_event=lambda _event: None,
        )
        project = store.load(project.id)
        print(f"{name} → {project.name} ({len(project.ontology.triplets)} faits)")


def write_sdk(destination: Path, *, home: Path | None) -> None:
    """Write a generated client next to the path the person gave."""
    from auto_ontology.text_ontology.schema_layer import sync_schema
    from auto_ontology.text_ontology.sdkgen import render_sdk
    from auto_ontology.text_ontology.store import ProjectStore

    store = ProjectStore(home or default_home())
    settings = store.settings()
    project = None
    if settings.last_project_id:
        try:
            project = store.load(settings.last_project_id)
        except (FileNotFoundError, ValueError):
            project = None
    if project is None:
        projects = store.list_projects()
        project = projects[0] if projects else None
    if project is None:
        raise SystemExit("Aucun projet.")
    sync_schema(project)
    destination.write_text(render_sdk(project), encoding="utf-8")
    print(destination)


def ask_project(question: str, *, home: Path | None) -> str:
    """One sentence and its source, from the current project."""
    from auto_ontology.text_ontology.query import answer
    from auto_ontology.text_ontology.store import ProjectStore

    store = ProjectStore(home or default_home())
    settings = store.settings()
    project = None
    if settings.last_project_id:
        try:
            project = store.load(settings.last_project_id)
        except (FileNotFoundError, ValueError):
            project = None
    if project is None:
        projects = store.list_projects()
        project = projects[0] if projects else None
    if project is None:
        return "Aucun projet."
    payload = answer(project, question)
    lines = [str(payload["answer"])]
    for fact in payload["facts"]:
        if isinstance(fact, dict) and fact.get("quote"):
            lines.append(f"- {fact['filename']} : {fact['quote']}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
