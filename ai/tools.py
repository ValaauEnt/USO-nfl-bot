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
]
