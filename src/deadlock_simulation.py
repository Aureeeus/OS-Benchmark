"""
Deadlock Simulation Script
===========================
Demonstrates a classic deadlock scenario using the ``threading`` module.

Deadlock occurs when threads form a **circular wait** — each thread holds
one lock and waits for another lock that is held by a different thread.
This is one of the four Coffman conditions required for deadlock:

    1. Mutual Exclusion
    2. Hold and Wait
    3. No Preemption
    4. Circular Wait

The script is fully cross-platform (Windows 11 / macOS) and uses only the
Python standard library.

Usage:
    python deadlock_simulation.py
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

# =============================================================================
# Configuration
# =============================================================================

NUM_THREADS: int = 2
"""Number of worker threads to spawn.  Each thread acquires locks in a
shifted order so that a circular wait is guaranteed when NUM_THREADS >= 2
and NUM_LOCKS >= 2."""

NUM_LOCKS: int = 2
"""Number of shared ``threading.Lock`` resources.  Must be >= 2 for a
circular-wait deadlock to occur."""

LOCK_DELAY_SECONDS: float = 0.5
"""Artificial delay (in seconds) between consecutive lock acquisitions.
Makes the race condition deterministic and reproducible by giving every
thread enough time to grab its first lock before anyone attempts the next."""

DEADLOCK_TIMEOUT_SECONDS: float = 5.0
"""Duration (in seconds) the watchdog timer waits before declaring that a
deadlock has occurred and forcing a clean exit."""

# =============================================================================
# Logging Setup
# =============================================================================

LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(threadName)-10s | %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> logging.Logger:
    """Configure and return the root logger with a timestamped console handler.

    Returns:
        logging.Logger: The configured root logger instance.
    """
    logger = logging.getLogger("deadlock_sim")
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    logger.addHandler(handler)
    return logger


logger: logging.Logger = configure_logging()

# =============================================================================
# Lock Factory
# =============================================================================


def create_locks(count: int) -> list[threading.Lock]:
    """Create a list of ``threading.Lock`` instances.

    Args:
        count: Number of locks to create.  Must be >= 2.

    Returns:
        A list containing *count* unlocked ``threading.Lock`` objects.

    Raises:
        ValueError: If *count* is less than 2.
    """
    if count < 2:
        raise ValueError(f"At least 2 locks are required for deadlock; got {count}")
    return [threading.Lock() for _ in range(count)]


# =============================================================================
# Thread Task
# =============================================================================


def thread_task(thread_id: int, locks: list[threading.Lock]) -> None:
    """Work executed by each thread — acquires locks in shifted order.

    Thread *n* acquires locks starting at index *n*, wrapping around.
    For example, with 2 locks:

    - Thread 0 acquires Lock-0 then Lock-1
    - Thread 1 acquires Lock-1 then Lock-0

    This opposite ordering guarantees a circular-wait deadlock.

    Args:
        thread_id: Zero-based identifier for this thread.
        locks:     Shared list of lock objects.
    """
    num_locks = len(locks)

    # Build the acquisition order for this thread (shifted by thread_id)
    acquisition_order: list[int] = [
        (thread_id + i) % num_locks for i in range(num_locks)
    ]

    logger.info("Started -- will acquire locks in order: %s", acquisition_order)

    for step, lock_index in enumerate(acquisition_order):
        if step == 0:
            logger.info("Acquiring Lock-%d ...", lock_index)
        else:
            logger.info("Waiting for Lock-%d ...", lock_index)

        locks[lock_index].acquire()
        logger.info("Acquired Lock-%d", lock_index)

        # Delay between acquisitions to let other threads grab their first lock
        if step < num_locks - 1:
            time.sleep(LOCK_DELAY_SECONDS)

    # Release all locks in reverse acquisition order (only reached if no deadlock)
    for lock_index in reversed(acquisition_order):
        locks[lock_index].release()
        logger.info("Released Lock-%d", lock_index)


# =============================================================================
# Watchdog -- Deadlock Detection
# =============================================================================


def watchdog_callback(workers: list[threading.Thread]) -> None:
    """Callback fired by ``threading.Timer`` after the timeout elapses.

    If any worker thread is still alive, a deadlock is declared and the
    process is terminated cleanly with ``os._exit(1)``.

    Args:
        workers: List of worker ``threading.Thread`` instances to inspect.
    """
    alive_threads = [t for t in workers if t.is_alive()]

    if not alive_threads:
        return  # All threads finished -- no deadlock

    logger.critical("=" * 60)
    logger.critical("DEADLOCK DETECTED after %.1fs timeout!", DEADLOCK_TIMEOUT_SECONDS)
    logger.critical("=" * 60)
    logger.critical("")
    logger.critical("Blocked threads (%d):", len(alive_threads))

    for t in alive_threads:
        logger.critical("  - %s", t.name)

    logger.critical("")
    logger.critical(
        "Each thread holds one lock and waits for the next -- "
        "classic circular wait."
    )
    logger.critical("")
    logger.critical(
        "Tip: To prevent deadlock, always acquire locks in the "
        "same global order."
    )
    logger.critical("=" * 60)

    # os._exit() is necessary because the deadlocked threads are permanently
    # blocked on Lock.acquire() and cannot be interrupted or joined.
    os._exit(1)


def start_watchdog(workers: list[threading.Thread]) -> threading.Timer:
    """Start a watchdog timer that will fire the deadlock-detection callback.

    The timer is created as a daemon so it won't prevent interpreter shutdown
    if the main thread exits first.

    Args:
        workers: Worker threads to monitor.

    Returns:
        The started ``threading.Timer`` instance (can be cancelled if no
        deadlock occurs).
    """
    timer = threading.Timer(DEADLOCK_TIMEOUT_SECONDS, watchdog_callback, args=[workers])
    timer.daemon = True
    timer.name = "Watchdog"
    timer.start()
    logger.info("Watchdog started -- will timeout in %.1fs", DEADLOCK_TIMEOUT_SECONDS)
    return timer


# =============================================================================
# Banner
# =============================================================================


def print_banner() -> None:
    """Log an informational banner about the simulation parameters."""
    logger.info("=" * 60)
    logger.info("DEADLOCK SIMULATION")
    logger.info("=" * 60)
    logger.info("Threads:  %d", NUM_THREADS)
    logger.info("Locks:    %d", NUM_LOCKS)
    logger.info("Delay:    %.2fs between acquisitions", LOCK_DELAY_SECONDS)
    logger.info("Timeout:  %.1fs before declaring deadlock", DEADLOCK_TIMEOUT_SECONDS)
    logger.info("-" * 60)
    logger.info("Coffman Conditions for Deadlock:")
    logger.info("  1. Mutual Exclusion  -- each lock held by one thread")
    logger.info("  2. Hold and Wait     -- threads hold one lock, wait for another")
    logger.info("  3. No Preemption     -- locks cannot be forcibly taken")
    logger.info("  4. Circular Wait     -- threads acquire locks in opposite order")
    logger.info("-" * 60)


# =============================================================================
# Main Orchestrator
# =============================================================================


def main() -> None:
    """Entry point — orchestrates lock creation, thread spawning, and watchdog."""
    print_banner()

    locks = create_locks(NUM_LOCKS)
    logger.info("Created %d locks", len(locks))

    # Spawn worker threads as daemons so os._exit() can clean up
    workers: list[threading.Thread] = []
    for i in range(NUM_THREADS):
        t = threading.Thread(
            target=thread_task,
            args=(i, locks),
            name=f"Thread-{i}",
            daemon=True,
        )
        workers.append(t)

    logger.info("Spawning %d worker threads ...", NUM_THREADS)
    for t in workers:
        t.start()
        logger.info("  > %s started", t.name)

    # Start watchdog timer for deadlock detection
    watchdog = start_watchdog(workers)

    # Wait for threads to finish (deadlock will cause them to hang)
    for t in workers:
        t.join(timeout=DEADLOCK_TIMEOUT_SECONDS + 1.0)

    # If all threads completed, cancel the watchdog and report success
    if all(not t.is_alive() for t in workers):
        watchdog.cancel()
        logger.info("All threads completed -- no deadlock occurred.")


if __name__ == "__main__":
    main()
