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

### Step 2: Install Homebrew (Package Manager)

Homebrew is a tool that makes it easy to install software on your Mac. Think of it as an App Store for command-line tools.

**Check if you already have it:**
```bash
brew --version
```

If you see a version number (like `Homebrew 4.x.x`), skip to Step 3.

**If you get "command not found", install Homebrew:**
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

This will:
- Download and install Homebrew
- Ask for your Mac password (you won't see characters as you type — that's normal)
- Take a few minutes to complete

**Important:** After installation, Homebrew will show you two commands to run. They look something like:
```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Copy and run both of these commands. This adds Homebrew to your system PATH so you can use it.

### Step 3: Install Python via Homebrew

Your Mac comes with Python, but it's an older version managed by Apple. We'll install a fresh, up-to-date Python that won't interfere with your system.

```bash
brew install python
```

This installs Python 3.12 (or newer) and `pip`, Python's package installer.

**Verify it worked:**
```bash
python3 --version
```

You should see something like `Python 3.12.x`.

### Step 4: Install Required Python Packages

The script needs two additional Python libraries:

- **psutil** — For reading process information (memory, CPU, etc.)
- **matplotlib** — For generating the graphs

Install them with:
```bash
pip3 install psutil matplotlib
```

You might see some warnings about "not in PATH" — you can ignore these.

### Step 5: Download the Script

Download `monitor_phocus.py` from this repository and save it somewhere you'll remember.

**Option A: Clone the repository (if you have git):**
```bash
cd ~/Downloads
git clone https://github.com/YOUR_USERNAME/phocus-monitor.git
cd phocus-monitor
```

**Option B: Download directly:**
1. Click the green "Code" button on GitHub
2. Click "Download ZIP"
3. Extract the ZIP file
4. Note where you saved it (e.g., `~/Downloads/phocus-monitor/`)

---

## Quick Start

If you followed the installation steps above, you're ready to go.

### Running the Monitor

1. **Open Phocus** (the script monitors an already-running Phocus)

2. **Open Terminal** and navigate to where you saved the script:
   ```bash
   cd ~/Downloads/phocus-monitor
   ```

3. **Run the script with sudo:**
   ```bash
   sudo python3 monitor_phocus.py
   ```
   
   Enter your Mac password when prompted. (You need `sudo` because reading GPU and Neural Engine data requires administrator privileges.)

4. **The script will start monitoring.** You'll see output like:
   ```
   ╔══════════════════════════════════════════════╗
   ║   Phocus Resource Monitor v2.5              ║
   ╚══════════════════════════════════════════════╝

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
sudo python3 monitor_phocus.py [options]
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
sudo python3 monitor_phocus.py --duration 300

# Sample every half-second for detailed analysis
sudo python3 monitor_phocus.py --interval 0.5

# Specify output filename (saves as hnnr_test_run1.png and .csv)
sudo python3 monitor_phocus.py --output hnnr_test_run1

# Specify output directory (uses default timestamped name in that directory)
sudo python3 monitor_phocus.py --output ~/Documents/phocus-tests/

# Full path with filename
sudo python3 monitor_phocus.py --output ~/Documents/phocus-tests/my_test
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
sudo python3 monitor_phocus.py
```

### "command not found: python3"

If you installed Python via Homebrew but get this error, try using the full path:
```bash
sudo /opt/homebrew/bin/python3 monitor_phocus.py
```

Or add Homebrew's Python to your PATH (see Step 2 in Installation).

### "No module named psutil" or "No module named matplotlib"

The required packages aren't installed. Run:
```bash
pip3 install psutil matplotlib
```

If that doesn't work, try:
```bash
/opt/homebrew/bin/pip3 install psutil matplotlib
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

## Contributing

Found a bug? Have an idea? Open an issue or PR on GitHub.

This tool was developed as part of a documentation project for Hasselblad Phocus. Read more at [tonalphoto.com](https://tonalphoto.com).

---

## License

MIT License — see [LICENSE](LICENSE) for details.
