"""
claude_cli.py
Uses your Claude subscription as the script writer, with no API key: it runs Claude Code's headless mode
(`claude -p`, the same program you already use) as a subprocess and reads the answer back. Whatever you're logged in
to Claude Code with is what's used - and it counts against that plan's usage limits, so it's opt-in
(USE_CLAUDE_CODE=1 in .env) and meant for the few high-value calls: episode scripts, explainers, series plans.

Startup context is trimmed with flags (no plugins, skills, MCP servers or settings) so a call isn't buried under the
tool descriptions an interactive session loads.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ClaudeCliError(RuntimeError):
    pass


def binary() -> str | None:
    """CLAUDE_BIN, a `claude` on PATH, or the newest copy bundled with the VS Code extension."""
    explicit = os.environ.get("CLAUDE_BIN", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    bundled = sorted(glob.glob(str(Path.home() / ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude")))
    return bundled[-1] if bundled else None


def enabled() -> bool:
    return os.environ.get("USE_CLAUDE_CODE", "").strip().lower() in ("1", "true", "yes") and binary() is not None


def chat_json(system: str, user: str, model: str | None = None, timeout: int = 420) -> dict:
    cmd = [binary(), "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config", "--disable-slash-commands",
           "--no-chrome", "--setting-sources", "", "--no-session-persistence",
           "--system-prompt", system + "\n\nRespond with ONLY the JSON object - no commentary, no code fences.",
           "--model", model or os.environ.get("CLAUDE_MODEL", "sonnet")]
    try:
        # Run from an empty temp folder so no project instructions get pulled into the context.
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=timeout, cwd=tempfile.gettempdir())
    except subprocess.TimeoutExpired:
        raise ClaudeCliError(f"Claude Code didn't answer within {timeout}s")
    if proc.returncode != 0:
        raise ClaudeCliError(f"Claude Code failed ({proc.returncode}): {(proc.stderr or proc.stdout)[:300]}")
    try:
        outer = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ClaudeCliError(f"unreadable Claude Code output: {proc.stdout[:200]}")
    if outer.get("is_error"):
        raise ClaudeCliError(f"Claude Code reported an error: {str(outer.get('result'))[:300]}")
    text = outer.get("result") or ""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ClaudeCliError("Claude Code's reply had no JSON object")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ClaudeCliError(f"Claude Code's JSON was invalid ({e})")
