---
name: UCE tracker/interactive-message ownership
description: Ownership of components spawned from shared messages must belong to the interacting user, not the original command invoker
---
When a shared/public message (e.g. scoreboard) lets any member spawn a new resource (e.g. a live tracker), set its owner_id from the *interaction* user who clicked, not from the command invoker stored on the parent view.
**Why:** A completion review rejected the tracker system because owner_id fell back to the scoreboard poster, so tracker creators couldn't end their own trackers.
**How to apply:** Any new button/select on a shared view that creates something ownable — take `interaction.user.id`; test with poster ≠ clicker.
