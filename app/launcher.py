#!/usr/bin/env python3
"""
Phocus Monitor App Launcher

A lightweight macOS app that:
1. Checks if the phocus-monitor venv is set up
2. Guides users through setup if needed
3. Launches the monitoring script with nice dialogs for options

Due to macOS security restrictions around sudo and native extensions,
we use the local venv installation rather than bundling Python.
"""

import os
import sys
import subprocess
from pathlib import Path


# Expected location of the phocus-monitor installation
# Users should clone/download to their home directory
DEFAULT_INSTALL_DIR = Path.home() / "phocus-monitor"


def show_alert(title, message, buttons=["OK"]):
    """Show a macOS alert dialog."""
    # Escape special characters for AppleScript
    message = message.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    buttons_str = ', '.join(f'"{b}"' for b in buttons)
    script = f'''
    display alert "{title}" message "{message}" buttons {{{buttons_str}}} default button 1
    '''
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True,
        text=True
    )
    return result.stdout.strip().replace('button returned:', '')


def show_input_dialog(prompt, default=""):
    """Show a macOS input dialog and return the text."""
    prompt = prompt.replace('"', '\\"')
    script = f'''
    display dialog "{prompt}" default answer "{default}"
    '''
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if 'text returned:' in output:
        return output.split('text returned:')[1].strip()
    return default


def get_output_directory():
    """Ask user where to save output files."""
    script = '''
    set outputFolder to choose folder with prompt "Choose where to save the monitoring results:"
    return POSIX path of outputFolder
    '''
    result = subprocess.run(
        ['osascript', '-e', script],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return str(Path.home() / "Desktop")
    return result.stdout.strip()


def check_phocus_running():
    """Check if Phocus is running."""
    result = subprocess.run(['pgrep', '-x', 'Phocus'], capture_output=True)
    return result.returncode == 0


def find_install_dir():
    """
    Find the phocus-monitor installation directory.
    Checks several common locations.
    """
    candidates = [
        DEFAULT_INSTALL_DIR,
        Path.home() / "Downloads" / "phocus-monitor",
        Path.home() / "Documents" / "phocus-monitor",
        # iCloud Drive location
        Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "GitHub" / "phocus-monitor",
    ]

    # If running as bundled app, check relative to bundle
    # The .app is at phocus-monitor/app/dist/Phocus Monitor.app
    # So we need to go up: Contents/MacOS -> Contents -> .app -> dist -> app -> phocus-monitor
    if getattr(sys, 'frozen', False):
        # sys.executable is .app/Contents/MacOS/Phocus Monitor
        bundle_path = Path(sys.executable).parent.parent.parent  # .app
        project_root = bundle_path.parent.parent.parent  # phocus-monitor
        candidates.insert(0, project_root)

    for candidate in candidates:
        venv_python = candidate / ".venv" / "bin" / "python3"
        script = candidate / "monitor_phocus.py"
        if venv_python.exists() and script.exists():
            return candidate

    return None


def show_setup_instructions():
    """Show setup instructions to the user."""
    instructions = """Phocus Monitor requires a one-time setup.

Please open Terminal and run these commands:

cd ~/Downloads
git clone https://github.com/kmichels/phocus-monitor.git
cd phocus-monitor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

Then launch this app again."""

    show_alert("Setup Required", instructions)


def main():
    """Main entry point for the app."""

    # Find the installation directory
    install_dir = find_install_dir()

    if install_dir is None:
        show_setup_instructions()
        sys.exit(0)

    # Check if Phocus is running
    if not check_phocus_running():
        response = show_alert(
            "Phocus Not Running",
            "Phocus doesn't appear to be running. Please start Phocus first, then click OK to continue.",
            ["OK", "Cancel"]
        )
        if "Cancel" in response:
            sys.exit(0)

        if not check_phocus_running():
            show_alert(
                "Phocus Still Not Running",
                "Phocus still isn't running. The monitor will wait for it to start."
            )

    # Get output directory
    output_dir = get_output_directory()

    # Get duration (optional)
    duration_str = show_input_dialog(
        "How long should monitoring run?\\n(Enter seconds, or leave blank for manual stop with Ctrl+C)",
        ""
    )

    # Build paths
    venv_python = install_dir / ".venv" / "bin" / "python3"
    script_path = install_dir / "monitor_phocus.py"

    # Build duration argument
    duration_arg = ""
    if duration_str and duration_str.strip().isdigit():
        duration_arg = f" -d {duration_str.strip()}"

    # Show info
    show_alert(
        "Starting Monitor",
        f"The monitor will now start.\\n\\nOutput will be saved to:\\n{output_dir}\\n\\nYou'll need to enter your password to allow hardware monitoring.\\n\\nA Terminal window will open - press Ctrl+C there when you want to stop.",
        ["OK"]
    )

    # Launch in Terminal with sudo
    # Use 'activate' and 'set frontmost' to ensure window comes to foreground
    terminal_script = f'''
    tell application "Terminal"
        do script "cd '{install_dir}' && sudo '{venv_python}' '{script_path}' -o '{output_dir}/'{duration_arg}; echo ''; echo 'Done! Press any key to close...'; read -n 1"
        activate
        set frontmost to true
    end tell
    tell application "System Events"
        set frontmost of process "Terminal" to true
    end tell
    '''

    subprocess.run(['osascript', '-e', terminal_script])


if __name__ == '__main__':
    main()
