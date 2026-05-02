# FastAPI Repository

This repository contains a FastAPI-based project for network monitoring and Orion topology visualization.

## Setup for GitHub Codespaces

The repo includes a `.devcontainer/devcontainer.json` file to make Codespaces start cleanly.

### What it does
- Uses the repo workspace at `/workspaces/fastapi`
- Builds the dev container using `Dockerfile.dockerfile`
- Creates a `.venv` virtual environment inside the repo
- Installs Python dependencies from `requirements.txt`
- Configures VS Code to use `.venv/bin/python`
- Forwards port `8000`

### How to open in Codespaces
1. Open this repository in GitHub Codespaces.
2. Wait for Codespaces to build and configure the container.
3. If needed, use the Command Palette:
   - `Codespaces: Rebuild Container`
   - or `Remote-Containers: Reopen in Container`

### When Codespaces is recreated
Codespaces rebuilds the container from the devcontainer config. The `.venv` lives inside the workspace, and is recreated automatically by the `postCreateCommand`.

## Local development on VS Code

### Option A: Use the dev container locally
1. Install the Remote - Containers extension.
2. Open the repository in VS Code.
3. Run `Remote-Containers: Reopen in Container`.

### Option B: Use a local venv directly
In the repository root:
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Then open VS Code and select the interpreter:
- `.venv/bin/python`

## Notes
- `.venv/` is ignored by `.gitignore` and should not be committed.
- Keep `requirements.txt` committed so both Codespaces and local machines can install the same dependencies.
- If dependencies change, rerun:
  - `.venv/bin/pip install -r requirements.txt`

## Useful VS Code commands
- `Python: Select Interpreter`
- `Developer: Reload Window`
- `Remote-Containers: Rebuild Container`
