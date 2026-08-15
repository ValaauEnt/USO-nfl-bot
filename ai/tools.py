"""
OpenAI function-calling tool schemas.

These are the JSON definitions passed to OpenAI. Actual execution happens
in main.py via the tools_executor callback injected into AIBrain.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_scoreboard",
            "description": "Get the current NFL scoreboard with live scores and game status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_headlines",
            "description": "Get the latest NFL news headlines.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_stats",
            "description": "Get stats and profile for a specific NFL player by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "The player's full or partial name, e.g. 'Patrick Mahomes'",
                    }
                },
                "required": ["player_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_schedule",
            "description": "Get the season schedule and recent results for an NFL team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {
                        "type": "string",
                        "description": "Team abbreviation e.g. KC, DAL, SF, BUF, or full name",
                    }
                },
                "required": ["team"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trade_news",
            "description": "Get current NFL trade news, rumors, and transaction headlines.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_league_leaders",
            "description": "Get current NFL stat leaders for offense and defense.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "coin_flip",
            "description": "Flip a coin — returns heads or tails.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "magic_8_ball",
            "description": "Consult the magic 8-ball for a yes/no question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hot_take",
            "description": "Generate a spicy NFL hot take or controversial opinion.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_user_fact",
            "description": "Remember something about the user for future conversations (nickname, favorite team, preferences, inside jokes, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key":   {"type": "string", "description": "What to remember, e.g. 'nickname', 'favorite_team', 'rival'"},
                    "value": {"type": "string", "description": "The value to store"},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trivia",
            "description": "Ask an NFL trivia question.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # ── Server management tools ────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_server_roles",
            "description": (
                "List all roles in the current Discord server. "
                "Use this before configuring auto-roles to find the correct role name and ID."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_server_config",
            "description": (
                "Read the current server manager configuration: auto-roles, welcome/goodbye "
                "channels, enabled states, and message templates. "
                "Use this to show the admin what is currently configured, or to answer questions "
                "like 'show my welcome channel' or 'what channel do goodbye messages go to'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_server_config",
            "description": (
                "Apply a confirmed server manager configuration change. "
                "ONLY call this tool AFTER the user has explicitly confirmed the proposed change. "
                "Do NOT call this tool proactively — always summarize the change and ask for "
                "confirmation first, then call this once the user says yes. "
                "Can set welcome/goodbye channels by channel name, mention, or ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "auto_roles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of role IDs (as strings) to auto-assign to new members. "
                            "Pass an empty list [] to clear all auto-roles. "
                            "Omit this field to leave auto-roles unchanged."
                        ),
                    },
                    "welcome_enabled": {
                        "type": "boolean",
                        "description": "Enable or disable welcome messages.",
                    },
                    "welcome_message": {
                        "type": "string",
                        "description": (
                            "Custom welcome message. Supports {user}, {server}, {memberCount}. "
                            "Omit to keep the current message."
                        ),
                    },
                    "welcome_channel": {
                        "type": "string",
                        "description": (
                            "Channel where welcome messages are posted. "
                            "Pass the channel name (e.g. 'welcome'), a mention (e.g. '<#123>'), "
                            "or a numeric channel ID string. Pass 'none' to clear."
                        ),
                    },
                    "goodbye_enabled": {
                        "type": "boolean",
                        "description": "Enable or disable goodbye messages.",
                    },
                    "goodbye_message": {
                        "type": "string",
                        "description": (
                            "Custom goodbye message. Supports {user}, {server}, {memberCount}. "
                            "Omit to keep the current message."
                        ),
                    },
                    "goodbye_channel": {
                        "type": "string",
                        "description": (
                            "Channel where goodbye messages are posted. "
                            "Pass the channel name, mention, or numeric ID. Pass 'none' to clear."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    # ── Server creation / announcement tools ──────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "create_channel",
            "description": (
                "Create a new text or voice channel in the Discord server. "
                "ONLY call this after the user has confirmed the channel name and type. "
                "Requires Administrator or Manage Server permission. "
                "To place the channel inside a category, provide category_name matching an existing category."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the new channel, e.g. 'trades' or 'league-news'",
                    },
                    "kind": {
                        "type": "string",
                        "enum": ["text", "voice"],
                        "description": "Channel type: 'text' (default) or 'voice'",
                    },
                    "category_name": {
                        "type": "string",
                        "description": "Exact name of an existing category to place the channel in (optional)",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_category",
            "description": (
                "Create a new channel category in the Discord server. "
                "ONLY call this after the user has confirmed the category name. "
                "Requires Administrator or Manage Server permission. "
                "Returns the created category name and ID so it can be referenced by create_channel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the new category, e.g. 'Madden League'",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "announce",
            "description": (
                "Post an announcement embed to one or more server channels. "
                "ONLY call this after the user has confirmed the message and target channel(s). "
                "Requires Administrator or Manage Server permission. "
                "Limit to 3 channels per call. For multi-channel announcements, confirm the list before calling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The announcement text to post.",
                    },
                    "channels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of channel names, mentions (<#ID>), or numeric IDs to post in. "
                            "Maximum 3 channels per call."
                        ),
                    },
                },
                "required": ["message", "channels"],
            },
        },
    },
    # ── Web search ─────────────────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for CURRENT information not available in the model's training data. "
                "Use this for: Madden news, gaming news, non-ESPN sports news, general current events, "
                "release dates, recent trades or injuries not yet in ESPN, anything from the current year "
                "that the model cannot answer confidently from memory alone. "
                "ALWAYS prefer get_scoreboard / get_headlines / get_player_stats / get_trade_news for NFL — "
                "use web_search only when those tools wouldn't cover it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Specific search query, e.g. 'Madden 26 release date 2026' or 'NFL training camp news July 2026'",
                    }
                },
                "required": ["query"],
            },
        },
    },
]
