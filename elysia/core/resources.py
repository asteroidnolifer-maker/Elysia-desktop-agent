"""Resource awareness: how many local workers can run on this machine, and how
many logical tasks may be active given RAM/CPU budget.

Key principle: logical agents != OS processes != provider sessions. On a 16 GB
laptop, "50 logical tasks" means 50 queued tasks, not 50 llama-server
processes. A small local pool (bounded by RAM/CPU) executes them.
"""
from __future__ import annotations

import os


def available_memory_mb() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    total = 0
    try:
        total = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except (ValueError, OSError, AttributeError):
        pass
    return total


def cpu_count() -> int:
    try:
        return os.cpu_count() or 1
    except (ValueError, OSError, AttributeError):
        return 1


def local_worker_budget(reserve_mb: int = 1536, worker_mb: int = 600,
                        cpu_per_worker: float = 1.0, max_cpu_fraction: float = 0.8) -> int:
    """How many local workers can run right now. Never returns less than 0.

    Based jointly on free RAM and free CPU headroom.
    """
    mem = available_memory_mb()
    max_by_mem = max(0, (mem - reserve_mb) // worker_mb) if mem > 0 else 1
    cpus = cpu_count()
    max_by_cpu = max(1, int(cpus * max_cpu_fraction / max(cpu_per_worker, 0.25)))
    if mem <= 0:
        return max_by_cpu
    return max(1, min(max_by_mem, max_by_cpu))


def can_spawn(active: int, budget: int) -> bool:
    return active < budget