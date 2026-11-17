# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Document type, domain and metadata from the text alone."""

from __future__ import annotations

from auto_ontology.text_ontology.profile import profile_text


def test_contract_paper_and_email_are_distinct() -> None:
    contract = profile_text(
        "Contrat de prestation.\nLes parties conviennent de la clause suivante.\n"
        "Article 1. Confidentialité.\nAuteur: Jeanne Martin\n",
        filename="contrat.txt",
    )
    paper = profile_text(
        "Abstract\nCette étude pose une hypothèse.\nDOI: 10.1000/xyz\nMots-clés : graphe\n",
        filename="article.txt",
    )
    mail = profile_text(
        "De : ada@example.test\nObjet : compte rendu\n"
        "Les notes sont dans ce message pour l'équipe.\nCordialement\n",
        filename="message.txt",
    )

    assert contract.genre == "contract"
    assert contract.author == "Jeanne Martin"
    assert contract.domain == "droit"
    assert contract.genre_confidence >= 0.5
    assert paper.genre == "scientific_paper"
    assert paper.domain == "science"
    assert mail.genre == "email"
    assert mail.language == "fr"
    assert {contract.genre, paper.genre, mail.genre} == {
        "contract",
        "scientific_paper",
        "email",
    }


def test_short_note_stays_a_note() -> None:
    profile = profile_text("Pense-bête\nRappeler Lyon demain.", filename="note.txt")

    assert profile.genre == "notes"
    assert profile.title
    assert profile.pages >= 1
