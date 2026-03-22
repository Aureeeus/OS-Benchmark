"""
Benchmark Monitor
==================
Monitors and records system performance metrics for a target process.

Designed to run as a background thread alongside ``deadlock_simulation.py``
(or any other process), capturing CPU, memory, thread count, context
switches, and injectable timing metrics at a configurable sampling interval.

Cross-platform: works on Windows 11 and macOS without modification.

Usage (standalone self-test)::

    python benchmark_monitor.py

Usage (from an orchestrator)::

    import benchmark_monitor as bm

    handle = bm.start_monitoring(pid=target_pid)
    # ... run simulation ...
    csv_path = bm.stop_monitoring(handle)
"""

from __future__ import annotations

import csv
import io
import logging
import os
import platform
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import psutil

# =============================================================================
# Configuration
# =============================================================================

SAMPLING_INTERVAL_SECONDS: float = 0.5
"""Time in seconds between consecutive metric samples."""

OUTPUT_DIR: str = "results"
"""Directory where CSV result files are written."""

# =============================================================================
# Logging Setup
# =============================================================================

LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(threadName)-10s | %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> logging.Logger:
    """Configure and return the module logger with a timestamped console handler.

    Returns:
        The configured logger instance.
    """
    logger = logging.getLogger("benchmark_monitor")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        logger.addHandler(handler)

    return logger


logger: logging.Logger = configure_logging()

# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class MetricSample:
    """A single snapshot of performance metrics for the monitored process."""

    timestamp: str
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    thread_count: int
    ctx_switches_voluntary: int
    ctx_switches_involuntary: int
    lock_acquisition_ms: float
    thread_wait_ms: float


@dataclass
class MonitorHandle:
    """Handle returned by ``start_monitoring`` and consumed by ``stop_monitoring``.

    Bundles the background thread, stop event, collected samples, and system
    metadata so the caller does not need to manage internals.
    """

    thread: threading.Thread
    stop_event: threading.Event
    samples: list[MetricSample] = field(default_factory=list)
    system_info: dict[str, str] = field(default_factory=dict)
    pid: int = 0
    start_time: float = 0.0

# =============================================================================
# System Info
# =============================================================================


def get_system_info() -> dict[str, str]:
    """Capture OS name, version, and architecture once at startup.

    Returns:
        Dictionary with keys ``os_name``, ``os_version``, and ``architecture``.
    """
    return {
        "os_name": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
    }


# =============================================================================
# Metric Sampling
# =============================================================================


def sample_metrics(
    process: psutil.Process,
    lock_acquisition_ms: float = 0.0,
    thread_wait_ms: float = 0.0,
) -> MetricSample | None:
    """Collect a single snapshot of metrics from the target process.

    Args:
        process:              ``psutil.Process`` handle for the monitored PID.
        lock_acquisition_ms:  Injectable lock acquisition time (ms).
        thread_wait_ms:       Injectable per-thread wait time (ms).

    Returns:
        A ``MetricSample`` on success, or ``None`` if the process is
        inaccessible or no longer exists.
    """
    try:
        mem_info = process.memory_info()
        ctx = process.num_ctx_switches()

        return MetricSample(
            timestamp=datetime.now(timezone.utc).isoformat(),
            cpu_percent=process.cpu_percent(),
            memory_mb=round(mem_info.rss / (1024 * 1024), 2),
            memory_percent=round(process.memory_percent(), 2),
            thread_count=process.num_threads(),
            ctx_switches_voluntary=ctx.voluntary,
            ctx_switches_involuntary=ctx.involuntary,
            lock_acquisition_ms=lock_acquisition_ms,
            thread_wait_ms=thread_wait_ms,
        )

    except psutil.NoSuchProcess:
        logger.warning("Process no longer exists (PID may have exited)")
        return None

    except psutil.AccessDenied:
        logger.warning("Access denied when reading process metrics")
        return None


# =============================================================================
# Monitor Thread
# =============================================================================


def _monitor_loop(
    process: psutil.Process,
    samples: list[MetricSample],
    stop_event: threading.Event,
    lock_acquisition_ms_fn: callable | None = None,
    thread_wait_ms_fn: callable | None = None,
) -> None:
    """Internal sampling loop executed on the background monitor thread.

    Runs until ``stop_event`` is set or the target process disappears.

    Args:
        process:                 ``psutil.Process`` handle.
        samples:                 Shared list to append samples to.
        stop_event:              Event signaling the monitor to stop.
        lock_acquisition_ms_fn:  Optional callable returning current lock
                                 acquisition time (ms).  Defaults to 0.0.
        thread_wait_ms_fn:       Optional callable returning current thread
                                 wait time (ms).  Defaults to 0.0.
    """
    logger.info("Monitor loop started (sampling every %.2fs)", SAMPLING_INTERVAL_SECONDS)

    # Prime cpu_percent so the first real sample is non-zero
    try:
        process.cpu_percent()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return

    while not stop_event.is_set():
        lock_ms = lock_acquisition_ms_fn() if lock_acquisition_ms_fn else 0.0
        wait_ms = thread_wait_ms_fn() if thread_wait_ms_fn else 0.0

        sample = sample_metrics(process, lock_ms, wait_ms)

        if sample is None:
            logger.info("Target process gone -- stopping monitor")
            break

        samples.append(sample)
        logger.debug(
            "Sample #%d: CPU=%.1f%% | Mem=%.1fMB (%.1f%%) | Threads=%d",
            len(samples),
            sample.cpu_percent,
            sample.memory_mb,
            sample.memory_percent,
            sample.thread_count,
        )

        stop_event.wait(SAMPLING_INTERVAL_SECONDS)

    logger.info("Monitor loop stopped (%d samples collected)", len(samples))


# =============================================================================
# Public API
# =============================================================================


def start_monitoring(
    pid: int,
    lock_acquisition_ms_fn: callable | None = None,
    thread_wait_ms_fn: callable | None = None,
) -> MonitorHandle:
    """Start monitoring a process by PID on a background thread.

    Args:
        pid:                     Process ID to monitor.
        lock_acquisition_ms_fn:  Optional callable returning the current lock
                                 acquisition time in milliseconds.
        thread_wait_ms_fn:       Optional callable returning the current
                                 per-thread wait time in milliseconds.

    Returns:
        A ``MonitorHandle`` that must be passed to ``stop_monitoring`` later.

    Raises:
        psutil.NoSuchProcess: If the PID does not exist at startup.
    """
    process = psutil.Process(pid)
    system_info = get_system_info()
    samples: list[MetricSample] = []
    stop_event = threading.Event()

    monitor_thread = threading.Thread(
        target=_monitor_loop,
        args=(process, samples, stop_event, lock_acquisition_ms_fn, thread_wait_ms_fn),
        name="Monitor",
        daemon=True,
    )

    handle = MonitorHandle(
        thread=monitor_thread,
        stop_event=stop_event,
        samples=samples,
        system_info=system_info,
        pid=pid,
        start_time=time.monotonic(),
    )

    monitor_thread.start()
    logger.info("Monitoring started for PID %d on %s %s",
                pid, system_info["os_name"], system_info["os_version"])

    return handle


def stop_monitoring(handle: MonitorHandle) -> str:
    """Stop monitoring, flush collected data to CSV, and return the file path.

    Args:
        handle: The ``MonitorHandle`` returned by ``start_monitoring``.

    Returns:
        Absolute path to the generated CSV file.
    """
    handle.stop_event.set()
    handle.thread.join(timeout=5.0)

    total_duration = time.monotonic() - handle.start_time
    logger.info(
        "Monitoring stopped after %.2fs (%d samples)",
        total_duration, len(handle.samples),
    )

    csv_path = flush_to_csv(handle, total_duration)
    return csv_path


# =============================================================================
# CSV Output
# =============================================================================

CSV_COLUMNS: list[str] = [
    "timestamp",
    "cpu_percent",
    "memory_mb",
    "memory_percent",
    "thread_count",
    "ctx_switches_voluntary",
    "ctx_switches_involuntary",
    "lock_acquisition_ms",
    "thread_wait_ms",
]


def _generate_csv_filename(os_name: str) -> str:
    """Build a CSV filename that encodes OS name and current timestamp.

    Args:
        os_name: Operating system name (e.g., ``Windows``, ``Darwin``).

    Returns:
        Filename string like ``benchmark_Windows_20260322_171400.csv``.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"benchmark_{os_name}_{ts}.csv"


def _compute_summary(
    samples: list[MetricSample],
    total_duration: float,
) -> dict[str, str]:
    """Compute aggregate statistics from the collected samples.

    Args:
        samples:        List of ``MetricSample`` data points.
        total_duration: Wall-clock duration of the monitoring session (seconds).

    Returns:
        Dictionary of summary key-value pairs.
    """
    if not samples:
        return {
            "average_cpu_percent": "N/A",
            "peak_memory_mb": "N/A",
            "total_duration_seconds": f"{total_duration:.2f}",
            "total_ctx_switches_voluntary": "N/A",
            "total_ctx_switches_involuntary": "N/A",
        }

    avg_cpu = sum(s.cpu_percent for s in samples) / len(samples)
    peak_mem = max(s.memory_mb for s in samples)

    # Context switches are cumulative; take the last sample's values
    last = samples[-1]

    return {
        "average_cpu_percent": f"{avg_cpu:.2f}",
        "peak_memory_mb": f"{peak_mem:.2f}",
        "total_duration_seconds": f"{total_duration:.2f}",
        "total_ctx_switches_voluntary": str(last.ctx_switches_voluntary),
        "total_ctx_switches_involuntary": str(last.ctx_switches_involuntary),
    }


def flush_to_csv(handle: MonitorHandle, total_duration: float) -> str:
    """Write all collected samples and a summary block to a CSV file.

    Args:
        handle:         The ``MonitorHandle`` containing samples and metadata.
        total_duration: Total wall-clock monitoring duration in seconds.

    Returns:
        Absolute path to the written CSV file.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    os_name = handle.system_info.get("os_name", "Unknown")
    filename = _generate_csv_filename(os_name)
    filepath = os.path.join(OUTPUT_DIR, filename)

    summary = _compute_summary(handle.samples, total_duration)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        # -- Header metadata (commented lines) --
        f.write(f"# Benchmark Monitor Results\n")
        f.write(f"# OS: {handle.system_info.get('os_name', 'N/A')}\n")
        f.write(f"# OS Version: {handle.system_info.get('os_version', 'N/A')}\n")
        f.write(f"# Architecture: {handle.system_info.get('architecture', 'N/A')}\n")
        f.write(f"# Monitored PID: {handle.pid}\n")
        f.write(f"# Sampling Interval: {SAMPLING_INTERVAL_SECONDS}s\n")
        f.write(f"# Total Samples: {len(handle.samples)}\n")
        f.write(f"#\n")

        # -- Data rows --
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for sample in handle.samples:
            writer.writerow({
                "timestamp": sample.timestamp,
                "cpu_percent": sample.cpu_percent,
                "memory_mb": sample.memory_mb,
                "memory_percent": sample.memory_percent,
                "thread_count": sample.thread_count,
                "ctx_switches_voluntary": sample.ctx_switches_voluntary,
                "ctx_switches_involuntary": sample.ctx_switches_involuntary,
                "lock_acquisition_ms": sample.lock_acquisition_ms,
                "thread_wait_ms": sample.thread_wait_ms,
            })

        # -- Summary block (commented lines) --
        f.write(f"#\n")
        f.write(f"# === Summary ===\n")
        for key, value in summary.items():
            f.write(f"# {key}: {value}\n")
        f.write(f"# ===============\n")

    logger.info("CSV written to: %s", os.path.abspath(filepath))
    return os.path.abspath(filepath)


# =============================================================================
# Standalone Self-Test
# =============================================================================


def _self_test() -> None:
    """Run a brief self-test monitoring this script's own process."""
    logger.info("=" * 60)
    logger.info("BENCHMARK MONITOR -- SELF-TEST")
    logger.info("=" * 60)

    own_pid = os.getpid()
    logger.info("Monitoring own PID: %d", own_pid)

    handle = start_monitoring(own_pid)

    # Simulate some work so CPU/memory metrics are non-trivial
    test_duration = 3.0
    logger.info("Running self-test for %.1fs ...", test_duration)
    end_time = time.monotonic() + test_duration
    while time.monotonic() < end_time:
        _ = [i ** 2 for i in range(10_000)]
        time.sleep(0.1)

    csv_path = stop_monitoring(handle)
    logger.info("Self-test complete. CSV: %s", csv_path)


if __name__ == "__main__":
    _self_test()
