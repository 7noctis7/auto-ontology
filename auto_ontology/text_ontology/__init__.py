# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ontology extraction from free text: classes, triplets and literal attributes.

Unlike :mod:`auto_ontology.semantic`, which compiles a semantic layer from
database tables, this package reads unstructured text (documents, notes,
specifications) and returns a formal ontology under the rules of
``prompts/system_prompt.txt``. Nothing is written to the store.
"""
