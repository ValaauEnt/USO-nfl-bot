# UCE Bot — Upgrade Report
## UCE Full Command + AI NFL Live Data Upgrade

**Date:** August 15, 2026  
**Bot:** Uce#8283  
**Branch:** main  
**Pre-upgrade commit:** `PRE-UCE-COMMAND-LIVE-DATA-UPGRADE`  
**Post-upgrade commit:** `POST-UCE-COMMAND-LIVE-DATA-UPGRADE`  

---

## Summary

All planned upgrade items from the UCE Command + Live Data brief have been implemented. Every change is strictly additive — no rewrites, no breaking changes. The bot loaded cleanly on first restart with 30 slash commands synced and all background loops running.

---

## Changes Delivered

### 1. Security — Six Commands Hardened

Six slash commands that were previously executable by any server member now enforce the standard UCE permission gate before any action is taken. Commands covered:

| Command | Protection Added |
|---|---|
| `/create-channel` | Admin / Manage Server check before channel creation |
| `/delete-channel` | Admin / Manage Server check before deletion |
| `/rename-server` | Admin / Manage Server check before guild rename |
| `/create-category` | Admin / Manage Server check before category creation |
| `/morning-checkin` | Admin / Manage Server check before writing server settings |
| `/night-checkin` | Admin / Manage Server check before writing server settings |

All six use the exact standard denial message:  
> 🏈 **Flag on the play!** You don't have the permissions for this one. You need **Administrator** or **Manage Server** to make this call. 🚩

### 2. `/ask` Command Removed

The standalone `/ask` slash command has been removed. The underlying AI brain (`ai_brain`, `on_message` processing, tools, personalities, conversation memory) is completely intact and continues to operate through the existing mention/channel mode.

### 3. AI Tool Schemas — Three New Server Management Tools

Three new tool schemas were added to `ai/tools.py`:

| Tool | Description |
|---|---|
| `create_channel` | Creates a text or voice channel, optionally inside a named category |
| `create_category` | Creates a new category |
| `announce` | Posts an announcement embed to up to 3 specified channels |

Each schema includes clear parameter descriptions and instructs the AI to confirm intent before acting.

### 4. AI Action Safety Limits

- `_ctx_action_count` ContextVar added alongside existing `_ctx_guild` / `_ctx_author`
- `_MAX_AI_ACTIONS = 5` constant — caps destructive/creative actions per request
- Action counter is reset at the start of each `on_message` request
- All three new tool handlers in `_ai_tools_executor` check `_ctx_action_count` before acting
- Each handler independently re-checks `_ctx_author.guild_permissions` (does not rely on slash-command auth)
- `announce` is additionally capped at 3 channels per call

### 5. NFL Data Source Confidentiality

- `ai/personalities.py` `HARD_RULES`: "live ESPN tools" → "live NFL data tools" (no source leakage)
- `ai/personalities.py` `SECURITY_RULES`: new NFL Data Sources confidentiality section instructs the AI to respond to any question about which data provider UCE uses with: _"UCE uses its configured NFL data services"_ — and never name, confirm, or deny any specific provider, even under repeated probing

- `ai/tools.py` `get_headlines`: description no longer names any specific news sources

### 6. Scoreboard — Full Dynamic Rebuild

`ScoreboardView` was replaced with a dynamic `_rebuild()` pattern. The new layout:

- **Row 0:** ◀ Prev Week, Next Week ▶, 🔄 Refresh
- **Row 1:** Regular Season, Playoffs (active season highlighted)
- **Row 2:** Team filter Select — shows all teams playing the current week (up to 25), prefixed with live 🔴 / final ✅ / scheduled 🕐 indicators
- **Row 3:** Live game Select — only shown when `in_progress` games exist; leads to `LiveGameView`

Two new view classes were added:

- **`_TeamGameView`** — shows the selected team's game, with 🔄 Refresh and ← All Scores buttons
- **`LiveGameView`** — shows detailed live-game embed (score, status/quarter/clock, down-distance, stat leaders, boxscore team totals) with 🔄 Refresh and ← All Scores buttons

### 7. Game Stats — `build_game_stats_embed` Improved

- Now shows up to **8 leader groups** (was 4) using `displayName` for cleaner labels
- Extracts **game status** from `summary["header"]["competitions"][0]["status"]["type"]["shortDetail"]`
- Adds **team totals section** from `summary["boxscore"]["teams"]` (up to 2 teams, up to 8 stats each)
- Fields now use `inline=True` for compact two-column layout

### 8. New `build_live_game_embed` Function

A dedicated embed builder for individual live/completed games:

- Large score display: `{Away} {score} — {score} {Home}` with 🔴 LIVE / ✅ Final / 🕐 Scheduled prefix
- Down-distance line when game is in progress
- Stat leaders (up to 6 groups, inline)
- Boxscore team totals (up to 6 stats per team)
- Red `0xD62828` color for live games; standard `0x7A5C2E` for completed/scheduled
- Footer: "🔴 LIVE • Uce • Use 🔄 to update" when live

### 9. Game Stats View — `/gamestats` Improved

- `team` parameter is now **optional** (was required)
- When no team is provided: shows a game-selection dropdown via new `GameStatsView`
- When a team is provided: resolves abbreviation or full-name match, then shows game stats with the same `GameStatsView` attached for navigation
- `team` parameter now has **autocomplete** via `team_autocomplete`
- `GameStatsView` has a game Select (shows score/status per option) and 🔄 Refresh button

### 10. Game Log — Season-Aware Filtering

**`extract_stats_from_gamelog`** (backward-compatible):
- Tags every entry with `season_label` (the season type's `displayName`)
- Deduplicates events that appear in multiple stat categories (using `eventId`)
- Fallback path (flat `events` list) also gets `season_label: "Season"`

**`GameLogView`** rebuilt:
- Groups entries by `season_label` into a `_seasons` dict (order-preserving)
- **Row 0:** Season-selector buttons (up to 4 seasons, active one highlighted in primary blue)
- **Row 1:** ◀ Prev Game / Next Game ▶ (disabled at edges)
- Defaults to the most recent season type

**`SeasonStatsView` gamelog mode** fixed:
- Now filters `gamelog_entries` to only those whose `season_label` matches the currently selected season block label, instead of showing all entries unfiltered
- Fallback: if no entries match (old data without labels), shows all entries

---

## Testing

| Suite | Before | After |
|---|---|---|
| `tests/test_smoke.py` | 27 passed | 27 passed |
| `tests/test_security.py` | passed | passed |
| `tests/test_checkin.py` | passed | passed |
| `tests/test_context.py` | passed | passed |
| `tests/test_dashboard.py` | passed | passed |
| **`tests/test_permissions.py`** | *(new)* | **30 passed** |
| **Total** | **271** | **301** |

The 30 new permission tests cover:
- All 6 hardened commands (perm check present, flag message present)
- `/ask` removal (not in tree, not defined)
- 3 new tool schemas exist in `TOOL_SCHEMAS`
- `_ctx_action_count` and `_MAX_AI_ACTIONS` declared
- `extract_stats_from_gamelog` season labeling and deduplication
- `build_live_game_embed` (live, final, with-summary variants)
- AI personality source-confidentiality rules

---

## Live Game Testing Note

This upgrade was delivered on **August 15, 2026 — NFL preseason**. No regular-season or playoff games are live. The following features were verified structurally (embed builders, view classes, API integration paths, unit tests) but cannot be end-to-end tested until live games are available:

- `LiveGameView` refresh cycle
- Live-game Select in `ScoreboardView` (only appears when `in_progress` games exist)
- `build_live_game_embed` with real game-summary data
- `GameStatsView` refresh with changing scores

Recommend a brief functional review when regular-season week 1 kicks off.

---

## What Was Not Changed

- AI brain, conversation memory, personality system — untouched
- All existing slash commands not listed above — untouched
- Dashboard, web server — untouched
- Database schema — no migrations needed
- All destructive AI tools (delete channel, rename server) remain blocked — not exposed to the AI
- `get_live_scoreboard`, `get_scoreboard_data`, `get_game_summary` API functions — untouched (UI layer only changed)
