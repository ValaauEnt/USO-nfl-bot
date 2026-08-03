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
            "description": "Get the latest NFL news headlines from ESPN, Pro Football Talk, and Yahoo Sports.",
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
    # ── Phase 1: Server Management tools ─────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_server_roles",
            "description": (
                "List all roles in the current Discord server. "
                "Call this FIRST when an admin asks about auto-roles so you can resolve "
                "role names to IDs. Returns each role's id, name, and position."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_server_config",
            "description": (
                "Read the current server management configuration: "
                "auto_roles, welcome_enabled, welcome_message, goodbye_enabled, goodbye_message. "
                "Call this when an admin asks what the current settings are."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_server_config",
            "description": (
                "Update server management settings. "
                "ONLY call this AFTER the admin has confirmed the change. "
                "All fields are optional — only include what needs to change."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "auto_role_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of role IDs to auto-assign to new members. Replaces existing list.",
                    },
                    "clear_auto_roles": {
                        "type": "boolean",
                        "description": "Set true to remove all auto-role assignments.",
                    },
                    "welcome_enabled": {
                        "type": "boolean",
                        "description": "Enable or disable welcome messages.",
                    },
                    "welcome_message": {
                        "type": "string",
                        "description": "Welcome message template. Supports {user}, {server}, {memberCount}.",
                    },
                    "goodbye_enabled": {
                        "type": "boolean",
                        "description": "Enable or disable goodbye messages.",
                    },
                    "goodbye_message": {
                        "type": "string",
                        "description": "Goodbye message template. Supports {user}, {server}, {memberCount}.",
                    },
                },
                "required": [],
            },
        },
    },
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
