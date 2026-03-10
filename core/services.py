"""Business services for the AstrBot NAI picture plugin."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from astrbot.api import logger

from .clients import NaiWebClient
from .config import (
    get_config_value,
    get_session_provider_id,
    is_recall_enabled,
    recall_is_allowed_in_session,
    resolve_model_config,
)
from .message_utils import delete_onebot_message, send_image_message, sleep_and_delete
from .models import PromptBuildResult, SessionContext
from .session_state import SessionStateStore
from .templates import (
    PROMPT_GENERATOR_JSON_TEMPLATE,
    PROMPT_GENERATOR_TEMPLATE,
    SFW_PROMPT_GENERATOR_JSON_TEMPLATE,
    SFW_PROMPT_GENERATOR_TEMPLATE,
    TAGGER_PROMPT_TEMPLATE,
    detect_selfie_from_output,
    get_selfie_hint,
    merge_selfie_prompt,
)
from .utils import (
    normalize_output,
    normalize_prompt_order,
    parse_json_object,
    parse_prompt_from_structured_output,
    remove_selfie_appearance_tags,
    user_mentions_appearance,
)


class LLMService:
    def __init__(self, context: Any, config: dict[str, Any]) -> None:
        self.context = context
        self.config = config

    async def _provider_id(
        self,
        event: Any,
        primary_path: str,
        *fallback_paths: str,
    ) -> str | None:
        provider_id = get_session_provider_id(self.config, primary_path, *fallback_paths)
        if provider_id:
            return provider_id
        try:
            provider_id = await self.context.get_current_chat_provider_id(
                umo=event.unified_msg_origin
            )
        except Exception as exc:
            logger.error(f"[nai_pic] 获取当前会话 provider 失败: {exc}")
            return None
        return provider_id or None

    async def generate(
        self,
        event: Any,
        *,
        prompt: str,
        provider_path: str,
        fallback_paths: tuple[str, ...] = (),
        temperature: float = 0.2,
        max_tokens: int = 300,
        image_inputs: list[str] | None = None,
    ) -> str | None:
        provider_id = await self._provider_id(event, provider_path, *fallback_paths)
        if not provider_id:
            return None

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                image_urls=image_inputs or None,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.error(f"[nai_pic] LLM 调用失败: {exc}")
            return None

        text = str(getattr(response, "completion_text", "") or "").strip()
        return text or None


class PromptGeneratorService:
    def __init__(
        self,
        config: dict[str, Any],
        states: SessionStateStore,
        llm_service: LLMService,
    ) -> None:
        self.config = config
        self.states = states
        self.llm = llm_service

    async def generate_prompt(
        self,
        event: Any,
        session: SessionContext,
        request_text: str,
        model_config: dict[str, Any],
    ) -> PromptBuildResult | None:
        output_format = str(
            get_config_value(self.config, "prompt_generator.output_format", "text") or "text"
        ).strip().lower()
        nsfw_filter_enabled = bool(
            get_config_value(self.config, "nsfw_filter.enabled", False)
        )
        if self.states.get(session).nsfw_filter_enabled is not None:
            nsfw_filter_enabled = bool(self.states.get(session).nsfw_filter_enabled)

        if output_format == "json":
            template = (
                SFW_PROMPT_GENERATOR_JSON_TEMPLATE
                if nsfw_filter_enabled
                else PROMPT_GENERATOR_JSON_TEMPLATE
            )
        else:
            template = (
                SFW_PROMPT_GENERATOR_TEMPLATE
                if nsfw_filter_enabled
                else PROMPT_GENERATOR_TEMPLATE
            )

        custom_template = str(
            get_config_value(self.config, "prompt_generator.prompt_template", "") or ""
        ).strip()
        if custom_template:
            template = custom_template

        custom_system_prompt = str(
            get_config_value(self.config, "custom_prompt.system_prompt", "") or ""
        ).strip()
        prompt = template.replace(
            "<<CUSTOM_SYSTEM_PROMPT>>",
            f"{custom_system_prompt}\n\n" if custom_system_prompt else "",
        )
        prompt = prompt.replace("<<SELFIE_HINT>>", get_selfie_hint())
        prompt = prompt.replace("<<USER_REQUEST>>", request_text.strip() or "N/A")

        response = await self.llm.generate(
            event,
            prompt=prompt,
            provider_path="prompt_generator.provider_id",
            fallback_paths=("prompt_generator.chat_provider_id",),
            temperature=float(
                get_config_value(self.config, "prompt_generator.temperature", 0.2) or 0.2
            ),
            max_tokens=int(
                get_config_value(self.config, "prompt_generator.max_tokens", 220) or 220
            ),
        )
        if not response:
            return None

        cleaned = self._cleanup_response(response)
        if not cleaned:
            return None

        is_selfie = detect_selfie_from_output(cleaned)
        display_prompt = cleaned
        final_prompt = cleaned

        if is_selfie:
            hide_selfie_prompt_add = bool(
                get_config_value(self.config, "prompt_show.hide_selfie_prompt_add", False)
            )
            display_prompt = self._apply_selfie_policy(
                cleaned,
                request_text,
                str(model_config.get("selfie_prompt_add") or ""),
                include_selfie_prompt_add=not hide_selfie_prompt_add,
                log_changes=False,
            )
            final_prompt = self._apply_selfie_policy(
                cleaned,
                request_text,
                str(model_config.get("selfie_prompt_add") or ""),
            )

        if get_config_value(self.config, "prompt_generator.enforce_tag_order", False):
            display_prompt = normalize_prompt_order(display_prompt)
            final_prompt = normalize_prompt_order(final_prompt)
        return PromptBuildResult(
            prompt=final_prompt,
            display_prompt=display_prompt,
            is_selfie=is_selfie,
        )

    def _cleanup_response(self, response: str) -> str:
        parsed = parse_prompt_from_structured_output(response)
        if parsed:
            return parsed

        cleaned = response.strip()
        if cleaned.startswith("```") and cleaned.endswith("```"):
            cleaned = cleaned[3:-3].strip()
            if "\n" in cleaned:
                first_line, rest = cleaned.split("\n", 1)
                if first_line.strip().isalpha() and len(first_line.strip()) < 15:
                    cleaned = rest.strip()

        if cleaned.startswith("`") and cleaned.endswith("`") and cleaned.count("`") == 2:
            cleaned = cleaned[1:-1].strip()
        if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
            cleaned = cleaned[1:-1].strip()

        cleaned = re.sub(
            r"^(?:output|result|prompt|here(?:'s| is)(?: the)?(?: prompt)?)\s*[:：]\s*",
            "",
            cleaned,
            flags=re.I,
        ).strip()

        if "\n" in cleaned:
            lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
            has_multi = any(line.startswith("|") for line in lines)
            valid_lines = [
                line
                for line in lines
                if not re.match(r"^(note|explanation|this|i |the above|here)", line, re.I)
            ]
            if valid_lines:
                cleaned = "\n".join(valid_lines) if has_multi else valid_lines[0]

        return cleaned

    def _apply_selfie_policy(
        self,
        prompt: str,
        raw_request: str,
        selfie_prompt_add: str,
        *,
        include_selfie_prompt_add: bool = True,
        log_changes: bool = True,
    ) -> str:
        policy = str(
            get_config_value(self.config, "prompt_generator.selfie_appearance_policy", "auto")
            or "auto"
        ).strip().lower()
        user_specified = user_mentions_appearance(raw_request)
        original = prompt

        if policy == "auto" and not user_specified:
            prompt = remove_selfie_appearance_tags(prompt)
        if include_selfie_prompt_add and selfie_prompt_add:
            prompt = merge_selfie_prompt(prompt, selfie_prompt_add)
        if policy == "never" and not user_specified:
            prompt = remove_selfie_appearance_tags(prompt)

        if log_changes and prompt != original:
            logger.debug(
                "[nai_pic] 自拍提示词后处理已生效: policy=%s, user_specified=%s",
                policy,
                user_specified,
            )
        return prompt


class TaggerService:
    def __init__(self, config: dict[str, Any], llm_service: LLMService) -> None:
        self.config = config
        self.llm = llm_service

    async def tag(self, event: Any, image_input: str) -> str | None:
        response = await self.llm.generate(
            event,
            prompt=TAGGER_PROMPT_TEMPLATE,
            provider_path="tagger.provider_id",
            fallback_paths=("prompt_generator.provider_id",),
            temperature=float(get_config_value(self.config, "tagger.temperature", 0.2) or 0.2),
            max_tokens=int(get_config_value(self.config, "tagger.max_tokens", 900) or 900),
            image_inputs=[image_input],
        )
        if not response:
            return None

        payload = parse_json_object(response)
        if not payload:
            return None

        normalized = normalize_output(payload)
        return self._format_prompt(
            normalized.get("CHARACTER_TAG", []),
            normalized.get("WORK_TAG", []),
            normalized.get("TAG", []),
        )

    def _format_prompt(
        self,
        character_tags: Any,
        work_tags: Any,
        tags: Any,
    ) -> str:
        characters = character_tags if isinstance(character_tags, list) else []
        works = work_tags if isinstance(work_tags, list) else []
        extras = tags if isinstance(tags, list) else []
        work = str(works[0]).strip() if works else ""

        head = []
        for item in characters:
            value = str(item).strip()
            if not value:
                continue
            head.append(f"{value} ({work})" if work else value)

        tail = [str(item).strip() for item in extras if str(item).strip()]

        out: list[str] = []
        seen: set[str] = set()
        for item in head + tail:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return ", ".join(out).strip()


class ImageService:
    def __init__(
        self,
        config: dict[str, Any],
        states: SessionStateStore,
        nai_client: NaiWebClient,
    ) -> None:
        self.config = config
        self.states = states
        self.client = nai_client

    async def generate_and_send(
        self,
        event: Any,
        session: SessionContext,
        prompt: str,
        *,
        model_config_override: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        model_config = (
            dict(model_config_override)
            if model_config_override is not None
            else resolve_model_config(self.config, session, self.states)
        )
        if not model_config.get("base_url"):
            return False, "NAI base_url 未配置"

        success, result = await self.client.generate_image(
            prompt=prompt,
            model_config=model_config,
            size=str(model_config.get("nai_size") or model_config.get("default_size") or ""),
        )
        if not success:
            return False, result

        image_input = self._normalize_image_output(result)
        if not image_input:
            return False, "无法识别接口返回的图片格式"

        message_id = await send_image_message(event, image_input)
        if message_id:
            self.states.track_image(session, message_id, prompt)
            await self._schedule_auto_recall(event, session, message_id)
        return True, prompt

    def _normalize_image_output(self, result: str) -> str | None:
        cleaned = (result or "").strip()
        if not cleaned:
            return None
        if cleaned.startswith(("http://", "https://", "file:///", "base64://")):
            return cleaned
        if cleaned.startswith("data:image"):
            prefix, _ = cleaned.split(",", 1)
            return f"base64://{cleaned[len(prefix) + 1:]}"
        return f"base64://{cleaned}"

    async def _schedule_auto_recall(
        self,
        event: Any,
        session: SessionContext,
        message_id: str,
    ) -> None:
        if not is_recall_enabled(self.config, session, self.states):
            return
        if not recall_is_allowed_in_session(self.config, session):
            return

        delay_seconds = float(
            get_config_value(self.config, "auto_recall.delay_seconds", 5) or 5
        )
        asyncio.create_task(sleep_and_delete(event, message_id, delay_seconds))

    async def delete_message(self, event: Any, message_id: str) -> bool:
        return await delete_onebot_message(event, message_id)
