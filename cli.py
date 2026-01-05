#!/usr/bin/env python3
"""CLI entry point for aigonviewer command.

Provides full process management for the Aigon Viewer Server.
"""

import argparse
import sys

try:
    from .process_manager import launch_server, status_server, kill_server
    from .version import __version__
except ImportError:
    # Fallback for direct execution
    from process_manager import launch_server, status_server, kill_server
    from version import __version__


def main():
    """Main CLI entry point for aigonviewer command."""
    parser = argparse.ArgumentParser(
        prog='aigonviewer',
        description='Aigon Viewer Server - Markdown viewer with process management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  aigonviewer launch                    # Launch on default port 4444
  aigonviewer launch --port 8080        # Launch on port 8080
  aigonviewer launch --foreground       # Run in foreground
  aigonviewer launch --no-browser       # Don't open browser
  aigonviewer status                    # Check running viewers
  aigonviewer kill                      # Stop all viewers
  aigonviewer kill --port 4444          # Stop viewer on port 4444

For simple server execution without process management, use:
  aigonviewer_raw /path/to/directory
        """
    )

    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}'
    )

    # Undocumented version assertion for proxy validation
    parser.add_argument(
        '--assert-version',
        help=argparse.SUPPRESS,  # Hide from help
        metavar='VERSION'
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Launch subcommand
    launch_parser = subparsers.add_parser(
        'launch',
        help='Launch viewer server in background or foreground'
    )
    launch_parser.add_argument(
        'directory',
        nargs='?',
        default=None,
        help='Directory to serve (default: current directory)'
    )
    launch_parser.add_argument(
        '--port', '-p',
        type=int,
        default=4444,
        help='Port to run server on (default: 4444, will auto-increment if in use)'
    )
    launch_parser.add_argument(
        '--host',
        default='127.0.0.1',
        help='Host to bind to (default: 127.0.0.1)'
    )
    launch_parser.add_argument(
        '--foreground', '-fg',
        action='store_true',
        help='Run in foreground (don\'t daemonize, run until Ctrl+C)'
    )
    launch_parser.add_argument(
        '--remote', '-r',
        action='store_true',
        default=False,
        help='Enable remote sources (Aigon API, remote URLs)'
    )
    launch_parser.add_argument(
        '--local', '-l',
        action='store_true',
        help='Force local-only mode (overrides --remote)'
    )
    launch_parser.add_argument(
        '--no-remote',
        action='store_true',
        help='Disable remote sources (local files only, alias for --local)'
    )
    launch_parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Don\'t open browser automatically'
    )

    # Status subcommand
    status_parser = subparsers.add_parser(
        'status',
        help='Check status of running viewer servers'
    )
    status_parser.add_argument(
        '--directory', '-d',
        help='Directory context (for PID file location, default: current directory)'
    )

    # Kill subcommand
    kill_parser = subparsers.add_parser(
        'kill',
        help='Stop running viewer server(s)'
    )
    kill_parser.add_argument(
        '--directory', '-d',
        help='Directory context (for PID file location, default: current directory)'
    )
    kill_parser.add_argument(
        '--port', '-p',
        type=int,
        help='Kill viewer on specific port (default: kill all)'
    )
    kill_parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='Explicitly kill all viewers (same as default behavior)'
    )

    # Check if first argument looks like a directory (for aigonviewer ~/path syntax)
    import sys as _sys
    if len(_sys.argv) > 1 and not _sys.argv[1].startswith('-') and _sys.argv[1] not in ['launch', 'status', 'kill']:
        # Insert 'launch' subcommand before the directory
        _sys.argv.insert(1, 'launch')

    # Parse arguments
    args = parser.parse_args()

    # Check version assertion (undocumented, used by proxy)
    if args.assert_version:
        if args.assert_version != __version__:
            print(f"Version mismatch: installed={__version__}, expected={args.assert_version}", file=sys.stderr)
            sys.exit(3)  # Exit code 3 indicates version mismatch (not 2, which is used by argparse)
        # Version matches, continue normally

    # Default to launch if no command specified
    if not args.command:
        args.command = 'launch'
        # Use default values for launch
        args.directory = None
        args.port = 4444
        args.host = '127.0.0.1'
        args.foreground = False
        args.remote = False
        args.local = False
        args.no_remote = False
        args.no_browser = False

    # Route to appropriate handler
    if args.command == 'launch':
        # Handle remote flag - --local overrides --remote
        if hasattr(args, 'local') and args.local:
            remote = False
        elif hasattr(args, 'no_remote') and args.no_remote:
            remote = False
        else:
            remote = args.remote

        result = launch_server(
            directory=args.directory,
            port=args.port,
            host=args.host,
            foreground=args.foreground,
            remote=remote,
            no_browser=args.no_browser
        )
        if result is None:
            sys.exit(1)
        else:
            sys.exit(0)

    elif args.command == 'status':
        viewers = status_server(directory=args.directory)
        # Always exit 0 - "no viewers running" is not an error
        sys.exit(0)

    elif args.command == 'kill':
        killed = kill_server(
            directory=args.directory,
            port=args.port,
            kill_all=args.all
        )
        sys.exit(0 if killed > 0 else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
