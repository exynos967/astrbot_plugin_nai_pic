from __future__ import annotations

from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .core.clients import NaiWebClient
from .core.config import (
    build_help_text,
    can_use_generation,
    get_config_value,
    is_plugin_admin,
    is_prompt_show_enabled,
    model_display_name,
    normalize_model_alias,
    normalize_size_alias,
    parse_artist_presets,
    resolve_model_config,
    size_display_name,
)
from .core.message_utils import (
    extract_first_reply_image_input,
    extract_reply_message_id,
    send_text_message,
)
from .core.models import SessionContext
from .core.services import (
    ImageService,
    LLMService,
    PromptGeneratorService,
    TaggerService,
)
from .core.session_state import SessionStateStore


@register(
    "astrbot_plugin_nai_pic",
    "Rabbit",
    "NovelAI Web 图片生成插件（AstrBot 版）",
    "1.0.0",
    "https://github.com/Rabbit-Jia-Er/nai_pic_plugin",
)
class Main(Star):
    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context, config)
        self.context = context
        self.config: dict[str, Any] = dict(config or {})

        self.states = SessionStateStore()
        self.nai_client = NaiWebClient()
        self.llm_service = LLMService(self.context, self.config)
        self.prompt_service = PromptGeneratorService(
            self.config,
            self.states,
            self.llm_service,
        )
        self.tagger_service = TaggerService(self.config, self.llm_service)
        self.image_service = ImageService(self.config, self.states, self.nai_client)

    async def terminate(self) -> None:
        await self.nai_client.close()

    @filter.command("nai")
    async def nai(self, event: AstrMessageEvent) -> None:
        """NovelAI 生图与管理命令。"""
        session = SessionContext.from_event(event)
        remainder = self._command_remainder(event.message_str)

        if not remainder:
            await send_text_message(event, build_help_text(self.config))
            return

        command, argument = self._split_remainder(remainder)
        if command == "help":
            await send_text_message(event, build_help_text(self.config))
            return
        if command in {"on", "off"}:
            await self._handle_recall_toggle(event, session, command == "on")
            return
        if command in {"st", "sp"}:
            await self._handle_admin_mode(event, session, command == "st")
            return
        if command == "set":
            await self._handle_model_switch(event, session, argument)
            return
        if command == "art":
            await self._handle_artist_preset(event, session, argument)
            return
        if command == "size":
            await self._handle_size_switch(event, session, argument)
            return
        if command == "pt":
            await self._handle_prompt_show(event, session, argument)
            return
        if command == "nsfw":
            await self._handle_nsfw(event, session, argument)
            return
        if command == "撤回":
            await self._handle_recall_last(event, session)
            return

        await self._handle_draw(event, session, remainder)

    @filter.command("nai0")
    async def nai0(self, event: AstrMessageEvent) -> None:
        """直接使用英文标签生图。"""
        session = SessionContext.from_event(event)
        if not can_use_generation(self.config, session, self.states):
            await send_text_message(event, "❌ 当前会话启用了管理员模式，只有管理员可以使用生图命令。")
            return

        tags = self._command_remainder(event.message_str)
        if not tags:
            await send_text_message(event, "用法：/nai0 1girl, hatsune miku, smile")
            return

        success, result = await self.image_service.generate_and_send(event, session, tags)
        if not success:
            await send_text_message(event, f"❌ 生成失败：{result}")

    @filter.command("打标")
    async def tag(self, event: AstrMessageEvent) -> None:
        """引用回复图片进行打标。"""
        image_input = await extract_first_reply_image_input(event)
        if not image_input:
            await send_text_message(event, "❌ 请引用回复一张图片后再发送 /打标。")
            return

        result = await self.tagger_service.tag(event, image_input)
        if not result:
            await send_text_message(
                event,
                "❌ 打标失败。请确认当前 provider 支持图像输入，并适当提高 tagger.max_tokens。",
            )
            return
        await send_text_message(event, result)

    @filter.llm_tool(name="nai_generate_image")
    async def nai_generate_image_tool(self, event: AstrMessageEvent, request: str) -> str:
        """根据用户描述生成一张 NovelAI 图片并直接发送到当前会话。

        Args:
            request(string): 用户想绘制的画面描述，可以是中文自然语言或英文标签。
        """
        session = SessionContext.from_event(event)
        request_text = request.strip()
        if not request_text:
            return "未提供绘图描述。"
        if not can_use_generation(self.config, session, self.states):
            return "当前会话启用了管理员模式，只有管理员可以使用生图能力。"

        model_config = resolve_model_config(self.config, session, self.states)
        prompt_result = await self.prompt_service.generate_prompt(
            event,
            session,
            request_text,
            model_config,
        )
        if not prompt_result:
            return "提示词生成失败，请确认当前会话存在可用的聊天模型。"

        if is_prompt_show_enabled(self.config, session, self.states):
            await send_text_message(event, f"📝 提示词：\n{prompt_result.display_prompt}")

        success, result = await self.image_service.generate_and_send(
            event,
            session,
            prompt_result.prompt,
        )
        if not success:
            return f"图片生成失败：{result}"
        return f"图片已发送。最终提示词：{prompt_result.prompt}"

    async def _handle_draw(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
        request_text: str,
    ) -> None:
        if not can_use_generation(self.config, session, self.states):
            await send_text_message(event, "❌ 当前会话启用了管理员模式，只有管理员可以使用生图命令。")
            return

        model_config = resolve_model_config(self.config, session, self.states)
        prompt_result = await self.prompt_service.generate_prompt(
            event,
            session,
            request_text,
            model_config,
        )
        if not prompt_result:
            await send_text_message(event, "❌ 提示词生成失败，请确认当前会话有可用的聊天模型。")
            return

        if is_prompt_show_enabled(self.config, session, self.states):
            await send_text_message(event, f"📝 提示词：\n{prompt_result.display_prompt}")

        success, result = await self.image_service.generate_and_send(
            event,
            session,
            prompt_result.prompt,
        )
        if not success:
            await send_text_message(event, f"❌ 生成失败：{result}")
            return

        if get_config_value(self.config, "components.enable_debug_info", False):
            await send_text_message(event, "✅ 图片生成完成。")

    async def _handle_recall_toggle(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
        enabled: bool,
    ) -> None:
        if not is_plugin_admin(self.config, session):
            await send_text_message(event, "❌ 只有插件管理员可以切换自动撤回。")
            return

        self.states.get(session).recall_enabled = enabled
        delay = int(get_config_value(self.config, "auto_recall.delay_seconds", 5) or 5)
        if enabled:
            await send_text_message(
                event,
                f"✅ 已开启自动撤回。当前会话中本插件发出的图片将在 {delay} 秒后自动撤回。",
            )
        else:
            await send_text_message(event, "✅ 已关闭自动撤回。")

    async def _handle_admin_mode(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
        enabled: bool,
    ) -> None:
        if not is_plugin_admin(self.config, session):
            await send_text_message(event, "❌ 只有插件管理员可以切换管理员模式。")
            return
        self.states.get(session).admin_mode = enabled
        await send_text_message(
            event,
            "✅ 已开启 NAI 插件管理员模式。"
            if enabled
            else "✅ 已关闭 NAI 插件管理员模式。",
        )

    async def _handle_model_switch(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
        argument: str,
    ) -> None:
        if argument:
            if not can_use_generation(self.config, session, self.states):
                await send_text_message(event, "❌ 当前会话启用了管理员模式，只有管理员可以切换模型。")
                return
            model_name = normalize_model_alias(argument)
            if not model_name:
                await send_text_message(event, "❌ 模型代号不能为空。")
                return
            available_models = get_config_value(self.config, "model.available_models", [])
            if isinstance(available_models, list) and available_models and model_name not in available_models:
                await send_text_message(event, f"❌ 未在配置中声明该模型：{model_name}")
                return
            self.states.get(session).selected_model = model_name
            await send_text_message(
                event,
                f"✅ 当前会话已切换模型为：{model_display_name(model_name)}",
            )
            return

        current = resolve_model_config(self.config, session, self.states).get("default_model", "")
        available_models = get_config_value(self.config, "model.available_models", []) or []
        lines = [f"当前模型：{model_display_name(str(current))}"]
        alias_lines = []
        for alias, model_name in {"3": "nai-diffusion-3", "f3": "nai-diffusion-3-furry", "4": "nai-diffusion-4-full", "4.5": "nai-diffusion-4-5-full"}.items():
            if not available_models or model_name in available_models:
                alias_lines.append(f"{alias} = {model_display_name(model_name)}")
        lines.append("可用切换：")
        lines.extend(alias_lines or [str(item) for item in available_models])
        await send_text_message(event, "\n".join(lines))

    async def _handle_artist_preset(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
        argument: str,
    ) -> None:
        current_config = resolve_model_config(self.config, session, self.states)
        section = "model_nai4_5"
        model_name = str(current_config.get("default_model") or "")
        if "4-5" in model_name:
            section = "model_nai4_5"
        elif "nai-diffusion-4" in model_name:
            section = "model_nai4"
        else:
            section = "model_nai3"
        presets = parse_artist_presets(
            get_config_value(self.config, f"{section}.artist_presets", [])
        )
        if not presets:
            await send_text_message(event, "⚠️ 当前模型没有配置画师预设。")
            return

        state = self.states.get(session)
        current_index = state.selected_artist_index or 1
        if argument:
            if not argument.isdigit():
                await send_text_message(event, "❌ /nai art 后面请填写数字编号。")
                return
            index = int(argument)
            if not 1 <= index <= len(presets):
                await send_text_message(event, f"❌ 编号超出范围，当前共有 {len(presets)} 个预设。")
                return
            state.selected_artist_index = index
            await send_text_message(
                event,
                f"✅ 已切换到画师预设 #{index}：{presets[index - 1].name}",
            )
            return

        lines = [f"当前画师预设：#{current_index}"]
        for index, preset in enumerate(presets, start=1):
            marker = "👉" if index == current_index else "  "
            lines.append(f"{marker} {index}. {preset.name}")
        await send_text_message(event, "\n".join(lines))

    async def _handle_size_switch(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
        argument: str,
    ) -> None:
        if argument:
            normalized = normalize_size_alias(argument)
            if not normalized:
                await send_text_message(event, "❌ 尺寸不能为空。")
                return
            self.states.get(session).selected_size = normalized
            await send_text_message(event, f"✅ 已切换尺寸为：{size_display_name(normalized)}")
            return

        current_size = str(
            resolve_model_config(self.config, session, self.states).get("nai_size")
            or resolve_model_config(self.config, session, self.states).get("default_size")
            or "1024x1024"
        )
        lines = [f"当前尺寸：{size_display_name(current_size)}", "可用快捷值："]
        lines.extend(
            [
                "竖 / v -> 832x1216",
                "横 / h -> 1216x832",
                "方 / s -> 1024x1024",
            ]
        )
        await send_text_message(event, "\n".join(lines))

    async def _handle_prompt_show(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
        argument: str,
    ) -> None:
        if argument not in {"on", "off"}:
            enabled = is_prompt_show_enabled(self.config, session, self.states)
            await send_text_message(event, f"当前提示词显示：{'开启' if enabled else '关闭'}")
            return
        self.states.get(session).prompt_show_enabled = argument == "on"
        await send_text_message(
            event,
            "✅ 已开启提示词显示。" if argument == "on" else "✅ 已关闭提示词显示。",
        )

    async def _handle_nsfw(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
        argument: str,
    ) -> None:
        if argument not in {"", "on", "off"}:
            await send_text_message(event, "用法：/nai nsfw [on|off]")
            return
        if not argument:
            enabled = self.states.get(session).nsfw_filter_enabled
            if enabled is None:
                enabled = bool(get_config_value(self.config, "nsfw_filter.enabled", False))
            await send_text_message(event, f"当前 NSFW 过滤：{'开启' if enabled else '关闭'}")
            return
        if not is_plugin_admin(self.config, session):
            await send_text_message(event, "❌ 只有插件管理员可以切换 NSFW 过滤。")
            return
        self.states.get(session).nsfw_filter_enabled = argument == "on"
        await send_text_message(
            event,
            "✅ 已开启 NSFW 过滤。" if argument == "on" else "✅ 已关闭 NSFW 过滤。",
        )

    async def _handle_recall_last(
        self,
        event: AstrMessageEvent,
        session: SessionContext,
    ) -> None:
        self.states.prune_expired_images(session, 24 * 3600)
        reply_message_id = extract_reply_message_id(event)
        target = (
            self.states.find_recent_image(session, reply_message_id)
            if reply_message_id
            else self.states.latest_image(session)
        )
        if target is None:
            await send_text_message(event, "❌ 找不到可撤回的本插件图片。")
            return

        success = await self.image_service.delete_message(event, target.message_id)
        if success:
            await send_text_message(event, "✅ 已撤回。")
        else:
            await send_text_message(event, "❌ 撤回失败，可能消息已过期或当前平台不支持。")

    @staticmethod
    def _command_remainder(message: str) -> str:
        parts = (message or "").strip().split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    @staticmethod
    def _split_remainder(remainder: str) -> tuple[str, str]:
        parts = remainder.split(maxsplit=1)
        command = parts[0].strip().lower() if parts else ""
        argument = parts[1].strip() if len(parts) > 1 else ""
        return command, argument
