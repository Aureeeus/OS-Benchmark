# OS Benchmark: Deadlock & Performance Monitor

This project provides a cross-platform (Windows / macOS) suite for simulating operating system deadlocks and monitoring system performance metrics in real-time.

## Components

### 1. Deadlock Simulation (`src/deadlock_simulation.py`)
A scalable demonstration of the **Circular Wait** Coffman condition.
- Uses `threading.Lock` to simulate shared resources.
- Supports any number of threads and locks via configurable constants.
- Includes a watchdog timer to detect deadlock and force-exit cleanly.

### 2. Benchmark Monitor (`src/benchmark_monitor.py`)
A background-thread monitor that captures system metrics using `psutil`.
- Samples CPU usage, RSS Memory, active thread count, and context switches.
- Flushes data to an auto-named CSV file (e.g., `benchmark_Windows_YYYYMMDD_HHMMSS.csv`) upon completion.
- Includes a summary block in the CSV with aggregate statistics (avg CPU, peak memory).

### 3. Orchestrator (`src/main/run_simulation.py`)
The main entry point that ties the simulation and monitor together.
- Launches the deadlock simulation as a subprocess.
- Automatically attaches the monitor to the simulation's PID.
- Streams real-time logs from both the simulation and the monitor.

## Project Structure
```text
OS_Benchmark/
├── src/
│   ├── main/
│   │   ├── __init__.py
│   │   └── run_simulation.py      # Orchestrator
│   ├── __init__.py
│   ├── benchmark_monitor.py       # Metrics Monitor
│   └── deadlock_simulation.py     # Deadlock Logic
├── results/                       # Generated CSV benchmarks
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup & Usage

### Prerequisites
- Python 3.8+
- `pip` (Python package installer)

### Installation

1. **Create a virtual environment**:
   ```bash
   python -m venv venv
   ```

2. **Activate the virtual environment**:
   - **Windows**:
     ```powershell
     .\venv\Scripts\activate
     ```
   - **macOS / Linux**:
     ```bash
     source venv/bin/activate
     ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Simulation
To run the full suite (simulation + monitoring) from the project root:
```bash
# Ensure PYTHONPATH is set so packages are discovered correctly
export PYTHONPATH=.   # macOS/Linux
$env:PYTHONPATH="."   # Windows PowerShell

python src/main/run_simulation.py
```
The results will be saved as a CSV in the `results/` directory.
