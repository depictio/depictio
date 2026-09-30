"""Agent tool modules. Each one registers its tools with ``@agent_tool`` on import.

``registry.ensure_tools_loaded`` imports them by name, so a module whose
dependencies are missing is skipped without taking the others down.
"""
