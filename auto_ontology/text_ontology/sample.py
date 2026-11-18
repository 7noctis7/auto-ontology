# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A small ontology shipped with the app, so the graph can be opened offline.

The text and the triples describe the same municipal library. Loading the
sample does not call a model. The fake extractor used by ``--fake`` and by
the tests returns this ontology when the text mentions the library. Any other
text is read with a deterministic heuristic, so two documents do not produce
the same graph.
"""

from __future__ import annotations

import json
import re

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
    yields the sample ontology. Any other text yields a small ontology built
    from names, titles and a few French patterns in that text alone.
    """

    model_name = "demo"

    def with_structured_output(self, schema: type, **_: object) -> FakeLLM:
        return self

    def complete(self, system: str, user: str) -> str:
        """Free-text answers for questions on the data, without a model.

        The demo query lists the table (or the facts) the question names
        best; the demo answer only counts the rows.
        """
        if '{"answer"' in system:
            rows = re.search(r'"rows": (\[.*\])\}\s*$', user, re.DOTALL)
            count = len(json.loads(rows.group(1))) if rows else 0
            return json.dumps(
                {"answer": f"{count} ligne(s) trouvée(s) (démonstration)."}
            )
        tables = re.findall(r"^(?:Table|Vue) (\w+) ", user, re.MULTILINE)
        question = user.rsplit("Question:", 1)[-1].casefold()
        chosen = next(
            (t for t in tables if t.replace("_", " ") in question or t in question),
            tables[0] if tables else "onto_facts",
        )
        return json.dumps(
            {"sql": f"SELECT * FROM {chosen} LIMIT 20", "explanation": "démonstration"}
        )

    def invoke(self, messages: list[object]) -> TextOntology:
        text = _message_text(messages)
        if "Camille Martin" in text or "bibliothèque municipale" in text.casefold():
            return sample_ontology()
        built = _heuristic(text)
        return built if built.triplets or built.classes else _minimal(text)


def _message_text(messages: list[object]) -> str:
    parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


_PERSON = re.compile(
    r"\b([A-ZÉÈÀÂÊÎÔÛÇ][a-zà-ÿ'’-]{2,}(?:\s+[A-ZÉÈÀÂÊÎÔÛÇ][a-zà-ÿ'’-]{2,})+)\b"
)
_QUOTE = re.compile(r"«\s*([^»]{3,80})\s*»")


def _source_slice(text: str) -> str:
    start = text.find("<texte_source>")
    end = text.find("</texte_source>")
    if start >= 0 and end > start:
        return text[start + len("<texte_source>") : end]
    return text


def _heuristic(text: str) -> TextOntology:
    """Names and a few patterns. The same text always yields the same triples."""
    source = _source_slice(text).strip()
    if not source:
        return TextOntology()
    folded = source.casefold()
    people = list(dict.fromkeys(_PERSON.findall(source)))[:4]
    quoted = list(dict.fromkeys(_QUOTE.findall(source)))[:2]
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    title = ""
    for line in lines:
        if re.match(r"(?i)^(de|from|objet|subject)\s*:", line):
            if line.casefold().startswith(("objet", "subject")):
                title = line.split(":", 1)[-1].strip()
            continue
        if 8 <= len(line) <= 90:
            title = title or line
            break
    classes = [
        OntologyClass(name="Document", description="Un écrit cité dans le texte."),
        OntologyClass(
            name="Personne", description="Une personne nommée dans le texte."
        ),
    ]
    triplets: list[OntologyTriplet] = []
    attributes: list[OntologyAttribute] = []
    if "contrat" in folded or "clause" in folded:
        classes.append(OntologyClass(name="Clause", description="Une stipulation."))
    if "abstract" in folded or "hypothèse" in folded or "hypothese" in folded:
        classes.append(
            OntologyClass(name="Hypothese", description="Une proposition à examiner.")
        )
    document = quoted[0] if quoted else (title[:72] if title else "")
    if document and people:
        triplets.append(
            OntologyTriplet(
                subject=document,
                subject_type="Document",
                predicate="a_pour_auteur",
                object=people[0],
                object_type="Personne",
            )
        )
    elif document:
        kind = (
            "Hypothese"
            if any(item.name == "Hypothese" for item in classes)
            else "Document"
        )
        triplets.append(
            OntologyTriplet(
                subject=document,
                subject_type=kind,
                predicate="est_mentionne_dans",
                object=lines[0][:48],
                object_type="Document",
            )
        )
    elif people:
        triplets.append(
            OntologyTriplet(
                subject=people[0],
                subject_type="Personne",
                predicate="est_cite_dans",
                object=(title or "Texte")[:48],
                object_type="Document",
            )
        )
    for person in people[1:3]:
        triplets.append(
            OntologyTriplet(
                subject=person,
                subject_type="Personne",
                predicate="est_cite_avec",
                object=people[0],
                object_type="Personne",
            )
        )
    if "clause" in folded and document:
        attributes.append(
            OntologyAttribute(entity=document, key="nature", value="clause")
        )
    return TextOntology(classes=classes, triplets=triplets, attributes=attributes)


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
