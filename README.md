# astrbot_plugin_nai_pic

将原 `nai_pic_plugin` 从 MaiBot 迁移到 AstrBot 的版本，按 AstrBot 插件规范重写了入口、配置和 QQ/NapCat 交互层。

## 功能

- `/nai <描述>`：自然语言生图，调用当前会话或插件指定的 AstrBot provider 生成英文提示词
- `/nai0 <英文标签>`：直接标签生图
- `/nai set`、`/nai art`、`/nai size`：会话级模型/画师预设/尺寸切换
- `/nai on|off`、`/nai 撤回`：NapCat/OneBot 环境下的自动/手动撤回
- `/nai pt on|off`、`/nai nsfw on|off`、`/nai st|sp`：提示词显示、NSFW 过滤、插件管理员模式
- `/打标`：引用回复一张图片，用支持图像输入的 provider 输出 NAI 可直接复制的 prompt
- `nai_generate_image`：注册为 AstrBot `llm_tool`，可在支持 function calling 的会话中作为原生生图工具使用

## 配置说明

- `model.*`：NovelAI Web 接口、默认模型和通用参数
- `model_nai3` / `model_nai4` / `model_nai4_5`：分模型版本的尺寸、采样、CFG、正负面补充词、画师预设和额外参数
  其中 `nai_extra_params` 需填写为 JSON 对象字符串，如 `{"seed": 42, "qualityToggle": true}`
- `prompt_generator.provider_id`：留空时默认跟随当前会话聊天模型
- `tagger.provider_id`：可单独指定打标模型
- `prompt_show.hide_selfie_prompt_add`：展示提示词时可隐藏自拍模式自动补充的角色标签
- `auto_recall`：仅在 `aiocqhttp` / NapCat OneBot 下可用

## 模型推荐

- grok4.2
- gemini-3-flash

## 特别感谢

- [久远](https://github.com/saberlights)
- [nai_pic_plugin](https://github.com/saberlights/nai_pic_plugin)
