#!/usr/bin/env python3
"""ail - unified launcher for codex / claude / droid / pi agents.

Usage:
  ail            interactive menu
  ail <n>        directly launch agent n (1-4), no menu
  ail -m         pick model first, then agent menu
  ail --reset-agents    overwrite agents config with defaults
"""

import json
import os
import sys
import shutil
import subprocess
import termios
import tty

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

CONFIG_PATH = os.path.expanduser("~/.launcher_model")
RECENTS_PATH = os.path.expanduser("~/.launcher_recents")
AGENTS_CONFIG_PATH = os.path.expanduser("~/.launcher_agents.json")
DEFAULT_MODEL = "glm-5.2:cloud"
MAX_RECENTS = 5


def load_model():
    """Return last-used model.

    First run (no config file) -> DEFAULT_MODEL.
    Config file exists but empty -> None (cleared state is remembered).
    """
    try:
        with open(CONFIG_PATH) as f:
            m = f.read().strip()
    except FileNotFoundError:
        return DEFAULT_MODEL
    except OSError:
        return DEFAULT_MODEL
    return m or None


def save_model(model):
    try:
        with open(CONFIG_PATH, "w") as f:
            f.write(model or "")
    except OSError:
        pass


def normalize_dir(path):
    return os.path.abspath(os.path.expanduser(path))


def load_recents():
    recents = []
    seen = set()
    try:
        with open(RECENTS_PATH) as f:
            lines = f.readlines()
    except (FileNotFoundError, OSError):
        return recents
    for line in lines:
        path = line.strip()
        if not path:
            continue
        path = normalize_dir(path)
        if path in seen or not os.path.isdir(path):
            continue
        seen.add(path)
        recents.append(path)
        if len(recents) >= MAX_RECENTS:
            break
    return recents


def save_recents(recents):
    try:
        with open(RECENTS_PATH, "w") as f:
            f.write("\n".join(recents[:MAX_RECENTS]))
            if recents:
                f.write("\n")
    except OSError:
        pass


def remember_recent(path):
    path = normalize_dir(path)
    if not os.path.isdir(path):
        return
    recents = [p for p in load_recents() if p != path]
    recents.insert(0, path)
    save_recents(recents)


AGENTS_DEFAULT = [
    {
        "key": "codex",
        "name": "Codex",
        "desc": "codex (directly)",
        "build": lambda model: ["codex"],
    },
    {
        "key": "claude",
        "name": "Claude Code",
        "desc": "ollama launch claude -- --dangerously-skip-permissions [--model <m>]",
        "build": lambda model: ["ollama", "launch", "claude"]
                               + (["--model", model] if model else [])
                               + ["--", "--dangerously-skip-permissions"],
    },
    {
        "key": "droid",
        "name": "Droid",
        "desc": "ollama launch droid -- --auto high [--model <m>]",
        "build": lambda model: ["ollama", "launch", "droid"]
                               + (["--model", model] if model else [])
                               + ["--", "--auto", "high"],
    },
    {
        "key": "pi",
        "name": "Pi",
        "desc": "ollama launch pi -- --thinking high [--model <m>]",
        "build": lambda model: ["ollama", "launch", "pi"]
                               + (["--model", model] if model else [])
                               + ["--", "--thinking", "high"],
    },
]


def build_agent(entry):
    """Build a launcher function from a config entry.

    Entry shape (one of):
      {"cmd": ["codex"]}                                  # fixed command
      {"cmd": ["ollama","launch","claude"],               # model injected
       "model_flag": "--model", "args": ["--","--dangerously-skip-permissions"]}
    """
    cmd = list(entry.get("cmd", []))
    model_flag = entry.get("model_flag")
    args = list(entry.get("args", []))

    def builder(model):
        out = list(cmd)
        if model_flag and model:
            out += [model_flag, model]
        out += args
        return out
    return builder


def load_agents():
    """Return agents list.

    - If ~/.launcher_agents.json exists and is valid -> use it.
    - Otherwise -> AGENTS_DEFAULT.
    """
    try:
        with open(AGENTS_CONFIG_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        return list(AGENTS_DEFAULT)
    except (OSError, ValueError):
        return list(AGENTS_DEFAULT)

    if not isinstance(data, list):
        return list(AGENTS_DEFAULT)

    agents = []
    for entry in data:
        if not isinstance(entry, dict) or "cmd" not in entry:
            continue
        key = entry.get("key") or entry.get("name", "agent").lower().replace(" ", "_")
        name = entry.get("name", key)
        desc = entry.get("desc", " ".join(entry.get("cmd", [])))
        agents.append({
            "key": key,
            "name": name,
            "desc": desc,
            "build": build_agent(entry),
        })
    return agents or list(AGENTS_DEFAULT)


def _default_agents_data():
    """Return the default agents config as a list of dicts."""
    return [
        {
            "key": "codex",
            "name": "Codex",
            "desc": "codex (directly)",
            "cmd": ["codex"],
        },
        {
            "key": "claude",
            "name": "Claude Code",
            "desc": "ollama launch claude -- --dangerously-skip-permissions [--model <m>]",
            "cmd": ["ollama", "launch", "claude"],
            "model_flag": "--model",
            "args": ["--", "--dangerously-skip-permissions"],
        },
        {
            "key": "droid",
            "name": "Droid",
            "desc": "ollama launch droid -- --auto high [--model <m>]",
            "cmd": ["ollama", "launch", "droid"],
            "model_flag": "--model",
            "args": ["--", "--auto", "high"],
        },
        {
            "key": "pi",
            "name": "Pi",
            "desc": "ollama launch pi -- --thinking high [--model <m>]",
            "cmd": ["ollama", "launch", "pi"],
            "model_flag": "--model",
            "args": ["--", "--thinking", "high"],
        },
    ]


# Loaded once at startup; can be reloaded via load_agents() if needed
AGENTS = load_agents()


def get_models():
    """Return list of model names from `ollama list`."""
    out = subprocess.run(
        ["ollama", "list"], capture_output=True, text=True, check=False
    )
    models = []
    for line in out.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        name = line.split()[0]
        if name:
            models.append(name)
    return models


def write_default_agents_config():
    """Write the default agents config to AGENTS_CONFIG_PATH.

    Returns True on success, False on failure.
    """
    try:
        with open(AGENTS_CONFIG_PATH, "w") as f:
            json.dump(_default_agents_data(), f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        console.print(f"[red]Cannot write {AGENTS_CONFIG_PATH}: {e}[/red]")
        return False
    return True


def edit_agents_config():
    """Open the agents config file in $EDITOR (fallback: vi).

    If the file does not exist, dump the default config into it first so the
    user has a starting point to edit.
    """
    if not os.path.isfile(AGENTS_CONFIG_PATH):
        if not write_default_agents_config():
            return
    editor = os.environ.get("EDITOR", "vi")
    try:
        subprocess.call([editor, AGENTS_CONFIG_PATH])
    except FileNotFoundError:
        console.print(f"[red]Editor '{editor}' not found in PATH[/red]")
        return
    except OSError as e:
        console.print(f"[red]Failed to launch editor: {e}[/red]")
        return
    # Reload agents after editing
    global AGENTS
    AGENTS = load_agents()


def clear_screen():
    if sys.stdin.isatty() and sys.stdout.isatty():
        console.clear()


def render_menu(model, selected_dir):
    clear_screen()
    table = Table(show_header=True, header_style="bold cyan", box=None,
                  padding=(0, 1))
    table.add_column("#", style="bold yellow", justify="right", width=3)
    table.add_column("Agent", style="bold green", width=14)
    table.add_column("Command", style="dim")
    for i, a in enumerate(AGENTS, 1):
        table.add_row(str(i), a["name"], a["desc"])

    footer = Text()
    if model:
        footer.append("model: ", style="bold magenta")
        footer.append(model, style="cyan")
    else:
        footer.append("model: ", style="bold magenta")
        footer.append("(cleared)", style="dim")
    footer.append("\n")
    footer.append("dir: ", style="bold magenta")
    footer.append(selected_dir, style="cyan")

    console.print(Panel(
        Group(table, Text(""), footer),
        title="[bold blue]AI Agent Launcher[/bold blue]",
        border_style="blue",
        subtitle=(
            "[yellow]m[/yellow] select model   "
            "[yellow]r[/yellow] recent dirs   "
            "[yellow]e[/yellow] edit agents   "
            "[yellow]q[/yellow] quit"
        ),
        subtitle_align="left",
        padding=(1, 2),
    ))


def read_key():
    """Read a single keystroke without waiting for Enter (cbreak mode).

    Falls back to line input if stdin is not a tty.
    """
    if not sys.stdin.isatty():
        return input("> ").strip().lower()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch.lower()


def read_line(prompt):
    console.print(prompt, end="")
    try:
        return input().strip()
    except EOFError:
        return ""


def read_directory_choice(prompt):
    """Read directory choice.

    In a TTY, numeric choices are accepted immediately. Path entry starts when
    the first key is not a digit or Enter, then continues as normal line input.
    """
    console.print(prompt, end="")
    if not sys.stdin.isatty():
        try:
            return input().strip()
        except EOFError:
            return ""

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    if ch in ("\r", "\n"):
        print()
        return ""
    if ch.isdigit():
        print(ch)
        return ch

    print(ch, end="", flush=True)
    try:
        rest = input()
    except EOFError:
        rest = ""
    return (ch + rest).strip()


def pick_model(current=None):
    models = get_models()
    if not models:
        console.print("  [red](no models found via `ollama list`)[/red]")
        return current
    clear_screen()
    table = Table(show_header=True, header_style="bold cyan", box=None,
                  padding=(0, 1))
    table.add_column("#", style="bold yellow", justify="right", width=3)
    table.add_column("Model", style="green")
    for i, m in enumerate(models, 1):
        style = "bold cyan" if m == current else "green"
        marker = " *" if m == current else ""
        table.add_row(str(i), f"{m}{marker}", style=style)
    table.add_row("0", "(no model / clear)", style="dim")
    console.print(Panel(
        table,
        title="[bold blue]Select Model[/bold blue]",
        border_style="blue",
        padding=(1, 2),
    ))
    while True:
        console.print(f"[bold]Select model [1-{len(models)} / 0]:[/bold] ", end="")
        choice = read_key()
        print()
        if choice == "0":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            return models[int(choice) - 1]
        console.print("[red]  invalid choice[/red]")


def pick_directory(current):
    cwd = normalize_dir(os.getcwd())
    recents = load_recents()
    clear_screen()
    table = Table(show_header=True, header_style="bold cyan", box=None,
                  padding=(0, 1))
    table.add_column("#", style="bold yellow", justify="right", width=3)
    table.add_column("Directory", style="green")
    for i, path in enumerate(recents, 1):
        style = "bold cyan" if path == current else "green"
        marker = " *" if path == current else ""
        table.add_row(str(i), f"{path}{marker}", style=style)
    table.add_row("0", f"(current directory) {cwd}", style="dim")
    console.print(Panel(
        table,
        title="[bold blue]Select Directory[/bold blue]",
        border_style="blue",
        padding=(1, 2),
    ))
    prompt = (
        f"[bold]Select dir [1-{len(recents)} / 0 / path]:[/bold] "
        if recents else
        "[bold]Select dir [0 / path]:[/bold] "
    )
    while True:
        choice = read_directory_choice(prompt)
        if choice == "" or choice == "0":
            remember_recent(cwd)
            return cwd
        if choice.isdigit() and 1 <= int(choice) <= len(recents):
            path = recents[int(choice) - 1]
            remember_recent(path)
            return path
        path = normalize_dir(choice)
        if os.path.isdir(path):
            remember_recent(path)
            return path
        console.print(f"[red]  not a directory: {choice}[/red]")


def launch(agent_idx, model, directory):
    agent = AGENTS[agent_idx]
    cmd = agent["build"](model)
    directory = normalize_dir(directory)
    if not os.path.isdir(directory):
        console.print(f"[red]Error: directory not found: {directory}[/red]")
        sys.exit(1)
    remember_recent(directory)
    console.print(f"\n[bold green]Launching {agent['name']} ...[/bold green]")
    try:
        os.chdir(directory)
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        console.print(f"[red]Error: '{cmd[0]}' not found in PATH[/red]")
        sys.exit(127)


def main():
    model = load_model()
    selected_dir = normalize_dir(os.getcwd())

    # Direct agent index from CLI arg
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("-h", "--help"):
            print(__doc__)
            return
        if arg == "--reset-agents":
            if write_default_agents_config():
                print(f"Wrote default agents config to {AGENTS_CONFIG_PATH}")
            return
        if arg == "-m":
            model = pick_model(model)
            save_model(model)
            render_menu(model, selected_dir)
        elif arg.isdigit():
            idx = int(arg)
            if 1 <= idx <= len(AGENTS):
                if len(sys.argv) > 2 and sys.argv[2] == "-m":
                    model = pick_model(model)
                    save_model(model)
                launch(idx - 1, model, selected_dir)
                return
            print("invalid agent index: {}".format(idx))
            return

    # Interactive menu loop
    while True:
        render_menu(model, selected_dir)
        print("> ", end="", flush=True)
        choice = read_key()
        print()  # newline after keypress
        if choice == "q":
            return
        if choice == "m":
            model = pick_model(model)
            save_model(model)
            continue
        if choice == "r":
            selected_dir = pick_directory(selected_dir)
            continue
        if choice == "e":
            edit_agents_config()
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(AGENTS):
            launch(int(choice) - 1, model, selected_dir)
            return
        print("invalid choice, try again")


if __name__ == "__main__":
    main()
