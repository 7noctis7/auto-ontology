# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Keep the developer's own studio settings out of these tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_studio_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Model resolution reads ~/AutoOntology/settings.json and ONTOLOGY_LLM_*."""
    monkeypatch.setenv("ONTOLOGY_HOME", str(tmp_path / "studio-home"))
    for name in (
        "ONTOLOGY_LLM_API_KEY",
        "ONTOLOGY_LLM_ENDPOINT",
        "ONTOLOGY_LLM_MODEL",
        "ONTOLOGY_LLM_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
