# astrbot_plugin_flood_guard (Flood Guard)

An AstrBot plugin that detects message flooding and mutes automatically.
Default mode is **repeater mode**: the *same* message repeated within a window triggers the mute.

Limits / window / mute duration / notice text can be set on the **plugin config page**,
or overridden per group inside QQ by **group admins** via the **single flat command** below.

## Commands (single flat command, English only)

In group chats the bot must be woken first: use the **wake prefix** (default `/`) or **@ the bot**.

| Command | Who | Meaning |
|---|---|---|
| `/flood` or `/flood status` | everyone | show this group's effective config (also proves the plugin loaded) |
| `/flood help` | everyone | usage |
| `/flood limit <n>` | admin | repeats of the same message that trigger a mute |
| `/flood window <s>` | admin | counting window, seconds |
| `/flood mute <s>` | admin | mute duration, seconds |
| `/flood notice <text>` | admin | per-group notice template |
| `/flood reset` | admin | drop this group's overrides |

> Examples: `/flood limit 5` , `/flood notice {at} stop repeating, muted for {mute_text}`

### Why a single flat command

AstrBot's command **groups** with sub-commands are dispatched by the framework's precompiled
command tree, and filters attached to sub-command handlers are skipped during the waking
stage. A single flat command with manual sub-command parsing is far more reliable across
AstrBot versions.

## Troubleshooting "the bot does not respond in my QQ group"

1. **Wake the bot.** In groups, AstrBot ignores plain messages. Send `/flood` (wake prefix `/`)
   or **@ the bot** then the command. The prefix is configurable in AstrBot settings.
2. **Is the plugin enabled and loaded?** Bare `/flood` always replies with the status block.
   If nothing happens, the plugin is not loaded — check the AstrBot log for import errors.
3. **Version gate.** `metadata.yaml` requires `astrbot_version: ">=4.0,<5"`. If you run a
   different major version, adjust this line or the plugin will be rejected before startup.
4. **Mute fails?** The bot must be an **admin in that group**; otherwise `set_group_ban` fails
   and the log shows `[flood_guard] mute failed`.

## Permissions

AstrBot's built-in `PermissionType.ADMIN` only matches **bot-wide admins** (`admins_id`), not
group owner/admins, and sub-command `event_filters` are skipped while waking. This plugin
therefore checks permissions explicitly:

| `manage_permission` | Meaning |
|---|---|
| `both` (default) | group owner/admins **or** bot admins |
| `group_admin` | group owner/admins only |
| `astrbot_admin` | bot admins only |
| `everyone` | anyone (not recommended) |

`manage_users` adds extra user IDs that may always manage a group.
Read-only actions (`status`, `help`) stay open to everyone.

## Detection semantics

| Config | Default | Behaviour |
|---|---|---|
| `same_message_only` | `true` | trigger only when the **same message** repeats to the limit |
| `only_chat_messages` | `true` | ignore notice events (recall, admin changes, joins, poke) |
| `text_normalize` | `true` | ignore case/whitespace when comparing text |

### How "same message" is computed

Content segments are normalised into a signature; context segments (`Reply`) are ignored:

| Segment | Signature |
|---|---|
| Text | whitespace stripped + lowercased |
| Image | `file` (preferred) or `url` |
| Face | face id |
| Record/Video/File | `file` / `url` |
| Card / Share / Music / Location | `data` |
| Poke | poke id |
| Forward | forward id |

Multiple segments are joined (`a|b|c`), so "same text + same image" counts as the same message.

## Config reference

| Key | Default | Meaning |
|---|---|---|
| `enabled` | true | enable detection |
| `same_message_only` | true | repeater mode |
| `only_chat_messages` | true | chat messages only |
| `window_seconds` | 5 | counting window |
| `max_messages` | 10 | repeats that trigger |
| `text_normalize` | true | ignore case/whitespace |
| `mute_seconds` | 600 | mute duration (0 = notify only) |
| `cooldown_seconds` | 30 | per-user cooldown after triggering |
| `notify` | true | post a notice when triggered |
| `notify_template` | see below | notice template |
| `manage_permission` | both | who may change group settings |
| `manage_users` | [] | extra allowed user IDs |
| `exempt_admins` | true | bot admins exempt from detection |
| `exempt_group_admins` | true | group owner/admins exempt from detection |
| `whitelist` | [] | user IDs exempt from detection |

Default notice template (English):

```
{at} You sent the same message {count} times in {window}s, which hit the limit, so you have been muted for {mute_text}.
```

Placeholders: `{at} {user} {user_id} {nickname} {group_id} {count} {window} {mute} {mute_text}`

## Platform support

| Platform | Mute | Notes |
|---|---|---|
| `aiocqhttp` (OneBot v11 / NapCat) | ✅ | `event.bot.call_action("set_group_ban", ...)` |
| others | ❌ | counts + notifies only; extend `_mute()` per platform |

## Install

1. Copy this repo into `AstrBot/data/plugins/astrbot_plugin_flood_guard/`, or install the zip from the WebUI.
2. Enable and configure it in the WebUI.
3. Make sure the bot is an **admin** in the target group.

## License

MIT
