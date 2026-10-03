# astrbot_plugin_flood_guard（刷屏守卫）

AstrBot 群刷屏检测与自动禁言插件。**默认是「复读机模式」：同一条消息在窗口内重复达到阈值才触发禁言。**
阈值 / 窗口 / 禁言时长 / 播报文案既能在**插件配置页**改，也能由**群管理员在 QQ 群内**对单个群覆盖。

## 权限模型（重要）

AstrBot 内置的 `PermissionType.ADMIN` **只认机器人全局管理员（`admins_id`）**，
不认群主/群管理员；而且挂在「指令组子指令」上的 `event_filters` 在唤醒阶段会被跳过。
所以本插件**不依赖框架的权限装饰器**，而是在每个修改类指令里做显式校验：

| `manage_permission` | 含义 |
|---|---|
| `both`（默认） | 群主/群管理员 **或** 机器人管理员 |
| `group_admin` | 仅群主/群管理员 |
| `astrbot_admin` | 仅机器人管理员（AstrBot `admins_id`） |
| `everyone` | 所有人（不推荐） |

- 判定群身份读的是平台原始事件 `raw_message.sender.role`（`owner`/`admin`），比 `event.role` 可靠（后者只对 `admins_id` 生效）。
- `manage_users` 可额外指定永远可管理本群设置的用户 ID。
- **查看类指令**（`/刷屏 状态`、`/刷屏 帮助`）对所有人生效；**修改类指令**（阈值/窗口/禁言/提示/重置）走上面的策略。

## 检测语义

| 配置 | 默认 | 行为 |
|---|---|---|
| `same_message_only` | `true` | **同一条内容**重复达到阈值才触发 |
| `only_chat_messages` | `true` | 只统计真正的聊天消息，忽略撤回/管理变更/入群等 notice |
| `text_normalize` | `true` | 文本比对忽略大小写与空白 |

关掉 `same_message_only` 就退回「窗口内任意 N 条消息即触发」。

### 「同一条」怎么判定

对消息链里的**内容段**做归一化签名，忽略 `Reply` 等上下文段：

| 段类型 | 签名 |
|---|---|
| 文本 `Plain` | 去空白 + 转小写 |
| 图片 `Image` | `file`（优先）或 `url` |
| 表情 `Face` | 表情 id |
| 语音/视频/文件 | `file` / `url` |
| 卡片 `Json` / `Share` / 音乐 / 位置 | `data` 原文 |
| 戳一戳 `Poke` | poke id |
| 合并转发 | 转发 id |

多个段会拼成 `a|b|c`，所以「同一句话 + 同一张图」才算同一条。

## 插件配置页（全局默认）

| 配置项 | 默认 | 说明 |
|---|---|---|
| `enabled` | true | 是否启用检测 |
| `same_message_only` | true | 只统计同一条消息的重复 |
| `only_chat_messages` | true | 只统计聊天消息（过滤 notice 噪声） |
| `window_seconds` | 5 | 统计窗口（秒） |
| `max_messages` | 10 | 同一条消息重复多少条触发 |
| `text_normalize` | true | 文本比对忽略大小写/空白 |
| `mute_seconds` | 600 | 禁言时长（秒），0 表示只播报不禁言 |
| `cooldown_seconds` | 30 | 同一用户触发后的冷却 |
| `notify` | true | 触发后是否播报 |
| `notify_template` | 见下 | 播报文案模板 |
| `manage_permission` | both | 谁可以改本群设置 |
| `manage_users` | [] | 额外可管理用户 ID |
| `exempt_admins` | true | 机器人管理员豁免检测 |
| `exempt_group_admins` | true | 群主/群管理员豁免检测 |
| `whitelist` | [] | 免检测用户 ID |

## 群内指令

| 指令 | 权限 | 作用 |
|---|---|---|
| `/刷屏 帮助` | 所有人 | 查看用法 |
| `/刷屏 状态` | 所有人 | 查看本群生效配置 |
| `/刷屏 阈值 <条数>` | 管理员 | 同一条消息重复多少条触发 |
| `/刷屏 窗口 <秒>` | 管理员 | 统计窗口 |
| `/刷屏 禁言 <秒>` | 管理员 | 禁言时长 |
| `/刷屏 提示 <文案>` | 管理员 | 播报文案 |
| `/刷屏 重置` | 管理员 | 清除本群覆盖，回退全局默认 |

> 「管理员」= 由 `manage_permission` 决定；无权限会直接回复拒绝提示。

## 播报文案占位符

| 占位符 | 含义 |
|---|---|
| `{at}` | @触发者（消息组件，不在文本里） |
| `{user}` / `{nickname}` | 触发者昵称 |
| `{user_id}` | 触发者 QQ |
| `{group_id}` | 群号 |
| `{count}` | 窗口内**同一条消息**的重复次数 |
| `{window}` | 统计窗口（秒） |
| `{mute}` | 禁言秒数 |
| `{mute_text}` | 人类可读禁言时长（如「10 分钟」）；失败时为「（禁言失败）」 |

默认模板：

```
{at} 你在 {window} 秒内发送了 {count} 条相同消息，达到阈值，已被禁言 {mute_text}。
```

## 触发逻辑

```
群消息事件
  ├─ 开关关 / 机器人自己 → 忽略
  ├─ 机器人管理员豁免 / 群主管理员豁免 / 白名单 → 忽略
  ├─ only_chat_messages 且非聊天消息（notice 等） → 忽略
  ├─ 冷却中 → 忽略
  ├─ 计算「相同消息」签名，往该签名的 deque 记时间戳
  ├─ 弹出窗口外的旧记录
  └─ 该签名的记录数 ≥ 阈值 → 清空该用户窗口 + 冷却 + 禁言 + 播报
```

## 平台支持

| 平台 | 禁言 | 说明 |
|---|---|---|
| `aiocqhttp`（OneBot v11 / NapCat 等） | ✅ | `event.bot.call_action("set_group_ban", ...)` |
| 其他平台 | ❌ | 未实现时仅计数 + 播报，日志会给出警告；可在 `_mute()` 中按平台扩展 |

## 安装

1. 把本仓库放到 AstrBot 的 `data/plugins/astrbot_plugin_flood_guard/`，或在 WebUI 从 zip 安装。
2. 在 WebUI 插件管理里启用并配置。
3. 机器人在目标群里需要是**管理员**，否则禁言会失败（日志会有提示）。

## License

MIT
