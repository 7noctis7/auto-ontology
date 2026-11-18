# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A small ontology shipped with the app, so the graph can be opened offline.

The text and the triples describe the same municipal library. Loading the
sample does not call a model. The fake extractor used by ``--fake`` and by
the tests returns this ontology when the text mentions the library, so a
PDF and an EPUB of the same passage produce the same graph.
"""

from __future__ import annotations

from auto_ontology.text_ontology.models import (
    OntologyAttribute,
    OntologyClass,
    OntologyTriplet,
    TextOntology,
)

SAMPLE_TEXT = """La bibliothèque municipale de Lyon est une organisation publique.
Camille Martin, bibliothécaire, la dirige depuis 2016.
Elle conserve le livre « Notes sur la machine analytique », écrit par Ada Lovelace en 1843.
Ada Lovelace est une mathématicienne.
Charles Babbage a conçu la machine analytique, une machine mécanique.
La bibliothèque municipale de Lyon est située à Lyon, une ville de France.
L'index des périodiques date de 1998.
"""

SAMPLE_MODEL = "exemple"


def sample_ontology() -> TextOntology:
    """The curated ontology, already in the shape the normalizer expects."""
    classes = [
        OntologyClass(
            name="Organisation",
            description="Structure qui rassemble des personnes autour d'une mission.",
        ),
        OntologyClass(
            name="Bibliotheque",
            parent="Organisation",
            description="Organisation qui conserve et prête des documents.",
        ),
        OntologyClass(name="Personne", description="Un être humain."),
        OntologyClass(
            name="Bibliothecaire",
            parent="Personne",
            description="Personne qui fait fonctionner une bibliothèque.",
        ),
        OntologyClass(
            name="Mathematicien",
            parent="Personne",
            description="Personne qui pratique les mathématiques.",
        ),
        OntologyClass(name="Document", description="Un écrit conservé."),
        OntologyClass(
            name="Livre",
            parent="Document",
            description="Document publié, assez long pour faire un volume.",
        ),
        OntologyClass(name="Lieu", description="Un endroit."),
        OntologyClass(name="Ville", parent="Lieu", description="Un lieu habité."),
        OntologyClass(
            name="Pays", parent="Lieu", description="Un territoire politique."
        ),
        OntologyClass(name="Machine", description="Un appareil conçu pour une tâche."),
    ]
    triplets = [
        OntologyTriplet(
            subject="Bibliothèque municipale de Lyon",
            subject_type="Bibliotheque",
            predicate="est_dirigee_par",
            object="Camille Martin",
            object_type="Bibliothecaire",
        ),
        OntologyTriplet(
            subject="Ada Lovelace",
            subject_type="Mathematicien",
            predicate="a_ecrit",
            object="Notes sur la machine analytique",
            object_type="Livre",
        ),
        OntologyTriplet(
            subject="Charles Babbage",
            subject_type="Personne",
            predicate="a_concu",
            object="Machine analytique",
            object_type="Machine",
        ),
        OntologyTriplet(
            subject="Bibliothèque municipale de Lyon",
            subject_type="Bibliotheque",
            predicate="est_situee_a",
            object="Lyon",
            object_type="Ville",
        ),
        OntologyTriplet(
            subject="Lyon",
            subject_type="Ville",
            predicate="se_trouve_dans",
            object="France",
            object_type="Pays",
        ),
        OntologyTriplet(
            subject="Index des périodiques",
            subject_type="Document",
            predicate="est_un",
            object="Document",
            object_type="Document",
        ),
    ]
    attributes = [
        OntologyAttribute(entity="Camille Martin", key="annee_debut", value="2016"),
        OntologyAttribute(
            entity="Notes sur la machine analytique", key="annee", value="1843"
        ),
        OntologyAttribute(entity="Index des périodiques", key="annee", value="1998"),
    ]
    return TextOntology(classes=classes, triplets=triplets, attributes=attributes)


class FakeLLM:
    """A stand-in model for tests and ``ontology serve --fake``.

    It never touches the network. A text that mentions the sample library
    yields the sample ontology; any other non-empty text yields one class
    and one entity taken from its first line, so the graph is never blank.
    """

    model_name = "demo"

    def with_structured_output(self, schema: type, **_: object) -> FakeLLM:
        return self

    def invoke(self, messages: list[object]) -> TextOntology:
        text = _message_text(messages)
        if "Camille Martin" in text or "bibliothèque municipale" in text.casefold():
            return sample_ontology()
        return _minimal(text)


def _message_text(messages: list[object]) -> str:
    parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _minimal(text: str) -> TextOntology:
    line = " ".join(text.split())
    start = line.find("<texte_source>")
    end = line.find("</texte_source>")
    if start >= 0 and end > start:
        line = line[start + len("<texte_source>") : end]
    line = " ".join(line.split())[:80] or "Texte"
    return TextOntology(
        classes=[
            OntologyClass(name="Document", description="Texte déposé dans le projet.")
        ],
        triplets=[
            OntologyTriplet(
                subject=line[:48],
                subject_type="Document",
                predicate="est_un",
                object="Document",
                object_type="Document",
            )
        ],
    )
