---
name: UCE ScoreboardView / LiveGameView / _TeamGameView
description: How the scoreboard view classes relate and the dynamic rebuild pattern
---

ScoreboardView uses a `_rebuild()` method that clears and re-adds all items on every state change. Static `@discord.ui.button` decorators were replaced because the live-game Select (row 3) is conditional — it only appears when `in_progress` games exist.

`_TeamGameView` and `LiveGameView` hold a reference to the parent `ScoreboardView` and call `parent._rebuild()` + `interaction.response.edit_message(view=parent)` to navigate back. These classes are defined AFTER `ScoreboardView` in the source file — Python resolves them at call time (not definition time) so forward references are fine.

**Why:** Discord's Select component can't be shown/hidden; the whole item list must be rebuilt each time. Using `_rebuild()` instead of `@decorator` buttons is the pattern for conditional rows.

**How to apply:** Any new views that need conditional rows should use the same `clear_items()` + `add_item()` pattern inside a `_rebuild()` method.
