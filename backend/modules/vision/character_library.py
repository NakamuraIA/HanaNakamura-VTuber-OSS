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
from pathlib import Path
from typing import Any


def _discover_default_character_root() -> str:
    """Find the workspace data/characters folder independent of process cwd."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "characters"
        if candidate.is_dir():
            return str(candidate)
    return os.path.abspath(os.path.join("data", "characters"))


DEFAULT_CHARACTER_ROOT = _discover_default_character_root()
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
    character_ids: tuple[str, ...]
    prompt: str
    mode: str
    references: tuple[str, ...]
    preserve_identity: bool
    source_image: str
    negative_prompt: str
    profile: CharacterProfile
    profiles: tuple[CharacterProfile, ...]


def _safe_character_alias(value: str) -> str:
    """Normalize a character folder, JSON alias, or XML ID for matching."""
    return re.sub(r"[^a-z0-9_-]+", "_", str(value or "").strip().lower()).strip("_")


def _safe_character_id(value: str) -> str:
    """Return a valid character ID, defaulting empty values to Hana."""
    character_id = _safe_character_alias(value)
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


def _registered_character_aliases(root_dir: str = DEFAULT_CHARACTER_ROOT) -> dict[str, str]:
    """Map folder names and JSON aliases to canonical lowercase character IDs."""
    aliases: dict[str, str] = {}
    if not os.path.isdir(root_dir):
        return aliases

    for entry in os.listdir(root_dir):
        profile_dir = os.path.join(root_dir, entry)
        profile_path = os.path.join(profile_dir, "character.json")
        if not os.path.isdir(profile_dir) or not os.path.exists(profile_path):
            continue

        canonical = _safe_character_alias(entry)
        if not canonical:
            continue
        aliases[canonical] = canonical

        try:
            with open(profile_path, "r", encoding="utf-8-sig") as file:
                data = json.load(file)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            continue

        for key in ("display_name", "name", "nickname", "apelido"):
            alias = _safe_character_alias(data.get(key) or "")
            if alias:
                aliases[alias] = canonical
    return aliases


def resolve_character_id(character_id: str, *, root_dir: str = DEFAULT_CHARACTER_ROOT) -> str:
    """Resolve a folder ID or configured alias to the canonical character ID."""
    safe_id = _safe_character_id(character_id)
    return _registered_character_aliases(root_dir).get(safe_id, safe_id)


def load_character_profile(character_id: str = DEFAULT_CHARACTER_ID, *, root_dir: str = DEFAULT_CHARACTER_ROOT) -> CharacterProfile:
    safe_id = resolve_character_id(character_id, root_dir=root_dir)
    profile_dir = os.path.abspath(os.path.join(root_dir, safe_id))
    if os.path.isdir(root_dir):
        for entry in os.listdir(root_dir):
            if entry.lower() == safe_id:
                profile_dir = os.path.abspath(os.path.join(root_dir, entry))
                break
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


def _coerce_character_id_list(value: Any) -> tuple[str, ...]:
    """Coerce XML/JSON character fields into an ordered list of IDs."""
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        parts = re.split(r"\s*(?:,|;|\||\+)\s*", text)
        return tuple(part.strip() for part in parts if part.strip())
    return _coerce_string_list(value)


def _payload_character_ids(payload: dict[str, Any], default_character_id: str, *, root_dir: str) -> tuple[str, ...]:
    """Read singular or multi-character payload keys without breaking old XML."""
    raw_ids = _coerce_character_id_list(
        payload.get("characters")
        or payload.get("character_ids")
        or payload.get("personagens")
        or payload.get("personagem_ids")
    )
    if not raw_ids:
        raw_ids = _coerce_character_id_list(
            payload.get("character")
            or payload.get("character_id")
            or payload.get("personagem")
            or payload.get("personagem_id")
            or default_character_id
        )

    resolved: list[str] = []
    seen: set[str] = set()
    for raw_id in raw_ids:
        character_id = resolve_character_id(raw_id, root_dir=root_dir)
        if character_id not in seen:
            resolved.append(character_id)
            seen.add(character_id)
    return tuple(resolved or (DEFAULT_CHARACTER_ID,))


def parse_character_image_request(
    raw_payload: str | dict[str, Any],
    *,
    default_character_id: str = DEFAULT_CHARACTER_ID,
    root_dir: str = DEFAULT_CHARACTER_ROOT,
) -> CharacterImageRequest:
    payload, raw_text = _load_payload(raw_payload)
    character_ids = _payload_character_ids(payload, default_character_id, root_dir=root_dir)
    profiles = tuple(load_character_profile(character_id, root_dir=root_dir) for character_id in character_ids)
    profile = profiles[0]

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
        character_id=character_ids[0],
        character_ids=character_ids,
        prompt=prompt,
        mode=str(payload.get("mode") or payload.get("modo") or "scene").strip() or "scene",
        references=tuple(references),
        preserve_identity=bool(preserve_identity),
        source_image=str(payload.get("source_image") or payload.get("image_path") or payload.get("imagem_base") or "").strip(),
        negative_prompt=str(payload.get("negative_prompt") or payload.get("avoid") or payload.get("evitar") or "").strip(),
        profile=profile,
        profiles=profiles,
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


def resolve_request_reference_paths(request: CharacterImageRequest) -> list[str]:
    """Resolve and deduplicate references for every character in one image request."""
    resolved: list[str] = []
    seen: set[str] = set()
    for profile in request.profiles:
        for path in resolve_reference_paths(profile, request.references):
            normalized = os.path.abspath(path).lower()
            if normalized not in seen:
                resolved.append(path)
                seen.add(normalized)
    return resolved


def resolve_source_image_path(source_image: str) -> str | None:
    source = str(source_image or "").strip()
    if not source or source.lower() == "latest":
        return None
    path = os.path.abspath(os.path.expanduser(os.path.expandvars(source)))
    return path if os.path.exists(path) else None


def compose_character_prompt(request: CharacterImageRequest, *, edit: bool = False) -> str:
    profiles = request.profiles or (request.profile,)
    lines = [
        "Use the provided reference images as the canonical visual identity for each registered character.",
        f"Mode: {request.mode}.",
    ]
    if len(profiles) > 1:
        lines.append(
            "This image contains multiple registered characters. Preserve each identity separately and do not merge their faces, hair, accessories, clothes, colors, or body traits."
        )
    if request.preserve_identity:
        lines.append(
            "Preserve the character identity exactly: face structure, eye color, hair color, hair accessories, beauty marks, body proportions, and recognizable silhouette."
        )

    for profile in profiles:
        lines.append(f"Character: {profile.display_name} (id: {profile.character_id}).")
        if profile.identity_prompt:
            lines.append(f"Identity rules for {profile.display_name}: {profile.identity_prompt}")

    if len(profiles) > 1:
        lines.append("Composition rule: include all listed characters in the same scene unless the creative request explicitly says otherwise.")
    lines.append(f"Creative request: {request.prompt}")
    if edit:
        lines.append("Edit only what the creative request asks. Do not redesign unrelated character traits.")

    negative_parts = [profile.negative_prompt for profile in profiles]
    negative_parts.append(request.negative_prompt)
    negative_text = " ".join(dict.fromkeys(part for part in negative_parts if part)).strip()
    if negative_text:
        lines.append(f"Avoid: {negative_text}")

    return "\n".join(lines)
