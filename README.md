# astrbot_plugin_flood_guard（刷屏守卫）

AstrBot 群刷屏检测与自动禁言插件。默认是**复读机模式**：**同一条消息**在时间窗口内重复达到上限才触发禁言。

阈值 / 窗口 / 禁言时长 / 播报文案，既可在**插件配置页**修改，也可由**群管理员在 QQ 群内**用命令对单个群单独覆盖。

> 语言约定：**插件命令为英文**；**说明文档与群内回复为中文**。

## 命令（单一扁平命令，英文）

在群里必须先**唤醒机器人**：使用唤醒前缀（默认 `/`）或 **@ 机器人**，然后再跟命令。

| 命令 | 权限 | 作用 |
|---|---|---|
| `/flood` 或 `/flood status` | 所有人 | 查看本群生效配置（也能验证插件是否加载成功） |
| `/flood help` | 所有人 | 用法说明 |
| `/flood limit <数字>` | 管理员 | 同一条消息重复多少条触发禁言 |
| `/flood window <秒>` | 管理员 | 统计窗口长度 |
| `/flood mute <秒>` | 管理员 | 禁言时长 |
| `/flood notice <文案>` | 管理员 | 本群播报文案 |
| `/flood reset` | 管理员 | 清除本群覆盖，回退全局默认 |

示例：

```
/flood limit 5
/flood window 5
/flood mute 600
/flood notice {at} 别复读了，禁言 {mute_text}
```

### 为什么用单一扁平命令

AstrBot 的**指令组 + 子指令**由框架预编译的指令树分发，且子指令处理器的过滤器在唤醒阶段会被跳过，导致触发不稳定、权限也可能失效。改成单一扁平命令 + 手动解析子命令后，跨版本可靠性高很多。

## 排障：群里发了命令没反应

1. **先唤醒机器人。** 群聊里 AstrBot 会忽略普通消息：请用 `/flood`（唤醒前缀 `/`）或 **@ 机器人** 再发命令。前缀可在 AstrBot 设置里修改。
2. **插件是否已加载？** 裸发 `/flood` 一定会返回状态；完全没反应说明插件没加载，去 AstrBot 日志里找 import 报错。
3. **版本门槛。** `metadata.yaml` 要求 `astrbot_version: ">=4.0,<5"`；版本不匹配会在启动前直接拒绝加载，请按你的实际版本调整该行。
4. **禁言失败？** 机器人在该群必须是**管理员**，否则 `set_group_ban` 会失败，日志出现 `[flood_guard] mute failed`。

## 权限模型

AstrBot 内置的 `PermissionType.ADMIN` **只认机器人全局管理员（`admins_id`）**，不认群主/群管理员；且子指令的 `event_filters` 在唤醒阶段被跳过。因此本插件在每个修改类操作里**显式校验**：

| `manage_permission` | 含义 |
|---|---|
| `both`（默认） | 群主/群管理员 **或** 机器人管理员 |
| `group_admin` | 仅群主/群管理员 |
| `astrbot_admin` | 仅机器人管理员 |
| `everyone` | 所有人（不推荐） |

`manage_users` 可额外指定永久可管理本群设置的用户 ID。
只读操作（`status`、`help`）对所有人生效。

## 检测语义

| 配置 | 默认 | 行为 |
|---|---|---|
| `same_message_only` | `true` | 只有**同一条消息**重复达到上限才触发 |
| `only_chat_messages` | `true` | 忽略撤回/管理变更/入群/戳一戳等 notice 事件 |
| `text_normalize` | `true` | 文本比对忽略大小写与空白 |

### 「同一条」如何判定

对消息链里的**内容段**归一化生成签名，忽略 `Reply` 这类上下文段：

| 段类型 | 签名 |
|---|---|
| 文本 | 去空白 + 转小写 |
| 图片 | `file`（优先）或 `url` |
| 表情 | 表情 id |
| 语音/视频/文件 | `file` / `url` |
| 卡片 / 分享 / 音乐 / 位置 | `data` |
| 戳一戳 | poke id |
| 合并转发 | 转发 id |

多个段会拼接为 `a|b|c`，因此「同一句话 + 同一张图」才算同一条。

## 配置项

| 配置项 | 默认 | 说明 |
|---|---|---|
| `enabled` | true | 是否启用检测 |
| `same_message_only` | true | 复读机模式 |
| `only_chat_messages` | true | 只统计聊天消息 |
| `window_seconds` | 5 | 统计窗口（秒） |
| `max_messages` | 10 | 触发禁言的重复条数 |
| `text_normalize` | true | 忽略大小写/空白 |
| `mute_seconds` | 600 | 禁言时长（秒），0 表示只播报不禁言 |
| `cooldown_seconds` | 30 | 同一用户触发后的冷却 |
| `notify` | true | 触发后是否播报 |
| `notify_template` | 见下 | 播报文案模板 |
| `manage_permission` | both | 谁可以改本群设置 |
| `manage_users` | [] | 额外可管理用户 ID |
| `exempt_admins` | true | 机器人管理员豁免检测 |
| `exempt_group_admins` | true | 群主/群管理员豁免检测 |
| `whitelist` | [] | 免检测用户 ID |

默认播报文案：

```
{at} 你在 {window} 秒内发送了 {count} 条相同消息，达到上限，已被禁言 {mute_text}。
```

占位符：`{at} {user} {user_id} {nickname} {group_id} {count} {window} {mute} {mute_text}`

## 平台支持

| 平台 | 禁言 | 说明 |
|---|---|---|
| `aiocqhttp`（OneBot v11 / NapCat 等） | ✅ | `event.bot.call_action("set_group_ban", ...)` |
| 其他平台 | ❌ | 仅计数 + 播报，日志会有警告；可在 `_mute()` 中扩展 |

## 安装

1. 把本仓库放到 `AstrBot/data/plugins/astrbot_plugin_flood_guard/`，或在 WebUI 从 zip 安装。
2. 在 WebUI 插件管理里启用并配置。
3. 确保机器人在目标群里是**管理员**。

## License

MIT
