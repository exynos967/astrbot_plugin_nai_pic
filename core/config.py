"""Configuration helpers for the AstrBot NAI picture plugin."""

from __future__ import annotations

import json
from typing import Any

from .constants import (
    DEFAULT_NAI_ENDPOINT,
    DEFAULT_NEGATIVE_FILTER_TAG,
    MODEL_ALIASES,
    MODEL_DISPLAY_NAMES,
    SIZE_ALIASES,
    SIZE_DISPLAY_NAMES,
)
from .models import ArtistPreset, SessionContext
from .session_state import SessionStateStore


def get_config_value(config: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = config
    for key in path.split("."):
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current


def parse_artist_presets(raw_value: Any) -> list[ArtistPreset]:
    """解析画师预设列表，兼容旧格式(list/dict)和 template_list 格式。"""
    if not isinstance(raw_value, list):
        return []

    presets: list[ArtistPreset] = []
    for index, item in enumerate(raw_value, start=1):
        if isinstance(item, dict):
            # template_list 格式包含 __template_key，忽略该字段
            name = str(item.get("name") or f"画师串 {index}").strip()
            prompt = str(item.get("prompt") or "").strip()
            negative_prompt = str(item.get("negative_prompt") or "").strip()
            description = str(item.get("description") or "").strip()
        elif isinstance(item, str):
            name = f"画师串 {index}"
            prompt = item.strip()
            negative_prompt = ""
            description = ""
        else:
            continue

        if prompt:
            presets.append(ArtistPreset(
                name=name,
                prompt=prompt,
                negative_prompt=negative_prompt,
                description=description,
            ))
    return presets


def parse_extra_params(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return dict(raw_value)

    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def normalize_model_alias(raw_value: str) -> str | None:
    value = (raw_value or "").strip().lower()
    if not value:
        return None
    return MODEL_ALIASES.get(value, value)


def normalize_size_alias(raw_value: str) -> str | None:
    value = (raw_value or "").strip().lower()
    if not value:
        return None
    return SIZE_ALIASES.get(value, raw_value.strip())


def model_display_name(model_name: str) -> str:
    return MODEL_DISPLAY_NAMES.get(model_name, model_name)


def size_display_name(size: str) -> str:
    return SIZE_DISPLAY_NAMES.get(size, size)


def detect_model_section(model_name: str) -> str:
    normalized = (model_name or "").strip().lower()
    if "4-5" in normalized:
        return "model_nai4_5"
    if "nai-diffusion-4" in normalized:
        return "model_nai4"
    return "model_nai3"


def get_session_provider_id(
    config: dict[str, Any],
    primary_path: str,
    *fallback_paths: str,
) -> str:
    for path in (primary_path, *fallback_paths):
        value = str(get_config_value(config, path, "") or "").strip()
        if value:
            return value
    return ""


def is_plugin_admin(
    config: dict[str, Any],
    session: SessionContext,
) -> bool:
    admin_users = get_config_value(config, "admin.admin_users", [])
    if isinstance(admin_users, list) and str(session.user_id) in {
        str(item) for item in admin_users
    }:
        return True
    return session.is_admin


def is_admin_mode_enabled(
    config: dict[str, Any],
    session: SessionContext,
    states: SessionStateStore,
) -> bool:
    state = states.get(session)
    if state.admin_mode is not None:
        return state.admin_mode
    return bool(get_config_value(config, "admin.default_admin_mode", False))


def can_use_generation(
    config: dict[str, Any],
    session: SessionContext,
    states: SessionStateStore,
) -> bool:
    if not is_admin_mode_enabled(config, session, states):
        return True
    return is_plugin_admin(config, session)


def is_prompt_show_enabled(
    config: dict[str, Any],
    session: SessionContext,
    states: SessionStateStore,
) -> bool:
    state = states.get(session)
    if state.prompt_show_enabled is not None:
        return state.prompt_show_enabled
    return bool(get_config_value(config, "prompt_show.enabled", False))


def should_show_draw_prompt(
    config: dict[str, Any],
    session: SessionContext,
    states: SessionStateStore,
) -> bool:
    if not bool(get_config_value(config, "prompt_show.draw_output_enabled", True)):
        return False
    return is_prompt_show_enabled(config, session, states)


def is_recall_enabled(
    config: dict[str, Any],
    session: SessionContext,
    states: SessionStateStore,
) -> bool:
    state = states.get(session)
    if state.recall_enabled is not None:
        return state.recall_enabled
    return bool(get_config_value(config, "auto_recall.enabled", False))


def is_nsfw_filter_enabled(
    config: dict[str, Any],
    session: SessionContext,
    states: SessionStateStore,
) -> bool:
    state = states.get(session)
    if state.nsfw_filter_enabled is not None:
        return state.nsfw_filter_enabled
    return bool(get_config_value(config, "nsfw_filter.enabled", False))


def recall_is_allowed_in_session(config: dict[str, Any], session: SessionContext) -> bool:
    allowed_groups = get_config_value(config, "auto_recall.allowed_groups", [])
    if not isinstance(allowed_groups, list) or not allowed_groups:
        return True
    return session.session_key in {str(item) for item in allowed_groups}


def resolve_model_config(
    config: dict[str, Any],
    session: SessionContext,
    states: SessionStateStore,
) -> dict[str, Any]:
    base = dict(get_config_value(config, "model", {}) or {})
    model_name = states.get(session).selected_model or str(
        base.get("default_model") or "nai-diffusion-4-5-full"
    )
    base["default_model"] = model_name
    base.setdefault("nai_endpoint", DEFAULT_NAI_ENDPOINT)

    version_section = detect_model_section(model_name)
    version_settings = dict(get_config_value(config, version_section, {}) or {})
    extra_params = parse_extra_params(base.get("nai_extra_params"))
    extra_params.update(parse_extra_params(version_settings.pop("nai_extra_params", {})))
    merged = {**base, **version_settings}
    if extra_params:
        merged["nai_extra_params"] = extra_params

    state = states.get(session)
    selected_size = state.selected_size
    if selected_size:
        merged["nai_size"] = selected_size

    presets = parse_artist_presets(
        get_config_value(config, f"{version_section}.artist_presets", [])
    )
    # 版本预设为空时回退到全局预设
    if not presets:
        presets = parse_artist_presets(
            get_config_value(config, "model.artist_presets", [])
        )
    index = state.selected_artist_index or 1
    if presets and 1 <= index <= len(presets):
        selected = presets[index - 1]
        merged["nai_artist_prompt"] = selected.prompt
        if selected.negative_prompt:
            existing_neg = str(merged.get("negative_prompt_add") or "").strip()
            merged["negative_prompt_add"] = (
                f"{existing_neg}, {selected.negative_prompt}" if existing_neg else selected.negative_prompt
            )

    if is_nsfw_filter_enabled(config, session, states):
        filter_tags = str(
            get_config_value(
                config,
                "nsfw_filter.filter_tags",
                DEFAULT_NEGATIVE_FILTER_TAG,
            )
            or DEFAULT_NEGATIVE_FILTER_TAG
        ).strip()
        negative_prompt = str(merged.get("negative_prompt_add") or "").strip()
        merged["negative_prompt_add"] = (
            f"{filter_tags}, {negative_prompt}" if negative_prompt else filter_tags
        )

    return merged


def build_help_text(config: dict[str, Any]) -> str:
    base_model = str(get_config_value(config, "model.default_model", "") or "")
    return "\n".join(
        [
            "📖 NAI 图片插件命令",
            "/nai draw <描述>：自然语言生图",
            "/nai tag <英文标签>：直接标签生图（兼容 /nai0）",
            "/nai help：查看帮助",
            "/nai set [模型代号]：查看或切换模型",
            "/nai art [编号]：查看或切换画师预设",
            "/nai size [尺寸]：查看或切换尺寸",
            "/nai nsfw [on|off]：查看或切换 NSFW 过滤",
            "/打标：引用回复图片进行打标",
            f"当前默认模型：{model_display_name(base_model) if base_model else '未配置'}",
        ]
    )
