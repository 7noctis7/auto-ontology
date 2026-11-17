# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""CLI: extract an ontology from text files and print it as JSON.

Usage::

    uv run python -m auto_ontology.text_ontology document.txt [autre.md ...]
    cat document.txt | uv run python -m auto_ontology.text_ontology -

Standard output carries only the JSON object (``classes`` / ``triplets`` /
``attributes``), so it can be piped; repairs made by normalization go to
standard error.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from auto_ontology.env import load_env

# Before the extractor import: the LLM client reads its keys at import time.
load_env()

from auto_ontology.text_ontology.extractor import (  # noqa: E402
    DEFAULT_CHUNK_CHARS,
    TextOntologyExtractionError,
    extract_text_ontology,
)


def _read_inputs(paths: list[str]) -> str:
    texts = [
        sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        for path in paths
    ]
    return "\n\n".join(texts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m auto_ontology.text_ontology",
        description="Extract classes, triplets and attributes from text.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=["-"],
        help="Text files to read; '-' (the default) reads standard input.",
    )
    parser.add_argument(
        "--known-class",
        action="append",
        default=[],
        metavar="NAME",
        help="A class that already exists and must be reused. Repeatable.",
    )
    parser.add_argument(
        "--known-predicate",
        action="append",
        default=[],
        metavar="NAME",
        help="A relation that already exists and must be reused. Repeatable.",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=DEFAULT_CHUNK_CHARS,
        help=f"Characters of text per LLM call (default {DEFAULT_CHUNK_CHARS}).",
    )
    parser.add_argument(
        "--output", "-o", help="Write the JSON here instead of standard output."
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), stream=sys.stderr)

    try:
        result = extract_text_ontology(
            _read_inputs(args.inputs),
            known_classes=args.known_class,
            known_predicates=args.known_predicate,
            max_chunk_chars=args.chunk_chars,
        )
    except (ValueError, OSError, TextOntologyExtractionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    payload = json.dumps(result.ontology.model_dump(), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
