# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""CLI: extract, merge and export ontologies from text.

Usage::

    # Extract (``extract`` may be omitted); '-' or nothing reads stdin
    uv run python -m auto_ontology.text_ontology document.txt -o ontologie.json

    # Grow a project ontology, document after document
    uv run python -m auto_ontology.text_ontology extract doc1.txt --project projet.json

    # Merge existing results into one file
    uv run python -m auto_ontology.text_ontology merge a.json b.json -o projet.json

    # Export: html (interactive graph), mermaid, turtle (RDF/OWL), cypher (Neo4j)
    uv run python -m auto_ontology.text_ontology export projet.json --format html -o graphe.html

JSON and exports go to standard output unless ``-o`` is given, so they can be
piped; warnings and errors go to standard error.
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

from auto_ontology.env import load_env

# Before the extractor import: the LLM client reads its keys at import time.
load_env()

from auto_ontology.text_ontology.export import (  # noqa: E402
    DEFAULT_BASE_IRI,
    ExportFormat,
    export_ontology,
)
from auto_ontology.utils import llm_invoke  # noqa: E402
from auto_ontology.text_ontology.clean import clean_text  # noqa: E402
from auto_ontology.text_ontology.evaluation import (  # noqa: E402
    CORPUS_DIR,
    evaluate,
    evaluate_corpus,
    load_corpus,
)
from auto_ontology.text_ontology.documents import read_document_text  # noqa: E402
from auto_ontology.text_ontology.extractor import (  # noqa: E402
    DEFAULT_MAX_TOKENS,
    DEFAULT_CHUNK_CHARS,
    DEFAULT_OVERLAP_CHARS,
    TextOntologyExtractionError,
    resolve_backend,
    extract_text_ontology,
)
from auto_ontology.text_ontology.models import TextOntology  # noqa: E402
from auto_ontology.text_ontology.project import (  # noqa: E402
    dump_ontology,
    load_ontology,
    merge_ontologies,
)

_COMMANDS = ("extract", "merge", "export", "clean", "eval")
# Served by the studio's own parser (auto_ontology.text_ontology.studio): both
# entry points, `ontology` and `python -m auto_ontology.text_ontology`, accept
# every command and hand the other group over.
STUDIO_COMMANDS = ("serve", "import", "ask", "mcp", "sdk")

_EPILOG = """\
Studio commands (same entry point):
  serve    open the local studio in the browser (no database, no login)
  import   extract files into the current studio project
  ask      answer from the current project's facts, with sources
  mcp      read-only MCP server on standard input
  sdk      write a Python client for the current project's schema

`<command> --help` describes each one. Without a command, files are extracted:
`ontology document.pdf` is `ontology extract document.pdf`."""


class CliError(Exception):
    """A failure to report in one line, without a traceback."""


def _read_text(paths: list[str]) -> str:
    """The text of every input: stdin, plain text, or PDF/EPUB/DOCX/HTML."""
    texts: list[str] = []
    for path in paths:
        if path == "-":
            texts.append(sys.stdin.read())
            continue
        file = Path(path)
        text, notes = read_document_text(file.name, file.read_bytes())
        for note in notes:
            print(f"note: {file.name}: {note}", file=sys.stderr)
        texts.append(text)
    return "\n\n".join(texts)


def _read_ontology(path: str) -> TextOntology:
    if path == "-":
        return TextOntology.model_validate_json(sys.stdin.read())
    return load_ontology(path)


def _write(content: str, output: str | None) -> None:
    if output:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"written: {target}", file=sys.stderr)
    else:
        sys.stdout.write(content)


def _warn(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


def _glossary() -> list[str]:
    from auto_ontology.text_ontology.glossary import glossary_class_names

    try:
        return glossary_class_names()
    except Exception as exc:  # noqa: BLE001 - any store failure means "no glossary"
        raise CliError(
            "cannot read the Auto-Ontology glossary (is its Postgres reachable "
            f"with the POSTGRES_* settings?): {exc}"
        ) from exc


def _extract(args: argparse.Namespace) -> None:
    project = Path(args.project) if args.project else None
    base = load_ontology(project) if project and project.exists() else None
    known_classes = list(args.known_class)
    if args.glossary:
        known_classes += _glossary()
    if args.timeout is not None:
        # Read when the client is built, so setting it here is enough.
        llm_invoke.LLM_INVOKE_TIMEOUT_S = args.timeout
    backend = resolve_backend(
        provider=args.provider, model=args.model, max_tokens=args.max_tokens
    )
    print(f"model: {backend.description}", file=sys.stderr)
    result = extract_text_ontology(
        _read_text(args.inputs),
        known_classes=known_classes,
        known_predicates=args.known_predicate,
        max_chunk_chars=args.chunk_chars,
        base=base,
        max_tokens=args.max_tokens,
        skip_failed_chunks=args.skip_failed_chunks,
        clean=args.clean,
        backend=backend,
        lang=args.lang,
        overlap_chars=args.overlap_chars,
    )
    _warn(result.warnings)
    output = args.output or (str(project) if project else None)
    _write(dump_ontology(result.ontology), output)


def _eval(args: argparse.Namespace) -> None:
    import json

    if args.inputs:
        if len(args.inputs) != 2:
            raise CliError(
                "eval takes an extraction and a reference: eval found.json gold.json"
            )
        result = evaluate(
            _read_ontology(args.inputs[0]), _read_ontology(args.inputs[1])
        )
        payload: dict[str, object] = result.as_dict()
        report = result.report(f"{args.inputs[0]} comparé à {args.inputs[1]}")
    else:
        directory = Path(args.corpus) if args.corpus else CORPUS_DIR
        documents = load_corpus(directory)
        if not documents:
            raise CliError(f"no <name>.txt with a <name>.gold.json in {directory}")
        if args.timeout is not None:
            llm_invoke.LLM_INVOKE_TIMEOUT_S = args.timeout
        backend = resolve_backend(
            provider=args.provider, model=args.model, max_tokens=args.max_tokens
        )
        print(f"model: {backend.description}", file=sys.stderr)

        def run(text: str) -> TextOntology:
            return extract_text_ontology(
                text,
                backend=backend,
                lang=args.lang,
                max_chunk_chars=args.chunk_chars,
                max_tokens=args.max_tokens,
                skip_failed_chunks=True,
            ).ontology

        total, per_document = evaluate_corpus(documents, run)
        payload = {
            "model": backend.description,
            "total": total.as_dict(),
            "documents": {name: e.as_dict() for name, e in per_document.items()},
        }
        report = "\n\n".join(
            [e.report(name) for name, e in per_document.items()]
            + [total.report(f"Total ({len(per_document)} documents)")]
        )
    if args.json:
        _write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", args.output)
    else:
        _write(report + "\n", args.output)


def _clean(args: argparse.Namespace) -> None:
    result = clean_text(_read_text(args.inputs))
    print(result.summary() or "Text cleaned: nothing to remove.", file=sys.stderr)
    _write(result.text, args.output)


def _merge(args: argparse.Namespace) -> None:
    ontology, warnings = merge_ontologies(
        (_read_ontology(path) for path in args.inputs),
        known_classes=args.known_class,
    )
    _warn(warnings)
    _write(dump_ontology(ontology), args.output)


def _export(args: argparse.Namespace) -> None:
    ontology = _read_ontology(args.input)
    title = args.title or (Path(args.input).stem if args.input != "-" else "Ontologie")
    _write(
        export_ontology(
            ontology, ExportFormat(args.format), base_iri=args.base_iri, title=title
        ),
        args.output,
    )


_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ontology",
        description="Extract, merge, export and evaluate ontologies from text, "
        "or open the local studio.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=_LOG_LEVELS,
        help="INFO shows one line per chunk while extracting.",
    )
    # Accepted after the command too. SUPPRESS keeps a subcommand that was not
    # given the option from overwriting the value given before it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--log-level", default=argparse.SUPPRESS, choices=_LOG_LEVELS)
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser(
        "extract",
        parents=[common],
        help="Extract an ontology from text files (the default command).",
    )
    extract.add_argument(
        "inputs",
        nargs="*",
        default=["-"],
        help="Files to read: text, Markdown, PDF, EPUB, DOCX or HTML; '-' (the default) reads standard input.",
    )
    extract.add_argument(
        "--project",
        metavar="FILE.json",
        help="Project ontology to grow: read if it exists, then written back.",
    )
    extract.add_argument(
        "--glossary",
        action="store_true",
        help="Reuse the Auto-Ontology glossary's Terms as classes (needs its database).",
    )
    extract.add_argument(
        "--known-class",
        action="append",
        default=[],
        metavar="NAME",
        help="A class that already exists and must be reused. Repeatable.",
    )
    extract.add_argument(
        "--known-predicate",
        action="append",
        default=[],
        metavar="NAME",
        help="A relation that already exists and must be reused. Repeatable.",
    )
    extract.add_argument(
        "--chunk-chars",
        type=int,
        default=DEFAULT_CHUNK_CHARS,
        help=f"Characters of text per LLM call (default {DEFAULT_CHUNK_CHARS}).",
    )
    extract.add_argument(
        "--timeout",
        type=int,
        metavar="SECONDS",
        help="Seconds to wait for one LLM answer (default: LLM_INVOKE_TIMEOUT_S, "
        "else 120). Raise it for a slow local model.",
    )
    extract.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Longest answer per LLM call (default {DEFAULT_MAX_TOKENS}); "
        "lower it to stop a small model that loops.",
    )
    extract.add_argument(
        "--skip-failed-chunks",
        action="store_true",
        help="Skip a chunk the LLM cannot answer instead of failing; the result "
        "is then marked INCOMPLETE in the warnings.",
    )
    extract.add_argument(
        "--lang",
        default="auto",
        help="Language of class, relation and attribute names: auto (the "
        "project's, else the text's), fr, en, or another code.",
    )
    extract.add_argument(
        "--overlap-chars",
        type=int,
        default=DEFAULT_OVERLAP_CHARS,
        help=f"End of the previous chunk restated as context (default "
        f"{DEFAULT_OVERLAP_CHARS}; 0 turns it off).",
    )
    extract.add_argument(
        "--clean",
        action="store_true",
        help="Drop PDF noise first (diagram labels, code, formulas, page numbers, "
        "references) and rejoin wrapped lines. Preview it with the clean command.",
    )
    extract.add_argument(
        "--provider",
        choices=["auto", "local", "hosted"],
        default="auto",
        help="local: an OpenAI-compatible server such as LM Studio, any model; "
        "hosted: the application's client. auto picks local for a server on this "
        "machine or the private network.",
    )
    extract.add_argument(
        "--model",
        help="Model to use instead of REASONING_MODEL; 'auto' uses the model the "
        "local server has loaded.",
    )
    extract.add_argument("--output", "-o", help="Write the JSON here.")
    extract.set_defaults(handler=_extract)

    evaluation = commands.add_parser(
        "eval",
        parents=[common],
        help="Score an extraction against a reference written by hand.",
        description="Either compare two ontology files (eval found.json "
        "gold.json), or run the model on a corpus of <name>.txt files with "
        "<name>.gold.json references (eval --corpus [DIR]; the bundled corpus "
        "by default) and report precision, recall and F1 per kind of fact.",
    )
    evaluation.add_argument(
        "inputs", nargs="*", help="An extraction and its reference, both JSON."
    )
    evaluation.add_argument(
        "--corpus",
        nargs="?",
        const="",
        default=None,
        metavar="DIR",
        help="Extract each corpus text and score it (default: the bundled corpus).",
    )
    evaluation.add_argument("--lang", default="auto", help="As for extract.")
    evaluation.add_argument(
        "--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS, help="As for extract."
    )
    evaluation.add_argument(
        "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, help="As for extract."
    )
    evaluation.add_argument(
        "--timeout", type=int, metavar="SECONDS", help="As for extract."
    )
    evaluation.add_argument(
        "--provider", choices=["auto", "local", "hosted"], default="auto"
    )
    evaluation.add_argument("--model", help="As for extract.")
    evaluation.add_argument(
        "--json", action="store_true", help="Print the scores as JSON."
    )
    evaluation.add_argument("--output", "-o", help="Write the report here.")
    evaluation.set_defaults(handler=_eval)

    clean = commands.add_parser(
        "clean",
        parents=[common],
        help="Show the text --clean would extract from, without calling a model.",
    )
    clean.add_argument(
        "inputs",
        nargs="*",
        default=["-"],
        help="Files to read: text, Markdown, PDF, EPUB, DOCX or HTML; '-' (the default) reads standard input.",
    )
    clean.add_argument("--output", "-o", help="Write the cleaned text here.")
    clean.set_defaults(handler=_clean)

    merge = commands.add_parser(
        "merge", parents=[common], help="Merge ontology files into one."
    )
    merge.add_argument("inputs", nargs="+", help="Ontology files, earliest first.")
    merge.add_argument(
        "--known-class",
        action="append",
        default=[],
        metavar="NAME",
        help="A class name to reconcile duplicates onto. Repeatable.",
    )
    merge.add_argument("--output", "-o", help="Write the merged JSON here.")
    merge.set_defaults(handler=_merge)

    export = commands.add_parser(
        "export", parents=[common], help="Export an ontology file."
    )
    export.add_argument("input", help="Ontology file; '-' reads standard input.")
    export.add_argument(
        "--format",
        "-f",
        required=True,
        choices=[f.value for f in ExportFormat],
        help="html: interactive graph; mermaid; turtle: RDF/OWL; cypher: Neo4j.",
    )
    export.add_argument(
        "--base-iri",
        default=DEFAULT_BASE_IRI,
        help=f"Namespace of the RDF/OWL export (default {DEFAULT_BASE_IRI}).",
    )
    export.add_argument("--title", help="Title of the HTML page.")
    export.add_argument("--output", "-o", help="Write the export here.")
    export.set_defaults(handler=_export)

    return parser


def first_command(args: list[str]) -> str | None:
    """The command *args* name, past the global options, if any."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--log-level":
            index += 2
        elif arg.startswith("--log-level=") or arg in ("-h", "--help"):
            index += 1
        else:
            return arg
    return None


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if first_command(raw) in STUDIO_COMMANDS:
        from auto_ontology.text_ontology.studio import main as studio_main

        return studio_main(raw)
    if not raw and sys.stdin.isatty():
        # Nothing to read: a bare command at a terminal shows what it can do
        # instead of waiting silently on standard input.
        _parser().print_help()
        return 0
    args = _with_default_command(raw)
    parsed = _parser().parse_args(args)
    _configure_output(parsed.log_level)
    try:
        parsed.handler(parsed)
    except (CliError, ValueError, OSError, TextOntologyExtractionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


class _NoTraceback(logging.Filter):
    """Keep a logged error to its one-line message; DEBUG shows the trace."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.exc_info = None
        record.exc_text = None
        return True


def _configure_output(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level),
        stream=sys.stderr,
        format="%(levelname)s: %(message)s",
    )
    if log_level != "DEBUG":
        # One line per HTTP request is transport detail, not progress.
        for name in ("httpx", "httpcore", "openai"):
            logging.getLogger(name).setLevel(logging.WARNING)
        for handler in logging.getLogger().handlers:
            handler.addFilter(_NoTraceback())
        # Printed once per chunk for any model the NVIDIA client does not list,
        # local ones included, while the answer is validated anyway.
        warnings.filterwarnings(
            "ignore", message=r".*is not known to support structured output.*"
        )


def _with_default_command(args: list[str]) -> list[str]:
    """*args* with ``extract`` inserted when no command is named.

    ``extract`` is the default, so the original form keeps working:
    ``python -m auto_ontology.text_ontology document.txt``. It goes after the
    global options, where argparse expects a command.
    """
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--log-level":
            index += 2
        elif arg.startswith("--log-level=") or arg in ("-h", "--help"):
            index += 1
        else:
            break
    if index < len(args) and args[index] in _COMMANDS:
        return args
    if index >= len(args) and any(a in ("-h", "--help") for a in args):
        return args  # top-level help lists the commands
    return [*args[:index], "extract", *args[index:]]


if __name__ == "__main__":
    sys.exit(main())
