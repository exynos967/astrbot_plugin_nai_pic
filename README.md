<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_nai_brush?name=astrbot_plugin_nai_brush&theme=miku&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# 幻笔 — NovelAI 绘图插件

基于 NovelAI 的 AI 绘图插件，适用于

支持自然语言生图、直接标签生图、画师预设切换、图片反推打标，以及工具调用。

## 功能一览

| 命令 | 说明 |
|------|------|
| `/nai draw <描述>` | 自然语言描述生图 |
| `/nai tag <英文标签>` | 直接使用英文标签生图 |
| `/nai set [模型代号]` | 查看或切换模型 |
| `/nai art [编号]` | 查看或切换画师预设 |
| `/nai size [尺寸]` | 查看或切换尺寸 |
| `/nai help` | 查看帮助 |
| `/打标` | 引用回复图片进行反推打标 |
| `/nai0 <标签>` | `/nai tag` 的兼容别名 |

此外，插件注册了 `nai_generate_image` LLM Tool，在支持 Function Calling 的会话中可作为原生生图工具被 LLM 自动调用。

## 支持模型

| 代号 | 模型 |
|------|------|
| `3` | NAI Diffusion V3 |
| `f3` | NAI Diffusion V3 Furry |
| `4` | NAI Diffusion V4 |
| `4.5` | NAI Diffusion V4.5 |

## 配置说明

所有配置项均可在 AstrBot 管理面板的插件配置页中编辑，每项都附有说明和提示。

| 配置组 | 说明 |
|--------|------|
| **基础配置** | API 地址、Token、默认模型、全局参数、全局画师预设 |
| **NAI V3 / V4 / V4.5 专属配置** | 各版本覆盖参数与专属画师预设，留空时回退到基础配置 |
| **提示词生成** | LLM Provider、温度、输出格式、自拍外貌策略 |
| **图片打标** | 打标 Provider 及参数 |
| **权限管理** | 插件管理员列表、默认管理员模式 |
| **自动撤回** | 撤回开关、延迟秒数、白名单 |
| **NSFW 过滤** | 过滤开关与过滤标签 |
| **提示词显示** | 提示词展示开关 |
| **自定义系统提示** | 注入到提示词生成模板的全局风格指导 |

### 画师预设

画师预设支持全局 + 各版本分级配置：

- 各版本（V3 / V4 / V4.5）可以定义专属预设
- 版本预设为空时自动回退到基础配置中的全局预设
- 每个预设包含：名称、风格说明、画师 Prompt、附加负面提示词
- 通过 `/nai art` 命令查看和切换

### 提示词生成 Provider

`prompt_generator.provider_id` 用于指定将自然语言转为绘图标签的 LLM Provider。留空时默认跟随当前会话的聊天模型。

推荐模型：**grok4.2**、**gemini-3-flash**

## 安装

在 AstrBot 管理面板中搜索 `幻笔` 或 `nai_brush` 安装即可。

依赖：`httpx >= 0.27.0`（安装时自动处理）。

## 致谢

- [久远](https://github.com/saberlights) / [nai_pic_plugin](https://github.com/saberlights/nai_pic_plugin)
