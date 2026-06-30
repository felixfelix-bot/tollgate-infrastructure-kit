#!/usr/bin/env python3
"""
ngit-tool-mcp.py — MCP stdio server for ngit operations.

Wraps ngit-tool.sh so Hermes can call ngit operations as MCP tools.
No pip packages needed — uses stdlib only.

Protocol: MCP over stdio (JSON-RPC 2.0)
Each tool call invokes ngit-tool.sh and returns its output.

Install in Hermes config:
  mcp_servers:
    ngit-tool:
      command: python3
      args: ["/home/c03rad0r/scripts/ngit-tool-mcp.py"]
"""

import json
import subprocess
import sys
import os

TOOL_SCRIPT = os.path.expanduser("~/scripts/ngit-tool.sh")

TOOLS = [
    {
        "name": "ngit_init",
        "description": "Initialize a new git repo on ngit (nostr git). Handles all interactive prompts automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string", "description": "Absolute path to git repo"},
                "repo_name": {"type": "string", "description": "Repo name (default: dir basename)"}
            },
            "required": ["repo_dir"]
        }
    },
    {
        "name": "ngit_push",
        "description": "Push a branch to ngit. Tries multiple strategies: ngit sync, direct push, GitHub push + sync.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string", "description": "Absolute path to git repo"},
                "branch": {"type": "string", "description": "Branch name to push (default: current branch)"}
            },
            "required": ["repo_dir"]
        }
    },
    {
        "name": "ngit_sync",
        "description": "Sync repo with ngit nostr state — updates grasp servers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string", "description": "Absolute path to git repo"}
            },
            "required": ["repo_dir"]
        }
    },
    {
        "name": "ngit_status",
        "description": "Show ngit configuration status for a repo (remotes, branches, PRs).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string", "description": "Absolute path to git repo"}
            },
            "required": ["repo_dir"]
        }
    },
    {
        "name": "ngit_fix",
        "description": "Fix ngit configuration for a repo. Adds remotes, runs ngit init via expect.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_dir": {"type": "string", "description": "Absolute path to git repo"}
            },
            "required": ["repo_dir"]
        }
    },
]


def run_tool(tool_name, args):
    """Run ngit-tool.sh with the given command and args."""
    cmd_map = {
        "ngit_init": ["init", args.get("repo_dir"), args.get("repo_name", "")],
        "ngit_push": ["push", args.get("repo_dir"), args.get("branch", "HEAD")],
        "ngit_sync": ["sync", args.get("repo_dir")],
        "ngit_status": ["status", args.get("repo_dir")],
        "ngit_fix": ["fix", args.get("repo_dir")],
    }

    cmd = cmd_map.get(tool_name)
    if not cmd:
        return {"error": f"Unknown tool: {tool_name}"}

    # Filter out empty trailing args
    cmd = [arg for arg in cmd if arg]

    try:
        result = subprocess.run(
            [TOOL_SCRIPT] + cmd,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "VERBOSE": "1", "TIMEOUT": "120"}
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out", "success": False}
    except FileNotFoundError:
        return {"error": f"Script not found: {TOOL_SCRIPT}", "success": False}
    except Exception as e:
        return {"error": str(e), "success": False}


def handle_request(request):
    """Handle a single JSON-RPC request."""
    req_id = request.get("id")
    method = request.get("method", "")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {"name": "ngit-tool", "version": "1.0.0"}
        }}
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        tool_args = request.get("params", {}).get("arguments", {})
        result = run_tool(tool_name, tool_args)
        # Format as MCP tool result
        content = []
        if "stdout" in result and result["stdout"]:
            content.append({"type": "text", "text": result["stdout"]})
        if "stderr" in result and result["stderr"]:
            content.append({"type": "text", "text": f"[stderr]\n{result['stderr']}"})
        if "error" in result:
            content.append({"type": "text", "text": f"[error] {result['error']}"})
        if not content:
            content.append({"type": "text", "text": "(no output)"})
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": content,
                "isError": not result.get("success", True)
            }
        }
    elif method == "notifications/initialized":
        return None  # No response needed
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {
            "code": -32601, "message": f"Method not found: {method}"
        }}


def main():
    """Read JSON-RPC requests from stdin, write responses to stdout."""
    # Signal to hermes: this is an MCP server
    sys.stderr.write("ngit-tool MCP server starting...\n")
    sys.stderr.flush()

    buffer = ""
    for line in sys.stdin:
        buffer += line
        try:
            request = json.loads(buffer)
            buffer = ""
        except json.JSONDecodeError:
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
