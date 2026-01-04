#!/usr/bin/env python3
"""Process management for aigonviewer server.

Handles launching, monitoring, and stopping viewer server instances.
Each server instance is tracked by a PID file in a platform-specific location.
"""

import os
import sys
import subprocess
import signal
import time
import socket
import platform
from pathlib import Path


def get_pid_directory(fallback_dir: Path = None) -> Path:
    """Get PID file directory, trying well-known locations by platform.

    Tries platform-specific standard locations in order:
    - macOS: ~/Library/Application Support/Aigon/pids, ~/.cache/aigon/pids, /tmp/aigon-fileserver
    - Linux: ~/.cache/aigon/pids, ~/.local/share/aigon/pids, /tmp/aigon-fileserver
    - Windows: %APPDATA%/Aigon/pids, %LOCALAPPDATA%/Aigon/pids, %TEMP%/aigon-fileserver

    Falls back to fallback_dir (current directory) as last resort.

    Args:
        fallback_dir: Directory to use if no standard location is writable (default: current directory)

    Returns:
        Path to PID directory (created if needed)
    """
    if fallback_dir is None:
        fallback_dir = Path.cwd()

    system = platform.system()
    home = Path.home()

    # Platform-specific candidate directories (in priority order)
    candidates = []

    if system == "Darwin":  # macOS
        candidates = [
            home / "Library" / "Application Support" / "Aigon" / "pids",
            home / ".cache" / "aigon" / "pids",
            Path("/tmp") / "aigon-fileserver",
        ]
    elif system == "Linux":
        candidates = [
            home / ".cache" / "aigon" / "pids",
            home / ".local" / "share" / "aigon" / "pids",
            Path("/tmp") / "aigon-fileserver",
        ]
    elif system == "Windows":
        appdata = os.getenv("APPDATA")
        localappdata = os.getenv("LOCALAPPDATA")
        temp = os.getenv("TEMP")

        if appdata:
            candidates.append(Path(appdata) / "Aigon" / "pids")
        if localappdata:
            candidates.append(Path(localappdata) / "Aigon" / "pids")
        if temp:
            candidates.append(Path(temp) / "aigon-fileserver")
    else:
        # Unknown system, try generic locations
        candidates = [
            home / ".cache" / "aigon" / "pids",
            Path("/tmp") / "aigon-fileserver" if Path("/tmp").exists() else None,
        ]
        candidates = [c for c in candidates if c]  # Remove None entries

    # Add fallback directory as last resort
    candidates.append(fallback_dir)

    # Try each candidate in order
    for candidate in candidates:
        try:
            # Try to create directory if it doesn't exist
            candidate.mkdir(parents=True, exist_ok=True)

            # Test if writable by creating/removing a test file
            test_file = candidate / ".write_test"
            test_file.touch()
            test_file.unlink()

            # Success - this directory works
            return candidate

        except (OSError, PermissionError):
            # Can't use this location, try next
            continue

    # Should never get here since fallback_dir is last candidate
    # But just in case, return fallback_dir anyway
    return fallback_dir


def find_available_port(start_port=4444, max_attempts=100):
    """Find an available port starting from start_port.

    Args:
        start_port: Port to start checking from
        max_attempts: Maximum number of ports to try

    Returns:
        Available port number, or None if none found
    """
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    return None


def is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running.

    Args:
        pid: Process ID to check

    Returns:
        True if process is running, False otherwise
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def launch_server(
    directory: str = None,
    port: int = 4444,
    host: str = "127.0.0.1",
    foreground: bool = False,
    remote: bool = True,
    no_browser: bool = False
):
    """Launch viewer server instance.

    Args:
        directory: Directory to serve (default: current directory)
        port: Port to run server on (will find next available if in use)
        host: Host to bind to
        foreground: Run in foreground (vs background daemon)
        remote: Enable remote sources (Aigon API, remote URLs)
        no_browser: Don't open browser automatically

    Returns:
        Tuple of (port, pid) for the launched server, or None if failed
    """
    # Get directory to serve (default to current working directory)
    serve_dir = Path(directory).resolve() if directory else Path.cwd()

    # Find available port
    actual_port = find_available_port(port)
    if actual_port is None:
        print(f"❌ No available ports found (tried {port}-{port+99})", file=sys.stderr)
        return None

    if actual_port != port:
        print(f"ℹ️  Port {port} in use, using port {actual_port} instead")

    # PID file location (port-specific to allow multiple viewers)
    pid_dir = get_pid_directory(serve_dir)
    pid_file = pid_dir / f"fileserver.{actual_port}.pid"

    # Check if server is already running on this port
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text().strip())
            if is_process_running(existing_pid):
                print(f"⚠️  Viewer already running on port {actual_port} (PID {existing_pid})")
                print(f"🌐 URL: http://{host}:{actual_port}")
                print(f"💡 Use 'aigonviewer kill --port {actual_port}' to stop it")
                return None
            else:
                # Process not running, clean up stale PID file
                pid_file.unlink()
        except (OSError, ValueError):
            # Invalid PID file, clean up
            pid_file.unlink()

    # Set environment variable for the server
    env = os.environ.copy()
    env["FILEDB_SERVE_DIR"] = str(serve_dir)

    # Build command - use python -m server to run as module
    cmd = [
        sys.executable, "-m", "server",
        "--directory", str(serve_dir),
        "--port", str(actual_port),
        "--host", host
    ]

    # Add remote flag if enabled
    if remote:
        cmd.append("--remote")

    # Always pass --no-browser to server (we handle browser opening ourselves)
    cmd.append("--no-browser")

    if foreground:
        # Run in foreground
        print(f"🚀 Starting Aigon Viewer Server...")
        print(f"📁 Serving: {serve_dir}")
        print(f"🌐 URL: http://{host}:{actual_port}")
        print(f"")
        print(f"Press Ctrl+C to stop the server")
        print(f"")

        try:
            subprocess.run(cmd, env=env, check=True)
            return (actual_port, None)  # No PID in foreground mode
        except KeyboardInterrupt:
            print("\n\n✅ Server stopped.")
            return (actual_port, None)
        except subprocess.CalledProcessError as e:
            print(f"\n❌ Error running server: {e}", file=sys.stderr)
            return None
    else:
        # Run in background
        print(f"🚀 Starting Aigon Viewer Server in background...")
        print(f"📁 Serving: {serve_dir}")
        print(f"🌐 URL: http://{host}:{actual_port}")

        try:
            # Create temporary file for stderr
            import tempfile
            stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.log')
            stderr_path = stderr_file.name
            stderr_file.close()

            # Start process in background
            with open(stderr_path, 'w') as stderr_log:
                process = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_log,
                    start_new_session=True
                )

            # Write PID file
            pid_file.write_text(str(process.pid))
            print(f"💾 PID {process.pid} saved to {pid_file}")

            # Wait a moment for server to start
            time.sleep(2)

            # Check if process is still running
            if process.poll() is not None:
                print(f"❌ Server failed to start", file=sys.stderr)
                # Read and display stderr
                try:
                    with open(stderr_path, 'r') as f:
                        stderr_output = f.read()
                        if stderr_output:
                            print(stderr_output, file=sys.stderr)
                except:
                    pass
                finally:
                    # Clean up temp file
                    try:
                        os.unlink(stderr_path)
                    except:
                        pass
                pid_file.unlink()
                return None

            # Clean up temp file if server started successfully
            try:
                os.unlink(stderr_path)
            except:
                pass

            # Open browser (unless --no-browser specified)
            if not no_browser:
                url = f"http://{host}:{actual_port}"
                print(f"🌍 Opening browser...")
                # Use platform-specific browser opening
                if platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", url], check=False)
                elif platform.system() == "Windows":
                    subprocess.run(["start", url], shell=True, check=False)
                else:  # Linux and others
                    subprocess.run(["xdg-open", url], check=False)

            print(f"✅ Server running in background")
            print(f"💡 Use 'aigonviewer kill' to stop it")

            return (actual_port, process.pid)

        except Exception as e:
            print(f"❌ Error starting server: {e}", file=sys.stderr)
            if pid_file.exists():
                pid_file.unlink()
            return None


def status_server(directory: str = None):
    """Check status of running viewer servers.

    Args:
        directory: Directory context (for PID file location)

    Returns:
        List of tuples (pid, port) for running servers
    """
    # Get directory
    serve_dir = Path(directory).resolve() if directory else Path.cwd()

    # Get PID directory (try standard locations, fallback to serve_dir)
    pid_dir = get_pid_directory(serve_dir)

    # Find all PID files
    pid_files = list(pid_dir.glob("fileserver.*.pid"))

    if not pid_files:
        print(f"⚠️  No viewers running")
        return []

    # Check each PID file
    running_viewers = []
    stale_files = []

    for pid_file in pid_files:
        try:
            pid = int(pid_file.read_text().strip())
            # Extract port from filename: fileserver.<port>.pid
            port = pid_file.stem.split('.')[-1]

            # Check if process is still running
            if is_process_running(pid):
                running_viewers.append((pid, port))
            else:
                stale_files.append(pid_file)

        except ValueError:
            stale_files.append(pid_file)

    # Clean up stale PID files
    for stale_file in stale_files:
        stale_file.unlink()

    # Report results
    if running_viewers:
        print(f"✅ {len(running_viewers)} viewer(s) running:")
        for pid, port in running_viewers:
            print(f"   Port {port}: PID {pid} - http://127.0.0.1:{port}")
        print(f"📁 Serving: {serve_dir}")
        return running_viewers
    else:
        if stale_files:
            print(f"⚠️  No viewers running (cleaned up {len(stale_files)} stale PID file(s))")
        else:
            print(f"⚠️  No viewers running")
        return []


def kill_server(directory: str = None, port: int = None, kill_all: bool = False):
    """Stop running viewer server(s).

    Args:
        directory: Directory context (for PID file location)
        port: Specific port to kill (None = kill all)
        kill_all: Explicitly kill all viewers (same as port=None)

    Returns:
        Number of servers successfully killed
    """
    # Get directory where server is running
    serve_dir = Path(directory).resolve() if directory else Path.cwd()

    # Get PID directory (try standard locations, fallback to serve_dir)
    pid_dir = get_pid_directory(serve_dir)

    # Find PID files to kill
    if port:
        # Kill specific port
        pid_files = [pid_dir / f"fileserver.{port}.pid"]
    elif kill_all:
        # Kill all viewers
        pid_files = list(pid_dir.glob("fileserver.*.pid"))
    else:
        # Default: kill all viewers (backwards compatible)
        pid_files = list(pid_dir.glob("fileserver.*.pid"))

    if not pid_files:
        if port:
            print(f"⚠️  No viewer running on port {port}")
        else:
            print(f"⚠️  No viewers running")
        return 0

    # Kill each process
    killed_count = 0
    failed_count = 0

    for pid_file in pid_files:
        if not pid_file.exists():
            if port:
                print(f"⚠️  No viewer running on port {port}")
                return 0
            continue

        try:
            pid = int(pid_file.read_text().strip())
            port_num = pid_file.stem.split('.')[-1]

            # Try to kill the process
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"✅ Stopped viewer on port {port_num} (PID {pid})")

                # Wait a moment for graceful shutdown
                time.sleep(1)

                # Check if still running, force kill if needed
                if is_process_running(pid):
                    print(f"⚠️  Process still running, force killing...")
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.5)

                killed_count += 1

            except OSError as e:
                if e.errno == 3:  # No such process
                    print(f"⚠️  Process {pid} not found (already stopped)")
                else:
                    print(f"❌ Error killing process {pid}: {e}", file=sys.stderr)
                    failed_count += 1

            # Clean up PID file
            pid_file.unlink()

        except ValueError:
            print(f"❌ Invalid PID file format in {pid_file.name}", file=sys.stderr)
            pid_file.unlink()
            failed_count += 1
        except Exception as e:
            print(f"❌ Error processing {pid_file.name}: {e}", file=sys.stderr)
            failed_count += 1

    # Final summary
    if killed_count > 0:
        print(f"💾 Stopped {killed_count} viewer(s)")

    return killed_count
