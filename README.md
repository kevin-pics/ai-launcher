# ai-launcher

Unified CLI launcher for **codex**, **claude**, **droid**, **pi** AI agents via [ollama](https://ollama.com).

Single-key interactive menu, model switching from `ollama list`, remembers last-used model and recent launch directories.

## Install

```bash
# recommended (manages its own venv)
brew install pipx && pipx ensurepath
pipx install git+https://github.com/kevin-pics/ai-launcher.git
```

Requires `ollama` and the agent CLIs (`codex`, `claude`, `droid`, `pi`) on your PATH.

## Usage

```bash
ail            # interactive menu, press a number to launch
ail 2          # launch agent #2 (Claude) directly
ail -m         # pick model first, then show agent menu
```

### Menu

```
╭───────────────────────────── AI Agent Launcher ──────────────────────────────╮
│     #  Agent           Command                                               │
│     1  Codex           codex (directly)                                      │
│     2  Claude Code     ollama launch claude -- --dangerously-skip-permissions --model
│     3  Droid           ollama launch droid -- --auto high --model             │
│     4  Pi              ollama launch pi -- --thinking high --model           │
│                                                                              │
│                                                                              │
│  model: glm-5.2:cloud                                                        │
│  dir: /Users/me/project                                                      │
╰─ m select model   r recent dirs   q quit ────────────────────────────────────╯
```

- Press `1`-`4` to launch an agent (no Enter needed)
- Press `m` to select model (list comes from `ollama list`)
- Press `r` to pick a recent launch directory (`1`-`5` without Enter), use the current directory, or enter a path
- Press `q` to quit

## Commands launched

| Agent | Command |
|-------|---------|
| Codex | `codex` (directly, no model flag) |
| Claude | `ollama launch claude --model <m> -- --dangerously-skip-permissions` |
| Droid | `ollama launch droid --model <m> -- --auto high` |
| Pi | `ollama launch pi --model <m> -- --thinking high` |

## Model memory

Last selected model is saved to `~/.launcher_model`. Defaults to `glm-5.2:cloud` on first run or when cleared.

## Directory Recents

Agents launch from the selected directory. If no Recent is selected, the default launch directory is the current shell directory.

Recent launch directories are saved to `~/.launcher_recents`, newest first, with at most 5 entries.
