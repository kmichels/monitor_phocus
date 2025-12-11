# CLAUDE.md — Project Context for Claude Code

## Project Overview

This is a Python-based resource monitoring tool for Hasselblad Phocus 4.x running on Apple Silicon Macs. It was developed to understand and document how Phocus utilizes system resources, particularly to confirm whether features like HNNR (Hasselblad Neural Network Noise Reduction) actually use Apple's Neural Engine.

**Owner:** Konrad (tonalphoto.com)
**Purpose:** Technical documentation for Hasselblad users; blog content; community resource
**Current Version:** 2.5.1  

## What the Tool Does

The script monitors a running Phocus process and collects:

| Metric | Scope | Source | Notes |
|--------|-------|--------|-------|
| Memory (RSS) | Phocus + children | psutil | Includes child processes |
| CPU % | Phocus + children | psutil | 100% = 1 core |
| GPU Active % | System-wide | powermetrics | macOS doesn't expose per-process |
| GPU Power (W) | System-wide | powermetrics | |
| ANE Power (W) | System-wide | powermetrics | Confirms Neural Engine usage |
| Swap | System-wide | psutil | |
| Thread Count | Phocus | psutil | For threading analysis |

Outputs:
- PNG graph (5-panel, publication-ready)
- CSV data file with metadata header

## Key Technical Decisions

### Why powermetrics requires sudo
`powermetrics` is an Apple system tool that reads hardware power data. It requires root access. There's no way around this for GPU/ANE metrics.

### Why GPU and ANE are system-wide
macOS does not expose per-process GPU utilization. This is a platform limitation, not something we can work around. We document this caveat clearly.

### Why we track child processes for memory
Phocus spawns helper processes. Using `psutil.Process.memory_info()` alone misses these. We sum RSS across the process tree using `proc.children(recursive=True)`.

### ANE monitoring approach
We parse powermetrics output for `ane_power` field. Early versions filtered powermetrics output with `--samplers gpu_power` which excluded ANE data — this was fixed in v2.2.

### System info detection
We auto-detect chip name, CPU cores (P+E breakdown), GPU cores, Neural Engine cores, and RAM via `system_profiler` and `ioreg`. This appears in the graph subtitle and CSV header.

## File Structure

```
phocus-monitor/
├── monitor_phocus.py    # Main script (single file)
├── README.md            # User-facing documentation
├── CLAUDE.md            # This file
├── requirements.txt     # Python dependencies
├── LICENSE              # MIT
└── examples/            # Sample output images (optional)
```

## Dependencies

- Python 3.9+
- psutil
- matplotlib

No other dependencies. Intentionally kept simple for easy installation.

## Version History

- **v1.0** — Basic memory/CPU monitoring
- **v2.0** — Added GPU monitoring via powermetrics
- **v2.1** — Added ANE monitoring (initially broken)
- **v2.2** — Fixed ANE monitoring (removed sampler filter)
- **v2.3** — Added system info detection and display
- **v2.4** — Clarified metric labels (Phocus-specific vs system-wide)
- **v2.5** — Error handling, input validation, Phocus version auto-detection, improved --output path handling, graceful Phocus exit handling, better comments
- **v2.5.1** — Fixed ioreg encoding issue (non-UTF-8 bytes), improved error messages for venv setup, switched to venv-based installation

## Planned Enhancements

### Per-Core Distribution Visualization (not yet implemented)
A separate visualization mode showing load distribution across P-cores and E-cores, plus Phocus thread count. Would be invoked via `--core-distribution` flag.

**Limitation discovered:** macOS doesn't support per-process CPU core affinity or querying which core a thread runs on. We can only show system-wide per-core utilization, with appropriate caveats.

### Disk I/O (considered, deferred)
Could add read/write throughput via `psutil.Process.io_counters()`. Deferred because SSDs are rarely the bottleneck for photo editing workflows.

## Key Findings from Testing

These findings should be preserved and inform future development:

1. **HNNR genuinely uses the Neural Engine** — 1.0-1.6W ANE power draw during processing, confirmed across multiple tests

2. **HNNR is a hybrid workload** — Uses CPU + GPU + ANE together, not pure Neural Engine

3. **Memory accumulation during browsing** — Each image selection adds ~2-3GB to memory. Phocus caches aggressively and doesn't release until restart. This is the major discovery — explains why users with 16GB Macs struggle.

4. **GPU Power vs GPU %** — Same GPU utilization percentage can have very different power draws depending on workload type (rendering vs ML inference)

5. **Consistent behavior across M4 Pro configs** — Similar patterns on 12-core/48GB MacBook and 14-core/64GB Mac Mini

## Testing Notes

- Tests run on M4 Pro MacBook (12-core CPU, 16-core GPU, 48GB RAM) and M4 Pro Mac Mini (14-core CPU, 20-core GPU, 64GB RAM)
- Test files: X2D II 100MP RAW files
- Phocus version: 4.0.1

## Blog Post Context

This tool supports a blog post titled "What Phocus Is Actually Doing to Your Mac — GPU, CPU, Memory, and Neural Engine Under the Hood" on tonalphoto.com.

Related posts:
- "Understanding Hasselblad Phocus on macOS" (HNCS, HNNR explanation)
- "How Phocus Handles Highlight Recovery, Shadow Fill, and White Balance"

## Code Style Notes

- Single-file script (no package structure) for easy distribution
- Extensive inline comments
- Self-contained — all functions in one file
- Graph styling uses consistent color scheme with good contrast
- Annotation system uses simple Enter-to-mark approach

## Common Issues

1. **"Phocus is not running"** — Script requires Phocus to already be running
2. **GPU/ANE data missing or zero** — Usually means not running with sudo
3. **Mac Mini sometimes doesn't report GPU core count** — Unknown ioreg issue, falls back gracefully

## Contact

For questions about this project, contact Konrad via tonalphoto.com or the associated GitHub issues.
