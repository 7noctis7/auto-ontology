# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for cleaning PDF text before extraction."""

from __future__ import annotations

from auto_ontology.text_ontology.clean import clean_text

# Shaped like text copied from a PDF: lines cut at the page width, a diagram,
# code, a formula, page numbers, citation markers and a reference list.
_PDF_TEXT = """\
Bitcoin: A Peer-to-Peer Electronic Cash System
Satoshi Nakamoto
satoshin@gmx.com
Abstract. A purely peer-to-peer version of electronic cash would allow online
payments to be sent directly from one party to another without going through a
financial institution. Digital signatures provide part of the solution, but the
main benefits are lost if a trusted third party is still required.
7. Reclaiming Disk Space
Once the latest transaction in a coin is buried under enough blocks, the spent
transactions before it can be discarded to save disk space. Transactions are
hashed in a Merkle Tree [7][2][5], with only the root included in the block's hash.
Block Header (Block Hash)
Prev Hash Nonce
Root Hash
Hash01
Tx0 Tx1 Tx2 Tx3
4
qz = probability the attacker will ever catch up from z blocks behind
={1 if p≤q
z=0 P=1.0000000
#include <math.h>
double AttackerSuccessProbability(double q, int z)
{
double p = 1.0 - q;
return sum;
}
12. Conclusion
We have proposed a system for electronic transactions without relying on trust,
using a peer-to-peer network and proof-of-work to record a public history.
References
W. Dai, "b-money," http://www.weidai.com/bmoney.txt, 1998.
A. Back, "Hashcash - a denial of service counter-measure," 2002.
"""


def test_noise_is_removed_and_prose_kept() -> None:
    result = clean_text(_PDF_TEXT)
    text = result.text

    for noise in (
        "Prev Hash Nonce",
        "Hash01",
        "#include",
        "AttackerSuccessProbability",
        "return sum",
        "P=1.0000000",
        "p≤q",
        "[7]",
        "b-money",
        "Hashcash",
    ):
        assert noise not in text, noise
    for prose in (
        "Satoshi Nakamoto",
        "satoshin@gmx.com",
        "hashed in a Merkle Tree, with only the root included",
        "qz = probability the attacker will ever catch up",
        "We have proposed a system for electronic transactions",
    ):
        assert prose in text, prose


def test_wrapped_lines_become_paragraphs() -> None:
    paragraphs = clean_text(_PDF_TEXT).text.split("\n\n")

    assert "Bitcoin: A Peer-to-Peer Electronic Cash System" in paragraphs
    assert "7. Reclaiming Disk Space" in paragraphs
    abstract = next(p for p in paragraphs if p.startswith("Abstract."))
    assert "\n" not in abstract
    assert "online payments to be sent" in abstract
    assert abstract.endswith("is still required.")


def test_hyphenated_compounds_are_rejoined_without_a_space() -> None:
    text = (
        "Lorem ipsum dolor sit amet, the network uses hash-based proof-\n"
        "of-work to record a public history of transactions every day.\n"
    )

    assert "proof-of-work" in clean_text(text).text


def test_the_summary_counts_each_kind_of_removal() -> None:
    summary = clean_text(_PDF_TEXT).summary()

    assert summary is not None
    assert summary.startswith("Text cleaned: removed ")
    for kind in ("code line", "formula line", "diagram-label line", "citation marker"):
        assert kind in summary


def test_clean_prose_is_left_alone() -> None:
    text = "Alice works for ACME.\n\nACME was founded in 1993 in Paris.\n"

    result = clean_text(text)

    assert result.text == text
    assert result.summary() is None
