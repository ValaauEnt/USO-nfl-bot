---
name: UCE gamelog season labels
description: How extract_stats_from_gamelog tags entries with season type and deduplicates
---

`extract_stats_from_gamelog` iterates ESPN's `seasonTypes` → `categories` → `events`. The same event can appear in multiple stat categories (passing, rushing, receiving for the same game). 

Fix applied: `seen_evt_ids: set` tracks `event.get("eventId")` and skips duplicates. Each entry gets `season_label = st.get("displayName", "Season")`.

Fallback (flat `events` list, no seasonTypes): entries get `season_label = "Season"`.

Empty result sentinel: `{"title": "Game Log", "value": "No game log data available.", "season_label": "Season"}`.

**Why:** Without deduplication, a game with passing + rushing stats produced 2+ entries with the same date/opponent but different stats. With season labels, `GameLogView` and `SeasonStatsView` can filter by season type.

**How to apply:** Any new code reading gamelog entries should expect `season_label` on every entry. The `GameLogView._seasons` dict groups by this label for the season-selector buttons.
