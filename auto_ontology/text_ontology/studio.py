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
        "import",
        help="Importe des fichiers, des dossiers (Obsidian), des zips (Notion), "
        "des e-mails (.eml) et des tableurs dans le projet courant.",
    )
    import_parser.add_argument("paths", nargs="*")
    import_parser.add_argument(
        "--paste", action="store_true", help="Importe aussi le texte du presse-papiers."
    )
    import_parser.add_argument(
        "--force",
        action="store_true",
        help="Réextrait un contenu déjà présent (par exemple avec un autre modèle).",
    )
    import_parser.add_argument("--home", default=None)
    import_parser.add_argument("--fake", action="store_true")
    ask_parser = commands.add_parser(
        "ask", help="Répond depuis les faits du projet, avec la source."
    )
    ask_parser.add_argument("question")
    ask_parser.add_argument("--home", default=None)
    mcp_parser = commands.add_parser(
        "mcp",
        help="Serveur MCP sur l'entrée standard (lecture ; écritures confirmées "
        "avec --allow-writes).",
    )
    mcp_parser.add_argument("--home", default=None)
    mcp_parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="Ajoute remember_fact et certify_rule : chaque écriture demande un "
        "aperçu puis un jeton de confirmation, et s'annule depuis le studio.",
    )
    report_parser = commands.add_parser(
        "report",
        help="Rapport Markdown depuis les faits : compte rendu de réunion ou "
        "tableau comparatif.",
    )
    report_parser.add_argument("kind", choices=["meeting", "compare"])
    report_parser.add_argument("names", nargs="*", help="compare : deux noms ou plus.")
    report_parser.add_argument(
        "--document", default=None, help="meeting : partie du nom du fichier."
    )
    report_parser.add_argument("--out", default=None, help="Écrit dans ce fichier.")
    report_parser.add_argument("--json", action="store_true")
    report_parser.add_argument("--home", default=None)
    rules_parser = commands.add_parser(
        "rules", help="Règles et décisions certifiées du projet courant."
    )
    rules_parser.add_argument(
        "action", nargs="?", choices=["list", "add", "retire"], default="list"
    )
    rules_parser.add_argument(
        "text", nargs="?", default="", help="add : la règle ; retire : son id."
    )
    rules_parser.add_argument("--source", default="", help="add : d'où elle vient.")
    rules_parser.add_argument("--rationale", default="", help="add : pourquoi.")
    rules_parser.add_argument(
        "--all", action="store_true", help="list : y compris retirées."
    )
    rules_parser.add_argument("--home", default=None)
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
        return import_paths(
            [Path(path).expanduser() for path in args.paths],
            home=Path(args.home) if args.home else None,
            fake=args.fake,
            pasted=pasted,
            force=args.force,
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

        serve_mcp(
            Path(args.home) if args.home else None, allow_writes=args.allow_writes
        )
    elif args.command == "report":
        return write_report(
            args.kind,
            names=args.names,
            document=args.document,
            out=Path(args.out) if args.out else None,
            as_json=args.json,
            home=Path(args.home) if args.home else None,
        )
    elif args.command == "rules":
        return manage_rules(
            args.action,
            args.text,
            source=args.source,
            rationale=args.rationale,
            show_all=args.all,
            home=Path(args.home) if args.home else None,
        )
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
    from auto_ontology.text_ontology.inbox import read_journal

    folder = store.project_dir(project.id)  # type: ignore[attr-defined]
    report = (
        brief(project, moment, read_journal(folder, moment))  # type: ignore[arg-type]
        if kind == "brief"
        else diff(project, store.project_dir(project.id), moment)  # type: ignore[arg-type, attr-defined]
    )
    sys.stdout.write(to_json(report.as_dict()) if as_json else report.markdown())
    return 0


def write_report(
    kind: str,
    *,
    names: list[str],
    document: str | None,
    out: Path | None,
    as_json: bool,
    home: Path | None,
) -> int:
    """``ontology report meeting|compare``: Markdown from the facts."""
    from auto_ontology.text_ontology.daily import as_json as to_json
    from auto_ontology.text_ontology.reports import ReportError, comparison, meeting

    found = _current_project(home)
    if found is None:
        return 1
    _store, project = found
    try:
        report = (
            meeting(project, document)  # type: ignore[arg-type]
            if kind == "meeting"
            else comparison(project, names)  # type: ignore[arg-type]
        )
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = to_json(report.as_dict()) if as_json else report.markdown()
    if out is not None:
        from auto_ontology.text_ontology.store import atomic_write_text

        atomic_write_text(out, text)
        print(out)
    else:
        sys.stdout.write(text)
    return 0


def manage_rules(
    action: str,
    text: str,
    *,
    source: str,
    rationale: str,
    show_all: bool,
    home: Path | None,
) -> int:
    """``ontology rules [list|add|retire]``: the person certifies directly."""
    from auto_ontology.text_ontology.agent_writes import (
        WriteError,
        certify_rule,
        retire_rule,
    )

    found = _current_project(home)
    if found is None:
        return 1
    store, project = found
    try:
        if action == "add":
            done = certify_rule(
                store,  # type: ignore[arg-type]
                project,  # type: ignore[arg-type]
                {"text": text, "source": source, "rationale": rationale},
                actor="local",
            )
            print(done["summary"] + ("" if done["applied"] else " (inchangé)"))
            return 0
        if action == "retire":
            rule = retire_rule(store, project, text.strip(), actor="local")  # type: ignore[arg-type]
            print(f"Retirée : {rule.text}")
            return 0
    except WriteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rules = [
        rule
        for rule in project.rules  # type: ignore[attr-defined]
        if show_all or rule.status == "certified"
    ]
    if not rules:
        print('Aucune règle certifiée. Ajoutez-en une : ontology rules add "…"')
    for rule in rules:
        mark = "" if rule.status == "certified" else " [retirée]"
        origin = f" — {rule.source}" if rule.source else ""
        print(f"{rule.id}  {rule.created_at[:10]}  {rule.text}{origin}{mark}")
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
    paths: list[Path],
    *,
    home: Path | None,
    fake: bool,
    pasted: str | None = None,
    force: bool = False,
) -> int:
    """Bring each file into the current project. Same pipeline as the page.

    A folder is walked (an Obsidian vault), a zip is opened (a Notion export),
    an email brings its attachments and a spreadsheet becomes a table. Returns
    the exit status: 1 when nothing could be brought in.
    """
    from datetime import datetime

    from auto_ontology.text_ontology.inbox import (
        Item,
        ingest_item,
        unpack,
        unreadable,
        walk,
    )
    from auto_ontology.text_ontology.store import ProjectStore

    store = ProjectStore(home or default_home())
    project = store.current() or store.create("Import")
    folder = store.project_dir(project.id)
    items: list[Item] = []
    unopened = 0
    for path in paths:
        files = list(walk(path, exclude=store.home)) if path.is_dir() else [path]
        if path.is_dir() and not files:
            print(f"{path} : aucun fichier pris en charge.", file=sys.stderr)
        for file in files:
            try:
                items += unpack(file.name, file.read_bytes())
            except OSError as exc:
                unopened += 1
                print(f"{file} : illisible ({exc.strerror}).", file=sys.stderr)
            except ValueError as exc:  # DocumentReadError: broken email or zip
                unopened += 1
                print(unreadable(folder, file.name, str(exc)).line(), file=sys.stderr)
    if pasted is not None:
        name = f"presse-papiers {datetime.now():%Y-%m-%d %H%M}.txt"
        items.append(Item(name, pasted.encode("utf-8")))

    model = _model_source(store, fake=fake)
    landed = 0
    for item in items:
        outcome = ingest_item(store, project.id, item, model=model, force=force)
        stream = sys.stderr if outcome.kind == "error" else sys.stdout
        print(outcome.line(), file=stream)
        landed += outcome.kind in {"document", "table", "duplicate"}
    if items:
        project = store.load(project.id)
        print(
            f"Projet « {project.name} » : {len(project.ontology.triplets)} faits, "
            f"{len(project.datasets)} table(s)."
        )
    return 0 if landed or not (items or unopened) else 1


def _model_source(store: object, *, fake: bool) -> object:
    """Build the model once, and only if a document needs one."""
    built: list[object] = []

    def source() -> object:
        if not built:
            from auto_ontology.text_ontology.llm_settings import (
                build_llm,
                model_label,
                resolve_llm_config,
            )
            from auto_ontology.text_ontology.sample import FakeLLM

            config = resolve_llm_config(store)  # type: ignore[arg-type]
            llm = FakeLLM() if fake else build_llm(config)
            built.append(
                (config, llm, "démonstration" if fake else model_label(llm, config))
            )
        return built[0]

    return source


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
