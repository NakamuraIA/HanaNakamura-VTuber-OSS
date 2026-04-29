"""
Character reference registry for image generation.

This layer keeps visual identity data outside prompts so Hana can generate
herself, or another registered character, with stable reference images.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


DEFAULT_CHARACTER_ROOT = os.path.abspath(os.path.join("data", "characters"))
DEFAULT_CHARACTER_ID = "hana"


@dataclass(frozen=True)
class CharacterProfile:
    character_id: str
    display_name: str
    root_dir: str
    identity_prompt: str
    negative_prompt: str
    default_references: tuple[str, ...]
    reference_images: dict[str, str]


@dataclass(frozen=True)
class CharacterImageRequest:
    character_id: str
    prompt: str
    mode: str
    references: tuple[str, ...]
    preserve_identity: bool
    source_image: str
    negative_prompt: str
    profile: CharacterProfile


def _safe_character_id(value: str) -> str:
    character_id = re.sub(r"[^a-z0-9_-]+", "_", str(value or "").strip().lower()).strip("_")
    if not character_id:
        character_id = DEFAULT_CHARACTER_ID
    if character_id in {".", ".."}:
        raise ValueError("ID de personagem invalido.")
    return character_id


def _coerce_string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _load_payload(raw_payload: str | dict[str, Any]) -> tuple[dict[str, Any], str]:
    if isinstance(raw_payload, dict):
        return dict(raw_payload), ""

    text = str(raw_payload or "").strip()
    if not text:
        return {}, ""

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"prompt": text}, text

    if not isinstance(parsed, dict):
        return {"prompt": text}, text
    return parsed, text


def load_character_profile(character_id: str = DEFAULT_CHARACTER_ID, *, root_dir: str = DEFAULT_CHARACTER_ROOT) -> CharacterProfile:
    safe_id = _safe_character_id(character_id)
    profile_dir = os.path.abspath(os.path.join(root_dir, safe_id))
    profile_path = os.path.join(profile_dir, "character.json")
    if not os.path.exists(profile_path):
        raise FileNotFoundError(f"Personagem visual nao cadastrado: {safe_id}")

    with open(profile_path, "r", encoding="utf-8-sig") as file:
        data = json.load(file)

    refs = data.get("reference_images") or {}
    if not isinstance(refs, dict):
        refs = {}

    return CharacterProfile(
        character_id=safe_id,
        display_name=str(data.get("display_name") or safe_id).strip(),
        root_dir=profile_dir,
        identity_prompt=str(data.get("identity_prompt") or "").strip(),
        negative_prompt=str(data.get("negative_prompt") or "").strip(),
        default_references=_coerce_string_list(data.get("default_references")),
        reference_images={str(key).strip(): str(value).strip() for key, value in refs.items() if str(key).strip() and str(value).strip()},
    )


def parse_character_image_request(
    raw_payload: str | dict[str, Any],
    *,
    default_character_id: str = DEFAULT_CHARACTER_ID,
    root_dir: str = DEFAULT_CHARACTER_ROOT,
) -> CharacterImageRequest:
    payload, raw_text = _load_payload(raw_payload)
    character_id = _safe_character_id(
        payload.get("character")
        or payload.get("character_id")
        or payload.get("personagem")
        or payload.get("personagem_id")
        or default_character_id
    )
    profile = load_character_profile(character_id, root_dir=root_dir)

    prompt = str(
        payload.get("prompt")
        or payload.get("description")
        or payload.get("descricao")
        or payload.get("instruction")
        or raw_text
        or ""
    ).strip()
    if not prompt:
        raise ValueError("A tag de imagem com personagem precisa de um campo 'prompt'.")

    references = _coerce_string_list(
        payload.get("references")
        or payload.get("reference_images")
        or payload.get("use_references")
        or payload.get("refs")
        or payload.get("referencias")
    )
    if not references:
        references = profile.default_references

    preserve_identity = payload.get("preserve_identity", payload.get("manter_identidade", True))
    if isinstance(preserve_identity, str):
        preserve_identity = preserve_identity.strip().lower() not in {"false", "0", "nao", "no"}

    return CharacterImageRequest(
        character_id=character_id,
        prompt=prompt,
        mode=str(payload.get("mode") or payload.get("modo") or "scene").strip() or "scene",
        references=tuple(references),
        preserve_identity=bool(preserve_identity),
        source_image=str(payload.get("source_image") or payload.get("image_path") or payload.get("imagem_base") or "").strip(),
        negative_prompt=str(payload.get("negative_prompt") or payload.get("avoid") or payload.get("evitar") or "").strip(),
        profile=profile,
    )


def resolve_reference_paths(profile: CharacterProfile, requested_refs: tuple[str, ...] | list[str] | None = None) -> list[str]:
    requested = tuple(requested_refs or profile.default_references)
    resolved: list[str] = []
    seen: set[str] = set()

    for ref in requested:
        raw_ref = str(ref or "").strip()
        if not raw_ref:
            continue

        configured = profile.reference_images.get(raw_ref, raw_ref)
        path = configured
        if not os.path.isabs(path):
            path = os.path.abspath(os.path.join(profile.root_dir, path))
        else:
            path = os.path.abspath(path)

        if os.path.exists(path) and path.lower() not in seen:
            resolved.append(path)
            seen.add(path.lower())

    return resolved


def resolve_source_image_path(source_image: str) -> str | None:
    source = str(source_image or "").strip()
    if not source or source.lower() == "latest":
        return None
    path = os.path.abspath(os.path.expanduser(os.path.expandvars(source)))
    return path if os.path.exists(path) else None


def compose_character_prompt(request: CharacterImageRequest, *, edit: bool = False) -> str:
    profile = request.profile
    lines = [
        "Use the provided reference images as the canonical visual identity.",
        f"Character: {profile.display_name}.",
        f"Mode: {request.mode}.",
    ]
    if request.preserve_identity:
        lines.append(
            "Preserve the character identity exactly: face structure, eye color, hair color, hair accessories, beauty marks, body proportions, and recognizable silhouette."
        )
    if profile.identity_prompt:
        lines.append(f"Character identity rules: {profile.identity_prompt}")
    lines.append(f"Creative request: {request.prompt}")
    if edit:
        lines.append("Edit only what the creative request asks. Do not redesign unrelated character traits.")

    negative_parts = [profile.negative_prompt, request.negative_prompt]
    negative_text = " ".join(part for part in negative_parts if part).strip()
    if negative_text:
        lines.append(f"Avoid: {negative_text}")

    return "\n".join(lines)
