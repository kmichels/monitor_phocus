# Phocus Resource Monitor for Apple Silicon

A Python tool that monitors Hasselblad Phocus 4.x resource usage on Apple Silicon Macs, generating annotated graphs showing memory, CPU, GPU, and Neural Engine activity.

## What This Tool Does

When you run this script, it watches Phocus in the background and records:

- **Memory usage** (Phocus-specific) — How much RAM Phocus is consuming
- **CPU usage** (Phocus-specific) — How hard Phocus is working your processor
- **GPU utilization** (system-wide) — Graphics processor activity percentage
- **GPU power draw** (system-wide) — How much power the GPU is consuming
- **Neural Engine power** (system-wide) — Apple's ML hardware activity (confirms HNNR uses the ANE!)
- **Swap usage** (system-wide) — How much disk is being used as overflow memory

When you stop monitoring, it generates a publication-ready graph with all this data, plus a CSV file for further analysis.

### Why "System-Wide" for Some Metrics?

macOS doesn't expose per-application GPU or Neural Engine usage. Memory and CPU are definitely Phocus-specific, but GPU and ANE reflect your whole system. For best results, close other apps during testing.

---

## Requirements

- **macOS** on Apple Silicon (M1, M2, M3, M4 series)
- **Phocus 4.x** installed
- **Python 3.9+** (we'll install this via Homebrew)
- **Administrator access** (the script needs `sudo` to read hardware metrics)

---

## Installation

If you're comfortable with Terminal and Python, skip to the [Quick Start](#quick-start). Otherwise, follow these step-by-step instructions.

### Step 1: Open Terminal

Terminal is a built-in macOS app that lets you type commands directly to your computer.

1. Press `Cmd + Space` to open Spotlight
2. Type `Terminal` and press Enter
3. A window with a command prompt will appear

You'll be typing commands into this window for the following steps.

### Step 2: Download the Script

**Option A: Clone the repository (if you have git):**
```bash
cd ~/Downloads
git clone https://github.com/kmichels/monitor_phocus.git
cd monitor_phocus
```

**Option B: Download directly:**
1. Click the green "Code" button on GitHub
2. Click "Download ZIP"
3. Extract the ZIP file
4. Open Terminal and navigate to the folder:
   ```bash
   cd ~/Downloads/monitor_phocus
   ```

### Step 3: Set Up Python Environment

Your Mac comes with Python 3, which is all we need. We'll create a "virtual environment" — an isolated space for this project's dependencies that won't affect anything else on your system.

**Create the virtual environment:**
```bash
python3 -m venv .venv
```

This creates a `.venv` folder containing a private copy of Python for this project.

**Install the required packages:**
```bash
.venv/bin/pip install -r requirements.txt
```

This installs `psutil` (for reading process info) and `matplotlib` (for generating graphs) into the virtual environment.

That's it! The setup is complete.

---

## Quick Start

If you followed the installation steps above, you're ready to go.

### Running the Monitor

1. **Open Phocus** (the script monitors an already-running Phocus)

2. **Open Terminal** and navigate to where you saved the script:
   ```bash
   cd ~/Downloads/monitor_phocus
   ```

3. **Run the script with sudo:**
   ```bash
   sudo .venv/bin/python3 monitor_phocus.py
   ```

   Enter your Mac password when prompted. (You need `sudo` because reading GPU and Neural Engine data requires administrator privileges. We use the full path `.venv/bin/python3` because `sudo` doesn't inherit your shell environment.)

4. **The script will start monitoring.** You'll see output like:
   ```
   ╔════════════════════════════════════════════════╗
   ║   Phocus Resource Monitor v2.5.1              ║
   ╚════════════════════════════════════════════════╝

     System: Apple M4 Pro
       CPU: 14 cores (10P + 4E)
       GPU: 20 cores
       ANE: 16-core Neural Engine
       RAM: 64 GB

     Phocus: v4.0.1

     Interval: 2.0s
     Output: phocus_monitor_20241210_143052.*

     Controls:
       Press Enter to add an annotation
       Press Ctrl+C to stop and generate graph
   ```

5. **Add annotations** by pressing Enter and typing what you're about to do:
   ```
   > HNNR start - 3 images
   ```
   These labels appear on your graph, helping you remember what was happening at each point.

6. **Perform your Phocus operations** — import images, apply HNNR, browse thumbnails, whatever you want to measure.

7. **Press Ctrl+C to stop monitoring.** The script will generate:
   - A PNG graph file (e.g., `phocus_monitor_20241210_143052.png`)
   - A CSV data file (e.g., `phocus_monitor_20241210_143052.csv`)

---

## Command Line Options

```bash
sudo .venv/bin/python3 monitor_phocus.py [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--duration SECONDS` | unlimited | Stop automatically after this many seconds |
| `--interval SECONDS` | 2.0 | How often to sample (lower = more detail, larger files) |
| `--output PATH` | auto-generated | Output path: directory or full path (see examples) |
| `--version` | — | Show version and exit |

**Examples:**

```bash
# Monitor for exactly 5 minutes
sudo .venv/bin/python3 monitor_phocus.py --duration 300

# Sample every half-second for detailed analysis
sudo .venv/bin/python3 monitor_phocus.py --interval 0.5

# Specify output filename (saves as hnnr_test_run1.png and .csv)
sudo .venv/bin/python3 monitor_phocus.py --output hnnr_test_run1

# Specify output directory (uses default timestamped name in that directory)
sudo .venv/bin/python3 monitor_phocus.py --output ~/Documents/phocus-tests/

# Full path with filename
sudo .venv/bin/python3 monitor_phocus.py --output ~/Documents/phocus-tests/my_test
```

**Note:** If you specify a directory that doesn't exist, the script will ask if you want to create it.

---

## Understanding the Output

The generated graph has 5 panels:

1. **Memory (GB)** — Phocus RAM usage (blue) and system swap (orange, right axis)
2. **GPU Active (%)** — System-wide GPU utilization
3. **CPU (%)** — Phocus CPU usage (100% = 1 full core, 200% = 2 cores, etc.)
4. **GPU Power (W)** — System-wide GPU power consumption
5. **ANE Power (W)** — Neural Engine power (spikes during HNNR confirm ML hardware usage!)

Vertical dashed lines show your annotations.

The summary bar at the bottom shows averages and maximums for each metric.

---

## Troubleshooting

### "Phocus is not running"

Start Phocus before running the script. The monitor watches an already-running Phocus process.

### "Permission denied" or no GPU/ANE data

Make sure you're running with `sudo`:
```bash
sudo .venv/bin/python3 monitor_phocus.py
```

### "No module named psutil" or "No module named matplotlib"

The virtual environment isn't set up or the packages aren't installed. Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### "No such file or directory: .venv/bin/python3"

You need to create the virtual environment first. Make sure you're in the `monitor_phocus` directory, then run:
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### The graph looks weird or has missing data

- **GPU/ANE all zeros?** Make sure you're using `sudo`
- **Memory seems too high?** Phocus caches images aggressively. This is normal — see our findings about memory accumulation during browsing.

---

## Tips for Good Data

1. **Close other apps** — GPU and ANE are system-wide metrics, so other apps will add noise
2. **Use annotations liberally** — It's hard to remember what you were doing at timestamp 3:42
3. **Let things settle** — Wait a few seconds between operations so you can see clear boundaries in the graph
4. **Longer sessions = clearer patterns** — 3-5 minute sessions work well

---

## Uninstalling

This tool doesn't install anything system-wide — everything is contained in the project folder. To completely remove it:

```bash
# Delete the entire project folder (includes venv and all dependencies)
rm -rf ~/Downloads/monitor_phocus
```

That's it. The virtual environment (`.venv/`) contains all the Python packages, so deleting the folder removes everything.

If you cloned with git and want to keep your output files:
```bash
# Keep only your CSV and PNG files
cd ~/Downloads/monitor_phocus
cp *.csv *.png ~/Desktop/  # or wherever you want them
cd ..
rm -rf monitor_phocus
```

---

## Contributing

Found a bug? Have an idea? Open an issue or PR on GitHub.

This tool was developed as part of a documentation project for Hasselblad Phocus. Read more at [tonalphoto.com](https://tonalphoto.com).

---

## License

MIT License — see [LICENSE](LICENSE) for details.
