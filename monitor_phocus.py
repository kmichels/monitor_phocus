#!/usr/bin/env python3
"""
Phocus 4.x Resource Monitor v2.4 for Apple Silicon Macs
Tracks memory, GPU, CPU, ANE (Neural Engine), and memory pressure over time.
Supports annotations during recording.

Features:
  - Auto-detects Apple Silicon chip, cores, GPU, and RAM
  - Process memory tracking (RSS + children)
  - GPU utilization percentage and power (Watts)
  - ANE (Neural Engine) power for HNNR operations
  - CPU usage with multi-core support
  - System swap and memory pressure monitoring
  - Interactive annotations during recording

Requires: pip install psutil matplotlib

Usage: sudo python3 monitor_phocus_v2.py [--duration SECONDS] [--interval SECONDS] [--output FILENAME]

Controls during recording:
  - Press Enter to add an annotation at the current timestamp
  - Press Ctrl+C once to stop and generate graph

v2.4: Clarified graph labels - Phocus-specific vs system-wide metrics
v2.3: Added system info detection (chip, cores, RAM) to graph title
v2.2: Fixed ANE monitoring by removing sampler filter from powermetrics
"""

import subprocess
import time
import argparse
import re
import sys
import os
import threading
import select
from datetime import datetime

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
    def __init__(self, interval=2, output_base=None):
        self.interval = interval
        self.output_base = output_base or f"phocus_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Data storage
        self.timestamps = []
        self.memory_mb = []
        self.gpu_percent = []
        self.gpu_power_mw = []
        self.ane_power_mw = []
        self.cpu_percent = []
        self.swap_used_mb = []
        self.memory_pressure = []  # 0=normal, 1=warn, 2=critical
        
        # Annotations: list of (timestamp_index, label)
        self.annotations = []
        
        self.running = True
        self.phocus_pid = None
        
        # System info (populated at start)
        self.system_info = self.get_system_info()
    
    def get_system_info(self):
        """Gather Apple Silicon system information"""
        info = {
            'chip': 'Unknown',
            'cpu_cores': 0,
            'cpu_p_cores': 0,
            'cpu_e_cores': 0,
            'ram_gb': 0,
            'gpu_cores': 0,
            'ane_cores': 16  # All Apple Silicon has 16-core ANE
        }
        
        try:
            # Get chip name and core counts from system_profiler
            result = subprocess.run(
                ['system_profiler', 'SPHardwareDataType'],
                capture_output=True, text=True, timeout=10
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
                    match = re.search(r'(\d+)\s*\((\d+)\s*performance\s+and\s+(\d+)\s*efficiency\)', core_part)
                    if match:
                        info['cpu_cores'] = int(match.group(1))
                        info['cpu_p_cores'] = int(match.group(2))
                        info['cpu_e_cores'] = int(match.group(3))
                    else:
                        # Fallback: just get the number
                        match = re.search(r'(\d+)', core_part)
                        if match:
                            info['cpu_cores'] = int(match.group(1))
                
                # Memory (e.g., "Memory: 48 GB")
                if line.startswith('Memory:'):
                    match = re.search(r'(\d+)\s*GB', line)
                    if match:
                        info['ram_gb'] = int(match.group(1))
            
            # Try to get GPU core count from ioreg
            gpu_result = subprocess.run(
                ['ioreg', '-l'],
                capture_output=True, text=True, timeout=10
            )
            
            # Look for gpu-core-count
            for line in gpu_result.stdout.split('\n'):
                if 'gpu-core-count' in line.lower():
                    match = re.search(r'=\s*(\d+)', line)
                    if match:
                        info['gpu_cores'] = int(match.group(1))
                        break
            
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, Exception) as e:
            print(f"Warning: Could not get full system info: {e}")
        
        return info
    
    def format_system_info(self):
        """Format system info for display"""
        info = self.system_info
        
        # Build chip + cores string
        chip_str = info['chip']
        
        # CPU cores
        if info['cpu_p_cores'] and info['cpu_e_cores']:
            cpu_str = f"{info['cpu_cores']}-core CPU ({info['cpu_p_cores']}P + {info['cpu_e_cores']}E)"
        elif info['cpu_cores']:
            cpu_str = f"{info['cpu_cores']}-core CPU"
        else:
            cpu_str = ""
        
        # GPU cores
        if info['gpu_cores']:
            gpu_str = f"{info['gpu_cores']}-core GPU"
        else:
            gpu_str = ""
        
        # RAM
        ram_str = f"{info['ram_gb']} GB RAM" if info['ram_gb'] else ""
        
        # ANE
        ane_str = f"{info['ane_cores']}-core Neural Engine"
        
        # Combine non-empty parts
        parts = [p for p in [chip_str, cpu_str, gpu_str, ane_str, ram_str] if p]
        return " • ".join(parts)
        
    def find_phocus(self):
        """Find Phocus process ID"""
        for proc in psutil.process_iter(['pid', 'name']):
            if 'Phocus' in proc.info['name']:
                return proc.info['pid']
        return None
    
    def get_gpu_utilization(self):
        """Get GPU and ANE metrics from powermetrics (Apple Silicon)"""
        try:
            # Don't filter samplers - we need both gpu_power and ane_power data
            result = subprocess.run(
                ['powermetrics', '-i', '100', '-n', '1'],
                capture_output=True,
                text=True,
                timeout=10  # Increased timeout for unfiltered output
            )
            
            gpu_active = 0.0
            gpu_power = 0.0
            ane_power = 0.0
            
            for line in result.stdout.split('\n'):
                if 'GPU HW active residency:' in line:
                    match = re.search(r'GPU HW active residency:\s+([\d.]+)%', line)
                    if match:
                        gpu_active = float(match.group(1))
                
                # Match "GPU Power:" but NOT "ANE Power:" or "Combined Power:"
                if line.strip().startswith('GPU Power:'):
                    match = re.search(r'GPU Power:\s+([\d.]+)\s*mW', line)
                    if match:
                        gpu_power = float(match.group(1))
                
                if 'ANE Power:' in line:
                    match = re.search(r'ANE Power:\s+([\d.]+)\s*mW', line)
                    if match:
                        ane_power = float(match.group(1))
            
            return gpu_active, gpu_power, ane_power
            
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError):
            return 0.0, 0.0, 0.0
    
    def get_memory_pressure(self):
        """Get system memory pressure level (macOS)"""
        try:
            # Use memory_pressure command
            result = subprocess.run(
                ['memory_pressure'],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            output = result.stdout.lower()
            if 'critical' in output:
                return 2
            elif 'warn' in output:
                return 1
            else:
                return 0
        except:
            return 0
    
    def get_swap_usage(self):
        """Get swap usage in MB"""
        try:
            swap = psutil.swap_memory()
            return swap.used / (1024 * 1024)
        except:
            return 0.0
    
    def get_process_memory(self, pid):
        """Get memory usage for a process and its children in MB"""
        try:
            proc = psutil.Process(pid)
            mem = proc.memory_info().rss
            
            for child in proc.children(recursive=True):
                try:
                    mem += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            return mem / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
    
    def get_process_cpu(self, pid):
        """Get CPU usage for a process and its children"""
        try:
            proc = psutil.Process(pid)
            # Use interval=0.1 to get actual CPU usage (blocks briefly but gives real numbers)
            cpu = proc.cpu_percent(interval=0.1)
            
            for child in proc.children(recursive=True):
                try:
                    cpu += child.cpu_percent(interval=0.05)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            return cpu
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def sample(self):
        """Take a single sample of all metrics"""
        if not self.phocus_pid:
            self.phocus_pid = self.find_phocus()
            if not self.phocus_pid:
                return False
        
        memory = self.get_process_memory(self.phocus_pid)
        if memory is None:
            self.phocus_pid = self.find_phocus()
            return False
        
        cpu = self.get_process_cpu(self.phocus_pid)
        gpu_active, gpu_power, ane_power = self.get_gpu_utilization()
        swap = self.get_swap_usage()
        pressure = self.get_memory_pressure()
        
        self.timestamps.append(datetime.now())
        self.memory_mb.append(memory)
        self.cpu_percent.append(cpu or 0)
        self.gpu_percent.append(gpu_active)
        self.gpu_power_mw.append(gpu_power)
        self.ane_power_mw.append(ane_power)
        self.swap_used_mb.append(swap)
        self.memory_pressure.append(pressure)
        
        return True
    
    def add_annotation(self, label):
        """Add an annotation at the current timestamp"""
        if self.timestamps:
            idx = len(self.timestamps) - 1
            self.annotations.append((idx, label))
            return True
        return False
    
    def save_csv(self):
        """Save data to CSV file"""
        csv_path = f"{self.output_base}.csv"
        with open(csv_path, 'w') as f:
            # Write system info as comment header
            f.write(f"# Phocus Resource Monitor v2.4\n")
            f.write(f"# System: {self.format_system_info()}\n")
            f.write(f"# Recorded: {self.timestamps[0].strftime('%Y-%m-%d %H:%M:%S') if self.timestamps else 'N/A'}\n")
            f.write("timestamp,elapsed_seconds,memory_mb,cpu_percent,gpu_percent,gpu_power_mw,ane_power_mw,swap_mb,memory_pressure,annotation\n")
            start_time = self.timestamps[0] if self.timestamps else datetime.now()
            
            # Create annotation lookup
            annotation_lookup = {idx: label for idx, label in self.annotations}
            
            for i, ts in enumerate(self.timestamps):
                elapsed = (ts - start_time).total_seconds()
                annotation = annotation_lookup.get(i, "")
                f.write(f"{ts.isoformat()},{elapsed:.1f},{self.memory_mb[i]:.1f},{self.cpu_percent[i]:.1f},"
                        f"{self.gpu_percent[i]:.1f},{self.gpu_power_mw[i]:.1f},{self.ane_power_mw[i]:.1f},{self.swap_used_mb[i]:.1f},"
                        f"{self.memory_pressure[i]},{annotation}\n")
        print(f"Data saved to: {csv_path}")
        return csv_path
    
    def generate_plot(self):
        """Generate a publication-ready multi-panel plot"""
        if not self.timestamps:
            print("No data to plot!")
            return
        
        # Calculate elapsed time in minutes
        start_time = self.timestamps[0]
        elapsed_minutes = [(ts - start_time).total_seconds() / 60 for ts in self.timestamps]
        duration_min = elapsed_minutes[-1] if elapsed_minutes else 0
        
        # Convert memory to GB
        memory_gb = [m / 1024 for m in self.memory_mb]
        swap_gb = [s / 1024 for s in self.swap_used_mb]
        
        # Create figure with subplots
        plt.style.use('seaborn-v0_8-whitegrid')
        fig = plt.figure(figsize=(14, 12))
        
        # Use GridSpec for custom layout - 5 panels now
        gs = gridspec.GridSpec(5, 1, height_ratios=[3, 2, 2, 1, 1], hspace=0.3)
        
        # Color palette
        color_mem = '#2E86AB'      # Blue
        color_swap = '#A23B72'     # Purple
        color_gpu = '#E94F37'      # Red
        color_cpu = '#F18F01'      # Orange
        color_ane = '#9C27B0'      # Magenta for ANE
        color_annotation = '#2E7D32'  # Green
        
        # --- Panel 1: Memory ---
        ax1 = fig.add_subplot(gs[0])
        ax1.fill_between(elapsed_minutes, memory_gb, alpha=0.3, color=color_mem)
        ax1.plot(elapsed_minutes, memory_gb, color=color_mem, linewidth=2, label='Phocus Memory')
        
        # Add swap on secondary axis if there's any swap usage
        if max(swap_gb) > 0.01:
            ax1_swap = ax1.twinx()
            ax1_swap.plot(elapsed_minutes, swap_gb, color=color_swap, linewidth=1.5, linestyle='--', label='System Swap', alpha=0.8)
            ax1_swap.set_ylabel('Swap (GB)', fontsize=10, color=color_swap)
            ax1_swap.tick_params(axis='y', labelcolor=color_swap)
            ax1_swap.set_ylim(bottom=0)
        
        ax1.set_ylabel('Memory (GB)', fontsize=11, color=color_mem)
        ax1.tick_params(axis='y', labelcolor=color_mem)
        ax1.set_ylim(bottom=0)
        ax1.set_xlim(0, duration_min)
        ax1.legend(loc='upper left', fontsize=9)
        
        # Main title
        main_title = f'Phocus 4.0.1 Resource Usage — {duration_min:.1f} minute session'
        fig.suptitle(main_title, fontsize=14, fontweight='bold', y=0.98)
        
        # System info subtitle (smaller, not bold)
        system_subtitle = self.format_system_info()
        fig.text(0.5, 0.95, system_subtitle, ha='center', fontsize=10, 
                 color='#555555', style='italic')
        
        # Add annotations to memory panel
        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                x = elapsed_minutes[idx]
                y = memory_gb[idx]
                ax1.axvline(x=x, color=color_annotation, linestyle=':', alpha=0.7, linewidth=1)
                ax1.annotate(label, xy=(x, y), xytext=(5, 10), textcoords='offset points',
                            fontsize=8, color=color_annotation, fontweight='bold',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=color_annotation, alpha=0.8))
        
        # --- Panel 2: GPU ---
        ax2 = fig.add_subplot(gs[1], sharex=ax1)
        ax2.fill_between(elapsed_minutes, self.gpu_percent, alpha=0.3, color=color_gpu)
        ax2.plot(elapsed_minutes, self.gpu_percent, color=color_gpu, linewidth=1.5, label='GPU Active (System)')
        ax2.set_ylabel('GPU (%)', fontsize=11, color=color_gpu)
        ax2.tick_params(axis='y', labelcolor=color_gpu)
        ax2.set_ylim(0, 100)
        ax2.legend(loc='upper left', fontsize=9)
        
        # Add annotation lines to GPU panel too
        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                ax2.axvline(x=elapsed_minutes[idx], color=color_annotation, linestyle=':', alpha=0.5, linewidth=1)
        
        # --- Panel 3: CPU ---
        ax3 = fig.add_subplot(gs[2], sharex=ax1)
        ax3.fill_between(elapsed_minutes, self.cpu_percent, alpha=0.3, color=color_cpu)
        ax3.plot(elapsed_minutes, self.cpu_percent, color=color_cpu, linewidth=1.5, label='Phocus CPU')
        ax3.set_ylabel('CPU (%)', fontsize=11, color=color_cpu)
        ax3.tick_params(axis='y', labelcolor=color_cpu)
        ax3.set_ylim(bottom=0)
        ax3.legend(loc='upper left', fontsize=9)
        
        # Add annotation lines
        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                ax3.axvline(x=elapsed_minutes[idx], color=color_annotation, linestyle=':', alpha=0.5, linewidth=1)
        
        # --- Panel 4: GPU Power ---
        ax4 = fig.add_subplot(gs[3], sharex=ax1)
        gpu_power_w = [p / 1000 for p in self.gpu_power_mw]  # Convert to Watts
        ax4.fill_between(elapsed_minutes, gpu_power_w, alpha=0.3, color='#666666')
        ax4.plot(elapsed_minutes, gpu_power_w, color='#666666', linewidth=1, label='GPU Power (System)')
        ax4.set_ylabel('GPU (W)', fontsize=10, color='#666666')
        ax4.set_ylim(bottom=0)
        ax4.legend(loc='upper left', fontsize=9)
        
        # Add annotation lines
        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                ax4.axvline(x=elapsed_minutes[idx], color=color_annotation, linestyle=':', alpha=0.5, linewidth=1)
        
        # --- Panel 5: ANE Power (Neural Engine) ---
        ax5 = fig.add_subplot(gs[4], sharex=ax1)
        ane_power_w = [p / 1000 for p in self.ane_power_mw]  # Convert to Watts
        ax5.fill_between(elapsed_minutes, ane_power_w, alpha=0.3, color=color_ane)
        ax5.plot(elapsed_minutes, ane_power_w, color=color_ane, linewidth=1, label='ANE Power (System)')
        ax5.set_ylabel('ANE (W)', fontsize=10, color=color_ane)
        ax5.tick_params(axis='y', labelcolor=color_ane)
        ax5.set_xlabel('Time (minutes)', fontsize=11)
        ax5.set_ylim(bottom=0)
        ax5.legend(loc='upper left', fontsize=9)
        
        # Add annotation lines
        for idx, label in self.annotations:
            if idx < len(elapsed_minutes):
                ax5.axvline(x=elapsed_minutes[idx], color=color_annotation, linestyle=':', alpha=0.5, linewidth=1)
        
        # Hide x-axis labels on upper panels
        plt.setp(ax1.get_xticklabels(), visible=False)
        plt.setp(ax2.get_xticklabels(), visible=False)
        plt.setp(ax3.get_xticklabels(), visible=False)
        plt.setp(ax4.get_xticklabels(), visible=False)
        
        # --- Stats text box below the graph ---
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
        
        stats_text = (f"Memory: avg {avg_mem:.1f} GB, max {max_mem:.1f} GB  |  "
                      f"GPU: avg {avg_gpu:.0f}%, max {max_gpu:.0f}%  |  "
                      f"CPU: avg {avg_cpu:.0f}%, max {max_cpu:.0f}%  |  "
                      f"GPU Power: avg {avg_gpu_power:.1f}W, max {max_gpu_power:.1f}W  |  "
                      f"ANE: avg {avg_ane_power:.1f}W, max {max_ane_power:.1f}W  |  "
                      f"Max Swap: {max_swap:.2f} GB")
        
        fig.text(0.5, 0.02, stats_text, ha='center', fontsize=9, 
                 bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        # Adjust layout
        plt.subplots_adjust(bottom=0.08, top=0.91)
        
        # Save both resolutions
        plot_path = f"{self.output_base}.png"
        plt.savefig(plot_path, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
        print(f"Plot saved to: {plot_path}")
        
        plot_path_hires = f"{self.output_base}_hires.png"
        plt.savefig(plot_path_hires, dpi=300, bbox_inches='tight', facecolor='white', edgecolor='none')
        print(f"High-res plot saved to: {plot_path_hires}")
        
        plt.close()
        return plot_path

    def input_listener(self):
        """Background thread to listen for annotation input"""
        while self.running:
            try:
                # Use select for non-blocking input on Unix
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        self.add_annotation(line)
                        print(f"\n📍 Annotation added: \"{line}\"")
                    else:
                        # Just Enter pressed, prompt for label
                        print("\n📍 Enter annotation label: ", end='', flush=True)
                        label = sys.stdin.readline().strip()
                        if label:
                            self.add_annotation(label)
                            print(f"📍 Annotation added: \"{label}\"")
                        else:
                            # Empty label, use timestamp
                            self.add_annotation(f"Mark {len(self.annotations)+1}")
                            print(f"📍 Annotation added: \"Mark {len(self.annotations)}\"")
            except:
                pass

    def run(self, duration=None):
        """Main monitoring loop"""
        print(f"╔══════════════════════════════════════════╗")
        print(f"║   Phocus Resource Monitor v2.4           ║")
        print(f"╚══════════════════════════════════════════╝")
        
        # Display system info
        print(f"\n  System: {self.system_info['chip']}")
        if self.system_info['cpu_p_cores'] and self.system_info['cpu_e_cores']:
            print(f"    CPU: {self.system_info['cpu_cores']} cores ({self.system_info['cpu_p_cores']}P + {self.system_info['cpu_e_cores']}E)")
        elif self.system_info['cpu_cores']:
            print(f"    CPU: {self.system_info['cpu_cores']} cores")
        if self.system_info['gpu_cores']:
            print(f"    GPU: {self.system_info['gpu_cores']} cores")
        print(f"    ANE: {self.system_info['ane_cores']}-core Neural Engine")
        print(f"    RAM: {self.system_info['ram_gb']} GB")
        
        print(f"\n  Interval: {self.interval}s")
        print(f"  Output: {self.output_base}.*")
        if duration:
            print(f"  Duration: {duration}s")
        print()
        print("  Controls:")
        print("    • Press Enter to add an annotation")
        print("    • Press Ctrl+C to stop and generate graph")
        print()
        
        # Check for sudo
        if os.geteuid() != 0:
            print("⚠️  WARNING: Not running as root. GPU monitoring requires sudo.")
            print("   Run with: sudo python3 monitor_phocus_v2.py\n")
        
        # Find Phocus
        self.phocus_pid = self.find_phocus()
        if self.phocus_pid:
            print(f"✓ Found Phocus (PID: {self.phocus_pid})")
        else:
            print("⏳ Phocus not running. Will wait for it to start...")
        
        # Test GPU and ANE monitoring
        gpu_test, power_test, ane_test = self.get_gpu_utilization()
        print(f"✓ GPU monitoring active (current: {gpu_test:.1f}%, {power_test:.0f} mW)")
        print(f"✓ ANE monitoring active (current: {ane_test:.0f} mW)")
        
        # Test memory pressure
        pressure = self.get_memory_pressure()
        pressure_str = ['Normal', 'Warning', 'Critical'][pressure]
        print(f"✓ Memory pressure: {pressure_str}")
        
        # Test swap
        swap = self.get_swap_usage()
        print(f"✓ Swap monitoring active (current: {swap:.0f} MB)")
        print()
        print("Recording started...")
        print("-" * 60)
        
        # Start input listener thread
        input_thread = threading.Thread(target=self.input_listener, daemon=True)
        input_thread.start()
        
        start_time = time.time()
        sample_count = 0
        
        try:
            while self.running:
                if duration and (time.time() - start_time) >= duration:
                    print("\n\nDuration reached.")
                    break
                
                if self.sample():
                    sample_count += 1
                    mem = self.memory_mb[-1] / 1024
                    gpu = self.gpu_percent[-1]
                    cpu = self.cpu_percent[-1]
                    gpu_pwr = self.gpu_power_mw[-1] / 1000
                    ane_pwr = self.ane_power_mw[-1] / 1000
                    elapsed = (time.time() - start_time) / 60
                    
                    # Show ANE only when active to save space
                    ane_str = f" | ANE:{ane_pwr:.1f}W" if ane_pwr > 0 else ""
                    status = f"\r[{elapsed:5.1f}m] Mem:{mem:5.1f}GB | GPU:{gpu:5.1f}% | CPU:{cpu:5.0f}% | Pwr:{gpu_pwr:4.1f}W{ane_str} | #{sample_count}"
                    print(status, end='', flush=True)
                
                time.sleep(self.interval)
                
        except KeyboardInterrupt:
            print("\n\nStopping...")
        
        self.running = False
        print(f"\nCollected {len(self.timestamps)} samples, {len(self.annotations)} annotations.")
        
        if self.timestamps:
            self.save_csv()
            self.generate_plot()
        else:
            print("No data collected!")


def main():
    parser = argparse.ArgumentParser(description='Monitor Phocus resource usage on Apple Silicon with system info')
    parser.add_argument('--duration', '-d', type=int, help='Maximum duration in seconds (default: unlimited)')
    parser.add_argument('--interval', '-i', type=float, default=2, help='Sampling interval in seconds (default: 2)')
    parser.add_argument('--output', '-o', type=str, help='Output filename base (default: phocus_monitor_TIMESTAMP)')
    
    args = parser.parse_args()
    
    monitor = PhocusMonitor(interval=args.interval, output_base=args.output)
    monitor.run(duration=args.duration)


if __name__ == '__main__':
    main()
