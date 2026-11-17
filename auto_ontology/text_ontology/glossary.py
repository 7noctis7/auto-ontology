# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The Auto-Ontology glossary as classes to reuse in a text extraction.

The glossary is built from the connected databases (see
:mod:`auto_ontology.semantic`). Feeding its Term names to the extractor as
known classes means a document that talks about "orders" lands on the
glossary's ``PurchaseOrder`` class instead of inventing a second one, which is
rule 1 applied across the whole platform. Nothing is written to the store.
"""

from __future__ import annotations

from auto_ontology.text_ontology.normalize import to_pascal_case


def glossary_class_names() -> list[str]:
    """Every glossary Term name, as a PascalCase class name, in glossary order.

    Reads the store, so it needs the Postgres settings the server uses.
    """
    # Imported here: the CLI works without a database unless asked for this.
    from auto_ontology.dal.terms import fetch_all_terms

    names = (to_pascal_case(row.get("name") or "") for row in fetch_all_terms())
    return list(dict.fromkeys(name for name in names if name))
