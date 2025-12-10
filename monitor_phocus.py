#!/usr/bin/env python3
"""
Phocus Resource Monitor for Apple Silicon Macs

Monitors Hasselblad Phocus resource usage including memory, CPU, GPU, and
Neural Engine (ANE) activity. Generates publication-ready graphs and CSV exports.

Features:
  - Auto-detects Apple Silicon chip configuration (cores, GPU, RAM)
  - Auto-detects Phocus version from application bundle
  - Process memory tracking (RSS + children) - Phocus-specific
  - CPU usage with multi-core support - Phocus-specific
  - GPU utilization percentage and power (Watts) - System-wide
  - ANE (Neural Engine) power for HNNR operations - System-wide
  - System swap and memory pressure monitoring
  - Interactive annotations during recording
  - Flexible output path handling with directory creation

Requirements:
  - macOS on Apple Silicon (M1/M2/M3/M4 series)
  - Python 3.9+
  - psutil, matplotlib (pip install psutil matplotlib)
  - sudo access for GPU/ANE metrics via powermetrics

Usage:
  sudo python3 monitor_phocus.py [--duration SECONDS] [--interval SECONDS] [--output PATH]

Controls during recording:
  - Press Enter to add an annotation at the current timestamp
  - Press Ctrl+C to stop and generate graph

Version History:
  v2.5: Added error handling, input validation, auto Phocus version detection,
        improved --output path handling, better comments
  v2.4: Clarified graph labels - Phocus-specific vs system-wide metrics
  v2.3: Added system info detection (chip, cores, RAM) to graph title
  v2.2: Fixed ANE monitoring by removing sampler filter from powermetrics
  v2.1: Added ANE monitoring (initially broken)
  v2.0: Added GPU monitoring via powermetrics
  v1.0: Basic memory/CPU monitoring

Author: Konrad Michels (tonalphoto.com)
License: MIT
"""

import subprocess
import time
import argparse
import re
import sys
import os
import signal
import threading
import select
import plistlib
from datetime import datetime
from pathlib import Path

# =============================================================================
# Constants
# =============================================================================

VERSION = "2.5"
DEFAULT_INTERVAL = 2.0          # Sampling interval in seconds
DEFAULT_ANE_CORES = 16          # All Apple Silicon chips have 16-core ANE
POWERMETRICS_TIMEOUT = 10       # Timeout for powermetrics calls (seconds)
POWERMETRICS_SAMPLE_MS = 100    # powermetrics sampling interval (milliseconds)
MEMORY_PRESSURE_TIMEOUT = 2     # Timeout for memory_pressure command (seconds)
SYSTEM_PROFILER_TIMEOUT = 10    # Timeout for system_profiler command (seconds)

# Default Phocus application path
PHOCUS_APP_PATH = "/Applications/Phocus.app"

# =============================================================================
# Dependency checks
# =============================================================================

try:
    import psutil
except ImportError:
    print("Error: psutil not installed. Run: pip install psutil")
    sys.exit(1)

try:
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
except ImportError:
    print("Error: matplotlib not installed. Run: pip install matplotlib")
    sys.exit(1)


class PhocusMonitor:
    """
    Main monitor class that tracks Phocus resource usage over time.

    Collects memory, CPU, GPU, and ANE metrics at regular intervals,
    supports interactive annotations, and generates graphs/CSV output.
    """

    def __init__(self, interval=DEFAULT_INTERVAL, output_base=None):
        """
        Initialize the Phocus monitor.

        Args:
            interval: Sampling interval in seconds (default: 2.0)
            output_base: Base path for output files. Can be:
                - None: Uses default timestamped name in current directory
                - Directory path: Uses default name in specified directory
                - Full path with filename: Uses specified path/name
        """
        self.interval = interval
        self.output_base = self._resolve_output_path(output_base)

        # Data storage - all lists grow together, indexed by sample number
        self.timestamps = []        # datetime objects for each sample
        self.memory_mb = []         # Phocus memory usage in MB
        self.gpu_percent = []       # System-wide GPU utilization %
        self.gpu_power_mw = []      # System-wide GPU power in milliwatts
        self.ane_power_mw = []      # System-wide ANE power in milliwatts
        self.cpu_percent = []       # Phocus CPU usage (100% = 1 core)
        self.swap_used_mb = []      # System swap usage in MB
        self.memory_pressure = []   # Memory pressure: 0=normal, 1=warn, 2=critical

        # Annotations: list of (timestamp_index, label) tuples
        self.annotations = []

        # Runtime state
        self.running = True
        self.phocus_pid = None
        self.phocus_lost_count = 0  # Track consecutive failures to find Phocus

        # System and application info (populated at start)
        self.system_info = self._get_system_info()
        self.phocus_version = self._get_phocus_version()

        # Set up signal handlers for graceful shutdown
        self._setup_signal_handlers()

    def _resolve_output_path(self, output_base):
        """
        Resolve the output path, handling directories and creating them if needed.

        Args:
            output_base: User-provided output path or None

        Returns:
            Resolved output base path (without extension)
        """
        # Default timestamped filename
        default_name = f"phocus_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if output_base is None:
            # No output specified - use default in current directory
            return default_name

        path = Path(output_base)

        # Check if it looks like a directory (ends with / or exists as directory)
        if output_base.endswith(os.sep) or (path.exists() and path.is_dir()):
            # It's a directory - use default filename within it
            output_dir = path
            output_file = default_name
        else:
            # It's a file path - separate directory and filename
            output_dir = path.parent
            output_file = path.stem  # Remove any extension user might have added

        # Handle directory creation if needed
        if output_dir and str(output_dir) != '.':
            if not output_dir.exists():
                # Directory doesn't exist - prompt to create
                response = input(f"Directory '{output_dir}' does not exist. Create it? [Y/n]: ").strip().lower()
                if response in ('', 'y', 'yes'):
                    try:
                        output_dir.mkdir(parents=True, exist_ok=True)
                        print(f"Created directory: {output_dir}")
                    except OSError as e:
                        print(f"Error creating directory '{output_dir}': {e}")
                        print("Using current directory instead.")
                        return default_name
                else:
                    print("Using current directory instead.")
                    return default_name
            elif not output_dir.is_dir():
                print(f"Error: '{output_dir}' exists but is not a directory.")
                print("Using current directory instead.")
                return default_name

        # Combine directory and filename
        if output_dir and str(output_dir) != '.':
            return str(output_dir / output_file)
        return output_file

    def _setup_signal_handlers(self):
        """Set up handlers for graceful shutdown on SIGTERM/SIGINT."""
        def signal_handler(signum, frame):
            """Handle shutdown signals gracefully."""
            signal_name = signal.Signals(signum).name
            print(f"\n\nReceived {signal_name}, stopping...")
            self.running = False

        # Handle both SIGTERM (kill) and SIGINT (Ctrl+C)
        signal.signal(signal.SIGTERM, signal_handler)
        # Note: SIGINT is also caught by KeyboardInterrupt in the main loop

    def _get_phocus_version(self):
        """
        Get Phocus version from the application bundle's Info.plist.

        Returns:
            Version string (e.g., "4.0.1") or "Unknown" if not found
        """
        plist_path = Path(PHOCUS_APP_PATH) / "Contents" / "Info.plist"

        try:
            with open(plist_path, 'rb') as f:
                plist = plistlib.load(f)
                # Try CFBundleShortVersionString first (user-visible version)
                version = plist.get('CFBundleShortVersionString')
                if version:
                    return version
                # Fall back to CFBundleVersion
                return plist.get('CFBundleVersion', 'Unknown')
        except FileNotFoundError:
            # Phocus not installed at default location
            return "Unknown"
        except (plistlib.InvalidFileException, KeyError, OSError) as e:
            print(f"Warning: Could not read Phocus version: {e}")
            return "Unknown"
    
    def _get_system_info(self):
        """
        Gather Apple Silicon system information from system_profiler and ioreg.

        Returns:
            dict with keys: chip, cpu_cores, cpu_p_cores, cpu_e_cores,
                           ram_gb, gpu_cores, ane_cores
        """
        info = {
            'chip': 'Unknown',
            'cpu_cores': 0,
            'cpu_p_cores': 0,
            'cpu_e_cores': 0,
            'ram_gb': 0,
            'gpu_cores': 0,
            'ane_cores': DEFAULT_ANE_CORES  # All Apple Silicon has 16-core ANE
        }

        # Get chip name, CPU cores, and RAM from system_profiler
        try:
            result = subprocess.run(
                ['system_profiler', 'SPHardwareDataType'],
                capture_output=True, text=True, timeout=SYSTEM_PROFILER_TIMEOUT
            )

            for line in result.stdout.split('\n'):
                line = line.strip()

                # Chip name (e.g., "Chip: Apple M4 Pro")
                if line.startswith('Chip:'):
                    info['chip'] = line.split(':', 1)[1].strip()

                # Total cores (e.g., "Total Number of Cores: 14 (10 performance and 4 efficiency)")
                if 'Total Number of Cores:' in line:
                    core_part = line.split(':', 1)[1].strip()
                    # Try to parse "14 (10 performance and 4 efficiency)"
                    match = re.search(
                        r'(\d+)\s*\((\d+)\s*performance\s+and\s+(\d+)\s*efficiency\)',
                        core_part
                    )
                    if match:
                        info['cpu_cores'] = int(match.group(1))
                        info['cpu_p_cores'] = int(match.group(2))
                        info['cpu_e_cores'] = int(match.group(3))
                    else:
                        # Fallback: just get the total number
                        match = re.search(r'(\d+)', core_part)
                        if match:
                            info['cpu_cores'] = int(match.group(1))

                # Memory (e.g., "Memory: 48 GB")
                if line.startswith('Memory:'):
                    match = re.search(r'(\d+)\s*GB', line)
                    if match:
                        info['ram_gb'] = int(match.group(1))

        except subprocess.TimeoutExpired:
            print("Warning: system_profiler timed out")
        except subprocess.SubprocessError as e:
            print(f"Warning: Could not run system_profiler: {e}")
        except (ValueError, AttributeError) as e:
            print(f"Warning: Error parsing system_profiler output: {e}")

        # Get GPU core count from ioreg (separate try block - don't fail if this fails)
        try:
            gpu_result = subprocess.run(
                ['ioreg', '-l'],
                capture_output=True, text=True, timeout=SYSTEM_PROFILER_TIMEOUT
            )

            # Look for gpu-core-count in ioreg output
            for line in gpu_result.stdout.split('\n'):
                if 'gpu-core-count' in line.lower():
                    match = re.search(r'=\s*(\d+)', line)
                    if match:
                        info['gpu_cores'] = int(match.group(1))
                        break

        except subprocess.TimeoutExpired:
            print("Warning: ioreg timed out (GPU core count unavailable)")
        except subprocess.SubprocessError as e:
            print(f"Warning: Could not get GPU core count: {e}")

        return info
    
    def _format_system_info(self):
        """
        Format system info as a single-line string for graph subtitle.

        Returns:
            String like "Apple M4 Pro • 14-core CPU (10P + 4E) • 20-core GPU • 16-core Neural Engine • 64 GB RAM"
        """
        info = self.system_info

        # Build individual component strings
        chip_str = info['chip']

        # CPU cores with P/E breakdown if available
        if info['cpu_p_cores'] and info['cpu_e_cores']:
            cpu_str = f"{info['cpu_cores']}-core CPU ({info['cpu_p_cores']}P + {info['cpu_e_cores']}E)"
        elif info['cpu_cores']:
            cpu_str = f"{info['cpu_cores']}-core CPU"
        else:
            cpu_str = ""

        # GPU cores (may not be available on all systems)
        gpu_str = f"{info['gpu_cores']}-core GPU" if info['gpu_cores'] else ""

        # RAM
        ram_str = f"{info['ram_gb']} GB RAM" if info['ram_gb'] else ""

        # ANE (always present on Apple Silicon)
        ane_str = f"{info['ane_cores']}-core Neural Engine"

        # Combine non-empty parts with bullet separator
        parts = [p for p in [chip_str, cpu_str, gpu_str, ane_str, ram_str] if p]
        return " • ".join(parts)

    def _find_phocus(self):
        """
        Find the Phocus process ID.

        Returns:
            int: PID of Phocus process, or None if not running
        """
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if proc.info['name'] and 'Phocus' in proc.info['name']:
                        return proc.info['pid']
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Process disappeared or we can't access it - continue searching
                    continue
        except psutil.Error as e:
            print(f"Warning: Error searching for Phocus process: {e}")
        return None
    
    def _get_gpu_utilization(self):
        """
        Get GPU and ANE (Neural Engine) metrics from powermetrics.

        Note: Requires sudo/root access. These are system-wide metrics -
        macOS doesn't expose per-process GPU/ANE usage.

        Returns:
            tuple: (gpu_active_percent, gpu_power_mw, ane_power_mw)
                   Returns (0.0, 0.0, 0.0) on error
        """
        try:
            # Run powermetrics without sampler filter to get both GPU and ANE data
            # -i: sample interval in ms, -n: number of samples
            result = subprocess.run(
                ['powermetrics', '-i', str(POWERMETRICS_SAMPLE_MS), '-n', '1'],
                capture_output=True,
                text=True,
                timeout=POWERMETRICS_TIMEOUT
            )

            gpu_active = 0.0
            gpu_power = 0.0
            ane_power = 0.0

            for line in result.stdout.split('\n'):
                # GPU utilization percentage
                if 'GPU HW active residency:' in line:
                    match = re.search(r'GPU HW active residency:\s+([\d.]+)%', line)
                    if match:
                        gpu_active = float(match.group(1))

                # GPU power - must start with "GPU Power:" to avoid matching
                # "ANE Power:" or "Combined Power:" etc.
                if line.strip().startswith('GPU Power:'):
                    match = re.search(r'GPU Power:\s+([\d.]+)\s*mW', line)
                    if match:
                        gpu_power = float(match.group(1))

                # ANE (Neural Engine) power
                if 'ANE Power:' in line:
                    match = re.search(r'ANE Power:\s+([\d.]+)\s*mW', line)
                    if match:
                        ane_power = float(match.group(1))

            return gpu_active, gpu_power, ane_power

        except subprocess.TimeoutExpired:
            # powermetrics hung - return zeros rather than crashing
            return 0.0, 0.0, 0.0
        except subprocess.SubprocessError as e:
            # Permission denied or other subprocess error
            # This is expected when not running as root
            return 0.0, 0.0, 0.0
        except ValueError:
            # Parsing error - return zeros
            return 0.0, 0.0, 0.0

    def _get_memory_pressure(self):
        """
        Get system memory pressure level using macOS memory_pressure command.

        Returns:
            int: 0=normal, 1=warning, 2=critical
        """
        try:
            result = subprocess.run(
                ['memory_pressure'],
                capture_output=True,
                text=True,
                timeout=MEMORY_PRESSURE_TIMEOUT
            )

            output = result.stdout.lower()
            if 'critical' in output:
                return 2
            elif 'warn' in output:
                return 1
            return 0

        except subprocess.TimeoutExpired:
            return 0
        except subprocess.SubprocessError:
            return 0

    def _get_swap_usage(self):
        """
        Get system swap usage in megabytes.

        Returns:
            float: Swap usage in MB, or 0.0 on error
        """
        try:
            swap = psutil.swap_memory()
            return swap.used / (1024 * 1024)  # Convert bytes to MB
        except (OSError, psutil.Error):
            return 0.0

    def _get_process_memory(self, pid):
        """
        Get memory usage for a process and all its children.

        Phocus spawns helper processes, so we need to sum RSS across
        the entire process tree for accurate memory reporting.

        Args:
            pid: Process ID to measure

        Returns:
            float: Memory usage in MB, or None if process not found
        """
        try:
            proc = psutil.Process(pid)
            mem = proc.memory_info().rss

            # Sum memory of all child processes recursively
            for child in proc.children(recursive=True):
                try:
                    mem += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Child process disappeared or inaccessible - continue
                    pass

            return mem / (1024 * 1024)  # Convert bytes to MB

        except psutil.NoSuchProcess:
            # Process no longer exists
            return None
        except psutil.AccessDenied:
            # Can't access process info (shouldn't happen with sudo)
            return None

    def _get_process_cpu(self, pid):
        """
        Get CPU usage for a process and all its children.

        Note: CPU percentage is relative to a single core, so values > 100%
        indicate multi-core usage (e.g., 400% = 4 cores fully utilized).

        Args:
            pid: Process ID to measure

        Returns:
            float: CPU percentage, or None if process not found
        """
        try:
            proc = psutil.Process(pid)
            # interval=0.1 gives a brief measurement window for accurate reading
            cpu = proc.cpu_percent(interval=0.1)

            # Add CPU usage of all child processes
            for child in proc.children(recursive=True):
                try:
                    cpu += child.cpu_percent(interval=0.05)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Child process disappeared - continue
                    pass

            return cpu

        except psutil.NoSuchProcess:
            return None
        except psutil.AccessDenied:
            return None

    def _sample(self):
        """
        Take a single sample of all metrics.

        Returns:
            bool: True if sample was successful, False if Phocus not found
            str or None: Warning message if Phocus was lost and refound, None otherwise
        """
        warning_msg = None

        # Try to find Phocus if we don't have a PID
        if not self.phocus_pid:
            self.phocus_pid = self._find_phocus()
            if not self.phocus_pid:
                return False, None

        # Get Phocus-specific metrics
        memory = self._get_process_memory(self.phocus_pid)

        if memory is None:
            # Phocus process disappeared - try to find it again
            self.phocus_lost_count += 1

            if self.phocus_lost_count >= 3:
                # Phocus has been gone for multiple samples - it probably quit
                warning_msg = "Phocus process lost. Searching..."

            old_pid = self.phocus_pid
            self.phocus_pid = self._find_phocus()

            if self.phocus_pid:
                if self.phocus_pid != old_pid:
                    warning_msg = f"Phocus restarted (new PID: {self.phocus_pid})"
                self.phocus_lost_count = 0
                # Try again with new PID
                memory = self._get_process_memory(self.phocus_pid)
                if memory is None:
                    return False, warning_msg
            else:
                return False, warning_msg

        # Reset lost count on successful sample
        self.phocus_lost_count = 0

        # Get remaining metrics
        cpu = self._get_process_cpu(self.phocus_pid)
        gpu_active, gpu_power, ane_power = self._get_gpu_utilization()
        swap = self._get_swap_usage()
        pressure = self._get_memory_pressure()

        # Store all metrics
        self.timestamps.append(datetime.now())
        self.memory_mb.append(memory)
        self.cpu_percent.append(cpu or 0)
        self.gpu_percent.append(gpu_active)
        self.gpu_power_mw.append(gpu_power)
        self.ane_power_mw.append(ane_power)
        self.swap_used_mb.append(swap)
        self.memory_pressure.append(pressure)

        return True, warning_msg
    
    def _add_annotation(self, label):
        """
        Add an annotation at the current timestamp.

        Args:
            label: Text label for the annotation

        Returns:
            bool: True if annotation was added, False if no data collected yet
        """
        if self.timestamps:
            idx = len(self.timestamps) - 1
            self.annotations.append((idx, label))
            return True
        return False

    def _save_csv(self):
        """
        Save collected data to a CSV file with metadata header.

        The CSV includes:
        - Comment header with version, system info, and recording time
        - Columns for all metrics plus annotations

        Returns:
            str: Path to the saved CSV file
        """
        csv_path = f"{self.output_base}.csv"

        try:
            with open(csv_path, 'w') as f:
                # Write metadata header as comments
                f.write(f"# Phocus Resource Monitor v{VERSION}\n")
                f.write(f"# Phocus Version: {self.phocus_version}\n")
                f.write(f"# System: {self._format_system_info()}\n")
                f.write(f"# Recorded: {self.timestamps[0].strftime('%Y-%m-%d %H:%M:%S') if self.timestamps else 'N/A'}\n")
                f.write(f"# Samples: {len(self.timestamps)}, Interval: {self.interval}s\n")
                f.write("#\n")

                # Column headers
                f.write("timestamp,elapsed_seconds,memory_mb,cpu_percent,gpu_percent,"
                        "gpu_power_mw,ane_power_mw,swap_mb,memory_pressure,annotation\n")

                start_time = self.timestamps[0] if self.timestamps else datetime.now()

                # Create annotation lookup dict for O(1) access
                annotation_lookup = {idx: label for idx, label in self.annotations}

                # Write data rows
                for i, ts in enumerate(self.timestamps):
                    elapsed = (ts - start_time).total_seconds()
                    annotation = annotation_lookup.get(i, "")
                    # Escape commas in annotation text
                    if ',' in annotation:
                        annotation = f'"{annotation}"'
                    f.write(
                        f"{ts.isoformat()},"
                        f"{elapsed:.1f},"
                        f"{self.memory_mb[i]:.1f},"
                        f"{self.cpu_percent[i]:.1f},"
                        f"{self.gpu_percent[i]:.1f},"
                        f"{self.gpu_power_mw[i]:.1f},"
                        f"{self.ane_power_mw[i]:.1f},"
                        f"{self.swap_used_mb[i]:.1f},"
                        f"{self.memory_pressure[i]},"
                        f"{annotation}\n"
                    )

            print(f"Data saved to: {csv_path}")
            return csv_path

        except OSError as e:
            print(f"Error saving CSV file: {e}")
            return None
    
    def _generate_plot(self):
        """
        Generate a publication-ready multi-panel plot showing all metrics.

        Creates a 5-panel figure:
        1. Memory (with swap on secondary axis)
        2. GPU utilization %
        3. CPU usage %
        4. GPU power (Watts)
        5. ANE power (Watts)

        Annotations appear as vertical dashed lines with labels.
        A summary statistics bar appears at the bottom.

        Returns:
            str: Path to saved PNG file, or None on error
        """
        if not self.timestamps:
            print("No data to plot!")
            return None

        # Calculate elapsed time in minutes for x-axis
        start_time = self.timestamps[0]
        elapsed_minutes = [(ts - start_time).total_seconds() / 60 for ts in self.timestamps]
        duration_min = elapsed_minutes[-1] if elapsed_minutes else 0

        # Convert memory units: MB -> GB for readability
        memory_gb = [m / 1024 for m in self.memory_mb]
        swap_gb = [s / 1024 for s in self.swap_used_mb]

        # Set up the figure with seaborn style for clean look
        try:
            plt.style.use('seaborn-v0_8-whitegrid')
        except OSError:
            # Fallback if seaborn style not available
            plt.style.use('ggplot')

        fig = plt.figure(figsize=(14, 12))

        # GridSpec for custom panel heights - memory panel is larger
        gs = gridspec.GridSpec(5, 1, height_ratios=[3, 2, 2, 1, 1], hspace=0.3)

        # Color palette - chosen for good contrast and colorblind accessibility
        color_mem = '#2E86AB'       # Blue - memory
        color_swap = '#A23B72'      # Purple - swap
        color_gpu = '#E94F37'       # Red - GPU utilization
        color_cpu = '#F18F01'       # Orange - CPU
        color_ane = '#9C27B0'       # Magenta - Neural Engine
        color_annotation = '#2E7D32'  # Green - annotation markers

        # =====================================================================
        # Panel 1: Memory (Phocus-specific) with Swap (system-wide) overlay
        # =====================================================================
        ax1 = fig.add_subplot(gs[0])
        ax1.fill_between(elapsed_minutes, memory_gb, alpha=0.3, color=color_mem)
        ax1.plot(elapsed_minutes, memory_gb, color=color_mem, linewidth=2, label='Phocus Memory')

        # Add swap on secondary y-axis if there's meaningful swap usage
        if max(swap_gb) > 0.01:
            ax1_swap = ax1.twinx()
            ax1_swap.plot(elapsed_minutes, swap_gb, color=color_swap,
                          linewidth=1.5, linestyle='--', label='System Swap', alpha=0.8)
            ax1_swap.set_ylabel('Swap (GB)', fontsize=10, color=color_swap)
            ax1_swap.tick_params(axis='y', labelcolor=color_swap)
            ax1_swap.set_ylim(bottom=0)

        ax1.set_ylabel('Memory (GB)', fontsize=11, color=color_mem)
        ax1.tick_params(axis='y', labelcolor=color_mem)
        ax1.set_ylim(bottom=0)
        ax1.set_xlim(0, duration_min)
        ax1.legend(loc='upper left', fontsize=9)

        # Main title with Phocus version (auto-detected)
        version_str = f" {self.phocus_version}" if self.phocus_version != "Unknown" else ""
        main_title = f'Phocus{version_str} Resource Usage — {duration_min:.1f} minute session'
        fig.suptitle(main_title, fontsize=14, fontweight='bold', y=0.98)

        # System info subtitle (smaller, italicized)
        system_subtitle = self._format_system_info()
        fig.text(0.5, 0.95, system_subtitle, ha='center', fontsize=10,
                 color='#555555', style='italic')
        
        # Add annotation markers to memory panel (labels only on this panel)
        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                x = elapsed_minutes[idx]
                y = memory_gb[idx]
                ax1.axvline(x=x, color=color_annotation, linestyle=':', alpha=0.7, linewidth=1)
                ax1.annotate(label, xy=(x, y), xytext=(5, 10), textcoords='offset points',
                             fontsize=8, color=color_annotation, fontweight='bold',
                             bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                                       edgecolor=color_annotation, alpha=0.8))

        # =====================================================================
        # Panel 2: GPU Utilization % (system-wide)
        # =====================================================================
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.fill_between(elapsed_minutes, self.gpu_percent, alpha=0.3, color=color_gpu)
        ax2.plot(elapsed_minutes, self.gpu_percent, color=color_gpu, linewidth=1.5,
                 label='GPU Active (System)')
        ax2.set_ylabel('GPU (%)', fontsize=11, color=color_gpu)
        ax2.tick_params(axis='y', labelcolor=color_gpu)
        ax2.set_ylim(0, 100)
        ax2.legend(loc='upper left', fontsize=9)

        # Add annotation lines (no labels - they're on panel 1)
        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                ax2.axvline(x=elapsed_minutes[idx], color=color_annotation,
                            linestyle=':', alpha=0.5, linewidth=1)

        # =====================================================================
        # Panel 3: CPU Usage % (Phocus-specific)
        # =====================================================================
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        ax3.fill_between(elapsed_minutes, self.cpu_percent, alpha=0.3, color=color_cpu)
        ax3.plot(elapsed_minutes, self.cpu_percent, color=color_cpu, linewidth=1.5,
                 label='Phocus CPU')
        ax3.set_ylabel('CPU (%)', fontsize=11, color=color_cpu)
        ax3.tick_params(axis='y', labelcolor=color_cpu)
        ax3.set_ylim(bottom=0)
        ax3.legend(loc='upper left', fontsize=9)

        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                ax3.axvline(x=elapsed_minutes[idx], color=color_annotation,
                            linestyle=':', alpha=0.5, linewidth=1)

        # =====================================================================
        # Panel 4: GPU Power in Watts (system-wide)
        # =====================================================================
        ax4 = fig.add_subplot(gs[3], sharex=ax1)
        gpu_power_w = [p / 1000 for p in self.gpu_power_mw]  # mW -> W
        ax4.fill_between(elapsed_minutes, gpu_power_w, alpha=0.3, color='#666666')
        ax4.plot(elapsed_minutes, gpu_power_w, color='#666666', linewidth=1,
                 label='GPU Power (System)')
        ax4.set_ylabel('GPU (W)', fontsize=10, color='#666666')
        ax4.set_ylim(bottom=0)
        ax4.legend(loc='upper left', fontsize=9)

        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                ax4.axvline(x=elapsed_minutes[idx], color=color_annotation,
                            linestyle=':', alpha=0.5, linewidth=1)

        # =====================================================================
        # Panel 5: ANE (Neural Engine) Power in Watts (system-wide)
        # This panel is key for confirming HNNR uses the Neural Engine
        # =====================================================================
        ax5 = fig.add_subplot(gs[4], sharex=ax1)
        ane_power_w = [p / 1000 for p in self.ane_power_mw]  # mW -> W
        ax5.fill_between(elapsed_minutes, ane_power_w, alpha=0.3, color=color_ane)
        ax5.plot(elapsed_minutes, ane_power_w, color=color_ane, linewidth=1,
                 label='ANE Power (System)')
        ax5.set_ylabel('ANE (W)', fontsize=10, color=color_ane)
        ax5.tick_params(axis='y', labelcolor=color_ane)
        ax5.set_xlabel('Time (minutes)', fontsize=11)
        ax5.set_ylim(bottom=0)
        ax5.legend(loc='upper left', fontsize=9)

        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                ax5.axvline(x=elapsed_minutes[idx], color=color_annotation,
                            linestyle=':', alpha=0.5, linewidth=1)

        # Hide x-axis labels on upper panels (only bottom panel shows time)
        plt.setp(ax1.get_xticklabels(), visible=False)
        plt.setp(ax2.get_xticklabels(), visible=False)
        plt.setp(ax3.get_xticklabels(), visible=False)
        plt.setp(ax4.get_xticklabels(), visible=False)

        # =====================================================================
        # Summary statistics bar at bottom of figure
        # =====================================================================
        avg_mem = sum(memory_gb) / len(memory_gb)
        max_mem = max(memory_gb)
        avg_gpu = sum(self.gpu_percent) / len(self.gpu_percent)
        max_gpu = max(self.gpu_percent)
        avg_cpu = sum(self.cpu_percent) / len(self.cpu_percent)
        max_cpu = max(self.cpu_percent)
        avg_gpu_power = sum(self.gpu_power_mw) / len(self.gpu_power_mw) / 1000
        max_gpu_power = max(self.gpu_power_mw) / 1000
        avg_ane_power = sum(self.ane_power_mw) / len(self.ane_power_mw) / 1000
        max_ane_power = max(self.ane_power_mw) / 1000
        max_swap = max(swap_gb)

        stats_text = (
            f"Memory: avg {avg_mem:.1f} GB, max {max_mem:.1f} GB  |  "
            f"GPU: avg {avg_gpu:.0f}%, max {max_gpu:.0f}%  |  "
            f"CPU: avg {avg_cpu:.0f}%, max {max_cpu:.0f}%  |  "
            f"GPU Power: avg {avg_gpu_power:.1f}W, max {max_gpu_power:.1f}W  |  "
            f"ANE: avg {avg_ane_power:.1f}W, max {max_ane_power:.1f}W  |  "
            f"Max Swap: {max_swap:.2f} GB"
        )

        fig.text(0.5, 0.02, stats_text, ha='center', fontsize=9,
                 bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

        # Final layout adjustments
        plt.subplots_adjust(bottom=0.08, top=0.91)

        # =====================================================================
        # Save output files
        # =====================================================================
        try:
            # Standard resolution for web/screen viewing
            plot_path = f"{self.output_base}.png"
            plt.savefig(plot_path, dpi=150, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            print(f"Plot saved to: {plot_path}")

            # High resolution for print/publication
            plot_path_hires = f"{self.output_base}_hires.png"
            plt.savefig(plot_path_hires, dpi=300, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            print(f"High-res plot saved to: {plot_path_hires}")

            plt.close()
            return plot_path

        except OSError as e:
            print(f"Error saving plot: {e}")
            plt.close()
            return None

    def _input_listener(self):
        """
        Background thread that listens for annotation input from the user.

        Uses select() for non-blocking input on Unix systems.
        When user presses Enter, prompts for an annotation label.
        """
        while self.running:
            try:
                # Use select for non-blocking input check (0.5s timeout)
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        # User typed something and pressed Enter
                        self._add_annotation(line)
                        print(f"\n  Annotation added: \"{line}\"")
                    else:
                        # Just Enter pressed - prompt for label
                        print("\n  Enter annotation label: ", end='', flush=True)
                        label = sys.stdin.readline().strip()
                        if label:
                            self._add_annotation(label)
                            print(f"  Annotation added: \"{label}\"")
                        else:
                            # Empty label - use auto-generated mark number
                            mark_num = len(self.annotations) + 1
                            self._add_annotation(f"Mark {mark_num}")
                            print(f"  Annotation added: \"Mark {mark_num}\"")

            except (IOError, OSError):
                # stdin closed or other I/O error - stop listening
                break
            except select.error:
                # select interrupted - check if we should stop
                if not self.running:
                    break

    def run(self, duration=None):
        """
        Main monitoring loop.

        Displays system info, starts monitoring Phocus, and collects samples
        until duration is reached or user presses Ctrl+C.

        Args:
            duration: Optional maximum duration in seconds (None = unlimited)
        """
        # =====================================================================
        # Display header and configuration
        # =====================================================================
        print(f"╔══════════════════════════════════════════════╗")
        print(f"║   Phocus Resource Monitor v{VERSION}              ║")
        print(f"╚══════════════════════════════════════════════╝")

        # Display detected system information
        print(f"\n  System: {self.system_info['chip']}")
        if self.system_info['cpu_p_cores'] and self.system_info['cpu_e_cores']:
            print(f"    CPU: {self.system_info['cpu_cores']} cores "
                  f"({self.system_info['cpu_p_cores']}P + {self.system_info['cpu_e_cores']}E)")
        elif self.system_info['cpu_cores']:
            print(f"    CPU: {self.system_info['cpu_cores']} cores")
        if self.system_info['gpu_cores']:
            print(f"    GPU: {self.system_info['gpu_cores']} cores")
        print(f"    ANE: {self.system_info['ane_cores']}-core Neural Engine")
        print(f"    RAM: {self.system_info['ram_gb']} GB")

        # Display Phocus version if detected
        if self.phocus_version != "Unknown":
            print(f"\n  Phocus: v{self.phocus_version}")

        # Display monitoring configuration
        print(f"\n  Interval: {self.interval}s")
        print(f"  Output: {self.output_base}.*")
        if duration:
            print(f"  Duration: {duration}s")
        print()
        print("  Controls:")
        print("    Press Enter to add an annotation")
        print("    Press Ctrl+C to stop and generate graph")
        print()

        # =====================================================================
        # Pre-flight checks
        # =====================================================================

        # Check for root access (required for powermetrics GPU/ANE data)
        if os.geteuid() != 0:
            print("  WARNING: Not running as root. GPU/ANE monitoring requires sudo.")
            print("  Run with: sudo python3 monitor_phocus.py\n")

        # Find Phocus process
        self.phocus_pid = self._find_phocus()
        if self.phocus_pid:
            print(f"  Found Phocus (PID: {self.phocus_pid})")
        else:
            print("  Phocus not running. Will wait for it to start...")

        # Test GPU and ANE monitoring
        gpu_test, power_test, ane_test = self._get_gpu_utilization()
        print(f"  GPU monitoring active (current: {gpu_test:.1f}%, {power_test:.0f} mW)")
        print(f"  ANE monitoring active (current: {ane_test:.0f} mW)")

        # Test memory pressure
        pressure = self._get_memory_pressure()
        pressure_str = ['Normal', 'Warning', 'Critical'][pressure]
        print(f"  Memory pressure: {pressure_str}")

        # Test swap
        swap = self._get_swap_usage()
        print(f"  Swap monitoring active (current: {swap:.0f} MB)")
        print()
        print("Recording started...")
        print("-" * 60)

        # =====================================================================
        # Start monitoring
        # =====================================================================

        # Start background thread for annotation input
        input_thread = threading.Thread(target=self._input_listener, daemon=True)
        input_thread.start()

        start_time = time.time()
        sample_count = 0
        phocus_wait_printed = False

        try:
            while self.running:
                # Check if we've reached the duration limit
                if duration and (time.time() - start_time) >= duration:
                    print("\n\nDuration reached.")
                    break

                # Take a sample
                success, warning_msg = self._sample()

                if warning_msg:
                    print(f"\n  {warning_msg}")

                if success:
                    sample_count += 1
                    phocus_wait_printed = False

                    # Format current metrics for display
                    mem = self.memory_mb[-1] / 1024  # MB -> GB
                    gpu = self.gpu_percent[-1]
                    cpu = self.cpu_percent[-1]
                    gpu_pwr = self.gpu_power_mw[-1] / 1000  # mW -> W
                    ane_pwr = self.ane_power_mw[-1] / 1000  # mW -> W
                    elapsed = (time.time() - start_time) / 60

                    # Show ANE only when active (>0) to save display space
                    ane_str = f" | ANE:{ane_pwr:.1f}W" if ane_pwr > 0 else ""

                    # Single-line status update (overwrites previous)
                    status = (f"\r[{elapsed:5.1f}m] Mem:{mem:5.1f}GB | GPU:{gpu:5.1f}% | "
                              f"CPU:{cpu:5.0f}% | Pwr:{gpu_pwr:4.1f}W{ane_str} | #{sample_count}")
                    print(status, end='', flush=True)
                else:
                    # Phocus not found - only print waiting message once
                    if not phocus_wait_printed:
                        print("\r  Waiting for Phocus...                                        ",
                              end='', flush=True)
                        phocus_wait_printed = True

                time.sleep(self.interval)

        except KeyboardInterrupt:
            print("\n\nStopping...")

        # =====================================================================
        # Cleanup and save output
        # =====================================================================
        self.running = False
        print(f"\nCollected {len(self.timestamps)} samples, {len(self.annotations)} annotations.")

        if self.timestamps:
            self._save_csv()
            self._generate_plot()
        else:
            print("No data collected - Phocus may not have been running.")


def validate_args(args):
    """
    Validate command line arguments.

    Args:
        args: Parsed argparse namespace

    Returns:
        tuple: (is_valid, error_message)
    """
    # Validate interval
    if args.interval <= 0:
        return False, "Error: --interval must be a positive number"
    if args.interval < 0.1:
        return False, "Error: --interval must be at least 0.1 seconds"
    if args.interval > 3600:
        return False, "Error: --interval cannot exceed 3600 seconds (1 hour)"

    # Validate duration if provided
    if args.duration is not None:
        if args.duration <= 0:
            return False, "Error: --duration must be a positive number"
        if args.duration < args.interval:
            return False, "Error: --duration must be at least as long as --interval"

    return True, None


def main():
    """
    Entry point for the Phocus Resource Monitor.

    Parses command line arguments, validates them, and starts monitoring.
    """
    parser = argparse.ArgumentParser(
        description='Monitor Phocus resource usage on Apple Silicon Macs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sudo python3 monitor_phocus.py                    # Monitor indefinitely
  sudo python3 monitor_phocus.py -d 300             # Monitor for 5 minutes
  sudo python3 monitor_phocus.py -i 0.5             # Sample every 0.5 seconds
  sudo python3 monitor_phocus.py -o ~/results/test  # Save to ~/results/test.*
  sudo python3 monitor_phocus.py -o ~/results/      # Save to ~/results/ with default name

Note: sudo is required for GPU and Neural Engine monitoring via powermetrics.
        """
    )

    parser.add_argument(
        '--duration', '-d',
        type=float,
        metavar='SECONDS',
        help='Maximum duration in seconds (default: unlimited)'
    )
    parser.add_argument(
        '--interval', '-i',
        type=float,
        default=DEFAULT_INTERVAL,
        metavar='SECONDS',
        help=f'Sampling interval in seconds (default: {DEFAULT_INTERVAL})'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        metavar='PATH',
        help='Output path: directory (uses default name) or full path (default: ./phocus_monitor_TIMESTAMP)'
    )
    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f'Phocus Resource Monitor v{VERSION}'
    )

    args = parser.parse_args()

    # Validate arguments
    is_valid, error_msg = validate_args(args)
    if not is_valid:
        print(error_msg)
        sys.exit(1)

    # Create monitor and run
    try:
        monitor = PhocusMonitor(interval=args.interval, output_base=args.output)
        monitor.run(duration=args.duration)
    except KeyboardInterrupt:
        # Handle Ctrl+C during initialization
        print("\nAborted.")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
