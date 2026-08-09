"""
Smoke tests: verify all declared runtime dependencies and every first-party
module can be imported without error.

Dependency names are derived directly from pyproject.toml so that adding a
new package to the manifest automatically flags it here if the install fails.
Internal modules are enumerated exhaustively so a missing file is caught
before it reaches production.
"""
import importlib
import pathlib
import re
import sys

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Distribution name → importable module name, only where they differ.
_DIST_TO_IMPORT: dict[str, str] = {
    "beautifulsoup4": "bs4",
    "discord-py":     "discord",
    "python-dotenv":  "dotenv",
    "pytest-asyncio": "pytest_asyncio",
}


def _parse_dependencies() -> list[tuple[str, str]]:
    """
    Read [project.dependencies] from pyproject.toml and return
    [(dist_name, import_name), ...].

    Uses the stdlib tomllib (Python 3.11+) so no extra dependency is needed.
    """
    import tomllib  # stdlib in Python 3.11+

    toml_path = pathlib.Path(__file__).parent.parent / "pyproject.toml"
    with toml_path.open("rb") as fh:
        data = tomllib.load(fh)

    deps: list[tuple[str, str]] = []
    for spec in data["project"]["dependencies"]:
        # Strip version specifiers: "aiohttp>=3.13.3" → "aiohttp"
        dist_name = re.split(r"[><=!~\[]", spec)[0].strip()
        import_name = _DIST_TO_IMPORT.get(dist_name, dist_name.replace("-", "_"))
        deps.append((dist_name, import_name))
    return deps


def _discover_internal_modules() -> list[str]:
    """
    Walk the ai/ and features/ packages and return every importable module
    path (e.g. "ai.cache", "features.announcements.db").
    Excludes __init__ files (they load automatically as part of the package).
    """
    root = pathlib.Path(__file__).parent.parent
    modules: list[str] = []

    for pkg_dir in ["ai", "features"]:
        for py_file in sorted((root / pkg_dir).rglob("*.py")):
            rel = py_file.relative_to(root)
            parts = list(rel.with_suffix("").parts)
            if parts[-1] == "__init__":
                # Still import the package itself, not the __init__ file
                mod = ".".join(parts[:-1])
            else:
                mod = ".".join(parts)
            if mod not in modules:
                modules.append(mod)

    return modules


# ---------------------------------------------------------------------------
# Third-party dependency smoke tests (derived from pyproject.toml)
# ---------------------------------------------------------------------------

THIRD_PARTY_DEPS = _parse_dependencies()


@pytest.mark.parametrize("dist_name,import_name", THIRD_PARTY_DEPS)
def test_third_party_import(dist_name: str, import_name: str) -> None:
    """Every declared pyproject.toml dependency must be importable."""
    try:
        importlib.import_module(import_name)
    except ImportError as exc:
        pytest.fail(
            f"Dependency '{dist_name}' (import: '{import_name}') is not "
            f"installed or is broken: {exc}"
        )


# ---------------------------------------------------------------------------
# Internal module smoke tests (exhaustive discovery)
# ---------------------------------------------------------------------------

INTERNAL_MODULES = _discover_internal_modules()


@pytest.mark.parametrize("module_path", INTERNAL_MODULES)
def test_internal_module_import(module_path: str) -> None:
    """Every first-party module must be importable without crashing."""
    try:
        importlib.import_module(module_path)
    except ImportError as exc:
        pytest.fail(
            f"Internal module '{module_path}' could not be imported "
            f"(missing dependency or broken import): {exc}"
        )
    except Exception as exc:
        pytest.fail(
            f"Internal module '{module_path}' raised {type(exc).__name__} "
            f"on import: {exc}"
        )


# ---------------------------------------------------------------------------
# Application entrypoint smoke test
# ---------------------------------------------------------------------------

def test_main_module_importable() -> None:
    """
    main.py must be importable (all top-level imports resolve) without
    starting the bot or requiring a live DISCORD_TOKEN.

    The module-level startup is guarded by `if __name__ == '__main__':`
    so importing it here is safe.
    """
    # Remove any cached copy so this test is always a fresh import check
    sys.modules.pop("main", None)
    try:
        importlib.import_module("main")
    except ImportError as exc:
        pytest.fail(f"main.py has an unresolvable import: {exc}")
    except RuntimeError as exc:
        # A RuntimeError about DISCORD_TOKEN means startup code ran — guard missing
        if "DISCORD_TOKEN" in str(exc):
            pytest.fail(
                "main.py startup code ran during import. "
                "Ensure the bot launch block is inside `if __name__ == '__main__':`"
            )
        raise
