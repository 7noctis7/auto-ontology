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
) -> None:
    """Bind the studio and, unless asked not to, open it in the browser."""
    import uvicorn

    from auto_ontology.text_ontology.app.server import create_app

    root = Path(home) if home is not None else default_home()
    chosen = port if port is not None else int(os.environ.get("ONTOLOGY_PORT", "4173"))
    url = f"http://{host}:{chosen}/"
    print(f"Ontologie — {url}")
    print(f"Projets — {root}")
    if fake:
        print("Mode démonstration : aucun modèle n'est appelé.")
    elif host not in {"127.0.0.1", "localhost", "::1"}:
        print("Attention : l'application n'a pas de connexion. Ne l'exposez pas.")
    print("Arrêt : Ctrl+C")
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        create_app(home=root, fake=fake),
        host=host,
        port=chosen,
        log_level="info",
    )


def main(argv: list[str] | None = None) -> int:
    """``ontology serve``."""
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
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "serve":
        serve(
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
            home=Path(args.home) if args.home else None,
            fake=args.fake,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
