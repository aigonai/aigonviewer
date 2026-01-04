# Aigon Viewer Server

A lightweight FastAPI markdown viewer for local files.

## Installation

### Prerequisites: Install uv

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver. `uv tool` installs CLI tools globally in isolated environments, making them available system-wide in your PATH.

```bash
# Install uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or install via pip/pipx if you prefer
pip install uv
# OR
pipx install uv
```

### Installation Options

**Option 1: Directly from GitHub (recommended)**

Install without cloning:

```bash
uv tool install git+https://github.com/aigonai/aigonviewer.git
```

**Option 2: From GitHub Clone**

Clone the repository and install locally:

```bash
# Clone the repository
git clone https://github.com/aigonai/aigonviewer.git
cd aigonviewer

# Install as a global tool
uv tool install .

# Or use the install script
./install.sh

# To update an already-installed version
uv tool install --force .
```

**Option 3: From PyPI (coming later)**

Once published to PyPI, you'll be able to install directly:

```bash
uv tool install aigon-viewer-server
```

### Updating

**If installed via Option 1 (Directly from GitHub):**
```bash
uv tool install --force git+https://github.com/aigonai/aigonviewer.git
```

**If installed via Option 2 (GitHub Clone):**
```bash
cd aigonviewer
git pull
uv tool install --force .
```

**If installed via Option 3 (PyPI - when available):**
```bash
uv tool install --upgrade aigon-viewer-server
```

## Running the Server

### Using `aigonviewer`
*Full CLI with Process Management*

The `aigonviewer` command provides full process management with background execution, status checking, and cleanup.

**Available Commands:**
```bash
aigonviewer launch [OPTIONS]    # Launch server in background
aigonviewer status              # Check running servers
aigonviewer kill [OPTIONS]      # Stop running servers
```

**Launch Options:**
```bash
aigonviewer [launch] [DIRECTORY] [OPTIONS]

Arguments:
  DIRECTORY             Directory to serve (default: current directory)

Options:
  --port, -p PORT       Port to run on (default: 4444)
  --host HOST           Host to bind to (default: 127.0.0.1)
  --foreground, -fg     Run in foreground (don't daemonize)
  --no-browser          Don't open browser automatically
  --remote, -r          Enable remote sources (default: enabled)
  --no-remote           Disable remote sources (local files only)
```

**Examples:**
```bash
# Launch server (simplified syntax)
aigonviewer ~/notes

# Launch on custom port
aigonviewer ~/notes --port 8080

# Launch from current directory
aigonviewer

# Run in foreground (blocks until Ctrl+C)
aigonviewer ~/notes --foreground

# Explicit launch command (also works)
aigonviewer launch ~/notes --port 8080

# Check running servers
aigonviewer status

# Stop all servers
aigonviewer kill

# Stop server on specific port
aigonviewer kill --port 4444
```

### Using `aigonviewer_base`
*Simple Mode*

For simple use cases where you don't need process management, use `aigonviewer_base` which runs directly in the foreground:

```bash
# Basic usage
aigonviewer_base ~/notes

# Custom port and host
aigonviewer_base ~/notes --port 8080 --host 0.0.0.0

# Don't open browser
aigonviewer_base ~/notes --no-browser
```

**Options:**
```bash
aigonviewer_base [PATH] [OPTIONS]

Arguments:
  PATH                   Directory to serve (default: current directory)

Options:
  --version              Show version and exit
  --port PORT            Port to run on (default: 3030)
  --host HOST            Host to bind to (default: 127.0.0.1)
  --remote               Enable remote sources
  --no-browser           Don't automatically open browser
```

## Configuration

The `_config.toml` file is optional. If you create it in your markdown directory, you can organize files into groups and get a dropdown menu to focus on specific file groups.

**Example `_config.toml`:**

```toml
[work]
todo-aigon
agenda
project-notes

[personal]
shopping-list
brain-context-dump
```

**Note:** File names are listed without the `.md` extension.
