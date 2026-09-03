"""Tests for caveman output-style injection in the system prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from strix.config import loader
from strix.agents.prompt import render_system_prompt


if TYPE_CHECKING:
    import pytest


_MARKER = '<output_style name="caveman-'


def _render(mode: str, *, is_root: bool) -> str:
    loader._cached = None
    try:
        return render_system_prompt(is_root=is_root, scan_mode="quick")
    finally:
        loader._cached = None


def test_caveman_injected_for_root_and_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIX_CAVEMAN", "ultra")
    for is_root in (True, False):
        prompt = _render("ultra", is_root=is_root)
        assert f"{_MARKER}ultra" in prompt
        # Report fields must be named as never-compress, after the marker.
        tail = prompt.split("<output_style")[-1]
        assert "create_vulnerability_report" in tail


def test_caveman_off_disables_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIX_CAVEMAN", "off")
    assert _MARKER not in _render("off", is_root=True)


def test_caveman_level_reflected_in_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIX_CAVEMAN", "full")
    assert f"{_MARKER}full" in _render("full", is_root=True)
