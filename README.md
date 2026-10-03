# astrbot_plugin_flood_guard（刷屏守卫）

AstrBot 群刷屏检测与自动禁言插件。

默认是**条数模式**：统计窗口内**任意消息**的条数，达到阈值即触发禁言；
也可以切换成**复读机模式**（只统计「同一条消息」的重复），见 `/flood mode`。

阈值 / 窗口 / 禁言时长 / 播报文案，既可在**插件配置页**修改，也可由**群管理员在 QQ 群内**用命令对单个群单独覆盖。

> 语言约定：**插件命令为英文**；**说明文档与群内回复为中文**。

## 命令（单一扁平命令，英文）

群里直接发即可（**不强制 @ 机器人**；带唤醒前缀 `/` 也行）。私聊不响应。

| 命令 | 权限 | 作用 |
|---|---|---|
| `/flood` 或 `/flood status` | 所有人 | 查看本群生效配置（也能验证插件是否加载成功） |
| `/flood help` | 所有人 | 用法说明 |
| `/flood mode <same\|any>` | 管理员 | 检测模式：`same` 只统计同一条消息；`any` 统计任意消息条数 |
| `/flood limit <数字>` | 管理员 | 达到多少条触发禁言 |
| `/flood window <秒>` | 管理员 | 统计窗口长度 |
| `/flood mute <秒>` | 管理员 | 禁言时长 |
| `/flood notice <文案>` | 管理员 | 本群播报文案 |
| `/flood reset` | 管理员 | 清除本群覆盖，回退全局默认 |

示例：

```
/flood mode any
/flood limit 5
/flood window 5
/flood mute 600
/flood notice {at} 别复读了，禁言 {mute_text}
```

### 群内触发不依赖唤醒

AstrBot 在「未唤醒」时会直接终止事件（`waking_check` 阶段的 `event.stop_event()`），
这也是此前 `/flood` 在 QQ 群里偶尔无响应的原因。
现在命令**同时由群消息事件处理器兜底处理**：只要消息以 `/flood` 开头（后面可跟参数），
即使唤醒判定异常、没 @ 到机器人，也能正常响应；
若 AstrBot 已正常激活原生指令，则不会重复应答。

### 为什么用单一扁平命令

AstrBot 的**指令组 + 子指令**由框架预编译的指令树分发，且子指令处理器的过滤器在唤醒阶段会被跳过，导致触发不稳定、权限也可能失效。改成单一扁平命令 + 手动解析子命令后，跨版本可靠性高很多。

## 排障：群里发了命令没反应

1. **确认插件已加载。** 裸发 `/flood` 一定会返回状态；完全没反应说明插件没加载，去 AstrBot 日志里找 import 报错。
2. **版本门槛。** `metadata.yaml` 要求 `astrbot_version: ">=4.0,<5"`；版本不匹配会在启动前直接拒绝加载，请按你的实际版本调整该行。
3. **禁言没生效？** 机器人在该群必须是**群主或管理员**，否则腾讯会返回 `ERR_NOT_GROUP_ADMIN`。此时插件**不会在群里播报**，只在服务器日志留一条 WARNING：
   `[flood_guard] mute failed; group notice suppressed ...`

## 检测语义

| 配置 | 默认 | 行为 |
|---|---|---|
| `same_message_only` | `false` | `false`：窗口内任意消息计数；`true`：只统计「同一条消息」的重复 |
| `only_chat_messages` | `true` | 忽略撤回/管理变更/入群/戳一戳等 notice 事件 |
| `text_normalize` | `true` | 文本比对忽略大小写与空白 |

### 「同一条」如何判定（仅 `same` 模式）

对消息链里的**内容段**归一化生成签名，忽略 `Reply` 这类上下文段：

| 段类型 | 签名 |
|---|---|
| 文本 | 去空白 + 转小写 |
| 图片 / 语音 / 视频 / 文件 | 本地文件**内容 MD5**（无本地文件时退化为去掉 query 的 URL） |
| 表情 | 表情 id |
| 卡片 / 分享 / 音乐 / 位置 | `data` |
| 戳一戳 | poke id |
| 合并转发 | 转发 id |

> 图片走**内容 MD5**：AstrBot 会把图片下载到 `data/temp/media_image_<时间戳>_<随机>.jpg`，路径每次都不同，直接拿路径当签名会导致「同一张图」被判成不同消息。

多个段会拼接为 `a|b|c`，因此 `same` 模式下「同一句话 + 同一张图」才算同一条。

## 配置项

| 配置项 | 默认 | 说明 |
|---|---|---|
| `enabled` | true | 是否启用检测 |
| `same_message_only` | false | true=只统计同一条消息；false=统计任意消息条数 |
| `only_chat_messages` | true | 只统计聊天消息 |
| `window_seconds` | 5 | 统计窗口（秒） |
| `max_messages` | 10 | 达到多少条触发禁言 |
| `text_normalize` | true | 忽略大小写/空白 |
| `mute_seconds` | 600 | 禁言时长（秒），0 表示只计数不实际禁言 |
| `cooldown_seconds` | 30 | 同一用户触发后的冷却 |
| `notify` | true | 触发后是否播报 |
| `notify_template` | 见下 | 播报文案模板 |
| `manage_permission` | both | 谁可以改本群设置 |
| `manage_users` | [] | 额外可管理用户 ID |
| `exempt_group_admins` | true | 群主/群管理员豁免检测 |

> 豁免说明：插件**只有一个豁免**——群主 / 群管理员（刷屏类插件的通行做法，且机器人本身也禁言不了群主）。
> 不提供机器人管理员（AstrBot `admins_id`）豁免，也没有免检测白名单：只要不是群主/群管理员，谁刷屏都会计数、都会禁言。

默认播报文案：

```
{at} 你在 {window} 秒内发送了 {count} 条消息，达到刷屏阈值：{mute_text}。
```

`{mute_text}` 成功时为「已被禁言 10 分钟」这类文案；失败时不会播报（只记 WARNING 日志）。

占位符：`{at} {user} {user_id} {nickname} {group_id} {count} {window} {mute} {mute_text}`

## 平台支持

| 平台 | 禁言 | 说明 |
|---|---|---|
| `aiocqhttp`（OneBot v11 / NapCat 等） | ✅ | `event.bot.call_action("set_group_ban", ...)` |
| 其他平台 | ❌ | 仅计数；禁言失败时群里静默，日志留 WARNING；可在 `_mute()` 中扩展 |

## 安装

1. 把本仓库放到 `AstrBot/data/plugins/astrbot_plugin_flood_guard/`，或在 WebUI 从 zip 安装。
2. 在 WebUI 插件管理里启用并配置。
3. 确保机器人在目标群里是**群主或管理员**。

## 发布到官方插件市场

> AstrBot 官方说明：旧仓库 `AstrBotDevs/AstrBot_Plugins_Collection` **已废弃**，现在统一在
> **[https://cloud.astrbot.app/publish](https://cloud.astrbot.app/publish)** 提交（需要注册 AstrBot Cloud 账号）。

1. 插件已推送到 GitHub 仓库：`https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard`
2. 打开 [https://cloud.astrbot.app/publish](https://cloud.astrbot.app/publish)，注册/登录。
3. 填写插件仓库地址，提交。
4. 平台会自动解析 `metadata.yaml`（name / display_name / desc / version / author / repo / astrbot_version / support_platforms / tags），CI 校验通过后收录。
5. **后续更新**：改 `metadata.yaml` 的 `version` 并 push 到 `main` 即可；`author` 与 `name` 不要改（`plugin_id = author/name`，改了会被当成新插件）。

注意事项（来自官方文档）：

- 插件 zip **不得超过 16MB**（本插件约 20KB，远低于限制）。
- 仓库里不要包含 `.git`、`__pycache__`、`node_modules` 等无关文件（本仓库已配 `.gitignore`）。
- 在 `metadata.yaml` 里声明 `support_platforms` 与 `tags`，便于市场分类与搜索（已配置）。

## License

MIT
