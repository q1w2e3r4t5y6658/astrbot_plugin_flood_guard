# astrbot_plugin_flood_guard（刷屏守卫）

AstrBot 群刷屏检测与自动禁言插件。**默认是「复读机模式」：同一条消息在窗口内重复达到阈值才触发禁言。**
阈值 / 窗口 / 禁言时长 / 播报文案既能在**插件配置页**改，也能在 **QQ 群内**用指令对**单个群**覆盖。

## 检测语义

| 配置 | 默认 | 行为 |
|---|---|---|
| `same_message_only` | `true` | **同一条内容**重复达到阈值才触发 |
| `only_chat_messages` | `true` | 只统计真正的聊天消息，忽略撤回/管理变更/入群等 notice |
| `text_normalize` | `true` | 文本比对忽略大小写与空白 |

关掉 `same_message_only` 就退回「窗口内任意 N 条消息即触发」的旧语义。

### 「同一条」是怎么判定的

对消息链里的**内容段**做归一化签名，忽略 `Reply` 等上下文段：

| 段类型 | 签名 |
|---|---|
| 文本 `Plain` | 去空白 + 转小写后的文本 |
| 图片 `Image` | `file`（优先）或 `url` |
| 表情 `Face` | 表情 id |
| 语音/视频/文件 | `file` / `url` |
| 卡片 `Json` / `Share` / 音乐 / 位置 | `data` 原文 |
| 戳一戳 `Poke` | poke id |
| 合并转发 | 转发 id |

> 一条消息里包含多个段时会拼成一个签名（`a|b|c`），所以「同一张图 + 同一句话」才算同一条。

## 功能

- 时间窗口内**同一条消息**的重复计数，达到阈值触发
- 触发后调用平台禁言接口（aiocqhttp / OneBot v11 的 `set_group_ban`）
- 触发后群内播报，**文案可自定义**（全局 + 单群）
- 同一用户触发后有冷却，避免反复禁言
- 管理员豁免、用户白名单
- 单群覆盖存于插件 KV

## 安装

1. 把本仓库放到 AstrBot 的 `data/plugins/astrbot_plugin_flood_guard/`，或在 WebUI 从 zip 安装。
2. 在 WebUI 插件管理里启用并配置。
3. 机器人在目标群里需要是**管理员**，否则禁言会失败（日志会有提示）。

> 依赖：仅使用 AstrBot 内置能力与 Python 标准库，`requirements.txt` 为空。

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
| `exempt_admins` | true | 管理员豁免 |
| `whitelist` | [] | 免检测用户 ID 列表 |

## 群内指令（单群覆盖）

管理员在群里发送：

| 指令 | 作用 |
|---|---|
| `/刷屏 帮助` | 查看用法 |
| `/刷屏 状态` | 查看本群生效配置 |
| `/刷屏 阈值 <条数>` | 同一条消息重复多少条触发 |
| `/刷屏 窗口 <秒>` | 统计窗口 |
| `/刷屏 禁言 <秒>` | 禁言时长 |
| `/刷屏 提示 <文案>` | 播报文案 |
| `/刷屏 重置` | 清除本群覆盖，回退全局默认 |

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

示例：

```
/刷屏 提示 {at} 别复读了，禁言 {mute_text} 🚫
```

## 触发逻辑

```
群消息事件
  ├─ 开关关 / 机器人自己 / 管理员豁免 / 白名单 → 忽略
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

## 开发

- 入口：`main.py`
- 配置 Schema：`_conf_schema.json`
- 文案：`.astrbot-plugin/i18n/zh-CN.json`、`en-US.json`
- 元数据：`metadata.yaml`

## License

MIT
