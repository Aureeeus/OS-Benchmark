"""
Run Simulation (Orchestrator)
==============================
Launches the deadlock simulation as a subprocess and attaches the benchmark
monitor to its PID, so system metrics are captured for the entire lifetime
of the simulation.

Cross-platform: works on Windows 11 and macOS without modification.

Usage::

    python run_simulation.py
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

import src.benchmark_monitor as bm

# =============================================================================
# Configuration
# =============================================================================

SIMULATION_SCRIPT: str = "../deadlock_simulation.py"
"""Filename of the deadlock simulation script to run."""

# =============================================================================
# Logging Setup
# =============================================================================

LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(threadName)-10s | %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> logging.Logger:
    """Configure and return the orchestrator logger.

    Returns:
        The configured logger instance.
    """
    logger = logging.getLogger("run_simulation")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        logger.addHandler(handler)

    return logger


logger: logging.Logger = configure_logging()

# =============================================================================
# Subprocess Management
# =============================================================================


def launch_simulation() -> subprocess.Popen:
    """Spawn the deadlock simulation as a child process.

    Returns:
        The ``Popen`` handle for the running simulation process.

    Raises:
        FileNotFoundError: If the simulation script does not exist.
    """
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), SIMULATION_SCRIPT)

    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"Simulation script not found: {script_path}")

    logger.info("Launching simulation: %s", script_path)

    process = subprocess.Popen(
        [sys.executable, script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    logger.info("Simulation started (PID: %d)", process.pid)
    return process


# =============================================================================
# Simulation Output
# =============================================================================


def stream_simulation_output(process: subprocess.Popen) -> int:
    """Read and log stdout from the simulation process until it exits.

    Args:
        process: The ``Popen`` handle for the simulation.

    Returns:
        The exit code of the simulation process.
    """
    if process.stdout:
        for line in process.stdout:
            stripped = line.rstrip("\n\r")
            if stripped:
                logger.info("[SIM] %s", stripped)

    return process.wait()


# =============================================================================
# Orchestrator
# =============================================================================


def run() -> None:
    """Orchestrate the deadlock simulation with benchmark monitoring.

    Steps:
        1. Launch ``deadlock_simulation.py`` as a subprocess.
        2. Attach the benchmark monitor to the simulation's PID.
        3. Stream simulation output to the console.
        4. Stop the monitor and flush metrics to CSV on completion.
    """
    logger.info("=" * 60)
    logger.info("RUN SIMULATION -- ORCHESTRATOR")
    logger.info("=" * 60)

    # Step 1: Launch the simulation subprocess
    sim_process = launch_simulation()

    # Brief delay so the subprocess has time to initialize
    time.sleep(0.3)

    # Step 2: Attach the benchmark monitor to the simulation PID
    logger.info("Attaching benchmark monitor to PID %d ...", sim_process.pid)
    try:
        monitor_handle = bm.start_monitoring(pid=sim_process.pid)
    except Exception:
        logger.error("Failed to attach monitor -- simulation PID may have exited early")
        sim_process.wait()
        return

    # Step 3: Stream simulation output until it exits
    exit_code = stream_simulation_output(sim_process)
    logger.info("Simulation exited with code %d", exit_code)

    # Step 4: Stop monitoring and flush CSV
    csv_path = bm.stop_monitoring(monitor_handle)

    logger.info("-" * 60)
    logger.info("Benchmark CSV: %s", csv_path)
    logger.info("=" * 60)
    logger.info("Done.")


if __name__ == "__main__":
    run()
