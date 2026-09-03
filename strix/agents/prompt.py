"""Jinja-based system-prompt renderer."""

from __future__ import annotations

import logging
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from strix.config import load_settings
from strix.skills import get_available_skills, load_skills, skill_search_dirs
from strix.utils.resource_paths import get_strix_resource_path


logger = logging.getLogger(__name__)


_PROMPT_DIRNAME = "prompts"


_CAVEMAN_INTENSITY = {
    "lite": "Trim obvious filler and hedging. Keep sentences, but shorter.",
    "full": (
        "Drop articles (a/an/the), filler (just/really/basically/actually/simply), "
        "pleasantries, and hedging. Sentence fragments are fine."
    ),
    "ultra": (
        "Drop articles (a/an/the), filler (just/really/basically/actually/simply), "
        "pleasantries, and hedging. Use terse fragments. Prefer short words "
        "(big not extensive, fix not implement-a-solution-for). Maximum compression."
    ),
}


def _caveman_block(mode: str) -> str:
    """System-prompt block that makes an agent emit token-frugal 'caveman' prose.

    Injected into every agent's system prompt (root and every spawned sub-agent),
    so brevity is inherited across the whole graph. Compression is applied to
    narration/reasoning ONLY; payloads, code, and report fields stay verbatim so
    finding accuracy is never traded for token savings.
    """
    intensity = _CAVEMAN_INTENSITY.get(mode, _CAVEMAN_INTENSITY["ultra"])
    return (
        '\n\n<output_style name="caveman-' + mode + '">\n'
        "TOKEN-FRUGAL OUTPUT MODE. This applies to you AND is inherited by every "
        "sub-agent you spawn with create_agent.\n\n"
        "Style for all prose, reasoning, notes, todos, and inter-agent messages:\n"
        f"{intensity}\n\n"
        "Keep ALL technical substance exact and complete. NEVER compress, "
        "abbreviate, paraphrase, or drop any of the following — emit them verbatim "
        "and in full:\n"
        "- Tool-call arguments and any JSON you output.\n"
        "- URLs, endpoints, parameters, payloads, headers, tokens, credentials, "
        "hashes, file paths, and software versions.\n"
        "- Code, shell commands, regexes, and exact error messages.\n"
        "- Vulnerability report fields (create_vulnerability_report / "
        "create_dependency_report): title, description, reproduction steps, "
        "evidence, impact, and remediation stay full and precise.\n\n"
        "Brevity applies to narration only, never to the security signal. When in "
        "doubt, keep the detail.\n"
        "</output_style>"
    )


def _resolve_skills(
    *,
    requested: list[str] | None,
    scan_mode: str = "deep",
    is_whitebox: bool = False,
    is_root: bool = False,
    is_diff_scoped: bool = False,
) -> list[str]:
    """Build the deduped, ordered skills list for the prompt render.

    Order:

    1. Whatever the caller asked for, in order.
    2. ``scan_modes/<mode>`` (always), plus ``scan_modes/diff`` when the
       run is scoped to a change set — diff scope overlays the depth
       mode rather than replacing it.
    3. ``tooling/agent_browser`` (always — every agent has shell + the
       agent-browser CLI).
    4. ``tooling/python`` (always — Python runs through ``exec_command``;
       sandbox scripts can import ``caido_api`` for Caido automation).
    5. ``analysis/counterevidence`` and ``analysis/severity_calibration``
       (always — closure discipline and severity rubric apply to every
       agent that can open or close a candidate, or file a report).
    6. ``coordination/root_agent`` for the root agent only — orchestration
       guidance for delegating to specialist subagents.
    7. Whitebox-specific skills if applicable, including
       ``analysis/fix_verification`` (only whitebox agents can attach an
       applyable ``fix_after``) and ``analysis/source_aware_discovery``.
    """
    ordered: list[str] = list(requested or [])
    ordered.append(f"scan_modes/{scan_mode}")
    if is_diff_scoped:
        ordered.append("scan_modes/diff")
    ordered.append("tooling/agent_browser")
    ordered.append("tooling/python")
    ordered.append("analysis/counterevidence")
    ordered.append("analysis/severity_calibration")
    if is_root:
        ordered.append("coordination/root_agent")
    if is_whitebox:
        ordered.append("coordination/source_aware_whitebox")
        ordered.append("custom/source_aware_sast")
        ordered.append("analysis/source_aware_discovery")
        ordered.append("analysis/fix_verification")

    deduped: list[str] = []
    seen: set[str] = set()
    for skill in ordered:
        if skill and skill not in seen:
            deduped.append(skill)
            seen.add(skill)
    return deduped


def render_system_prompt(
    *,
    skills: list[str] | None = None,
    scan_mode: str = "deep",
    is_whitebox: bool = False,
    is_root: bool = False,
    is_diff_scoped: bool = False,
    interactive: bool = False,
    system_prompt_context: dict[str, Any] | None = None,
) -> str:
    """Render the system prompt. Returns empty string on template failure."""
    try:
        prompt_dir = get_strix_resource_path("agents", _PROMPT_DIRNAME)
        loader_dirs = [prompt_dir, *skill_search_dirs()]
        env = Environment(
            loader=FileSystemLoader(loader_dirs),
            autoescape=select_autoescape(
                enabled_extensions=(),
                default_for_string=False,
            ),
        )

        skills_to_load = _resolve_skills(
            requested=skills,
            scan_mode=scan_mode,
            is_whitebox=is_whitebox,
            is_root=is_root,
            is_diff_scoped=is_diff_scoped,
        )
        skill_content = load_skills(skills_to_load)
        env.globals["get_skill"] = lambda name: skill_content.get(name, "")

        rendered = env.get_template("system_prompt.jinja").render(
            loaded_skill_names=list(skill_content.keys()),
            available_skills=get_available_skills(),
            interactive=interactive,
            is_root=is_root,
            system_prompt_context=system_prompt_context or {},
            **skill_content,
        )
        caveman_mode = load_settings().output_style.caveman
        if caveman_mode != "off":
            rendered = f"{rendered}{_caveman_block(caveman_mode)}"
    except Exception:
        logger.exception("render_system_prompt failed; returning empty prompt")
        return ""
    else:
        logger.debug(
            "render_system_prompt: scan_mode=%s root=%s whitebox=%s skills=%d prompt_len=%d",
            scan_mode,
            is_root,
            is_whitebox,
            len(skill_content),
            len(rendered),
        )
        return str(rendered)
