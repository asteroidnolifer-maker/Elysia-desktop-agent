"""Resource awareness: RAM / CPU / disk / GPU, adaptive local worker concurrency,
and a provider capacity model.

Core principle: 100 logical tasks != 100 model processes. A bounded local pool
(by RAM + CPU) executes queued tasks; remote providers consume no local model
RAM. When the machine is memory-constrained we shrink concurrency; when more
resources free up, we grow it.
"""
from __future__ import annotations

import os
import threading


class ResourceManager:
    """Tracks and reports live system resources, and the provider capacity
    model (which providers/models may run concurrently)."""

    def __init__(self, reserve_mb: int = 1536, worker_est_mb: int = 600,
                 max_local_workers: int = 4, max_cpu_fraction: float = 0.8):
        self.reserve_mb = reserve_mb
        self.worker_est_mb = worker_est_mb
        self.max_local_workers = max_local_workers
        self.max_cpu_fraction = max_cpu_fraction
        self._active_workers = 0
        self._mu = threading.Lock()
        # provider capacity model: name -> {model, current_concurrency}
        self._provider_load: dict[str, int] = {}

    @classmethod
    def from_config(cls, cfg=None) -> "ResourceManager":
        """Build from a Config (or a ResourcesConfig) — one place that knows how
        config maps onto the resource model, so callers never pass the config
        object where an int is expected."""
        rc = getattr(cfg, "resources", cfg)
        if rc is None:
            return cls()
        return cls(reserve_mb=int(getattr(rc, "reserve_mb", 1536)),
                   worker_est_mb=int(getattr(rc, "worker_est_mb", 600)),
                   max_local_workers=int(getattr(rc, "max_local_workers", 4)),
                   max_cpu_fraction=float(getattr(rc, "max_cpu_fraction", 0.8)))

    # -- raw metrics ---------------------------------------------------------
    @staticmethod
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

    @staticmethod
    def total_memory_mb() -> int:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) // 1024
        except OSError:
            pass
        return 0

    @staticmethod
    def cpu_count() -> int:
        try:
            return os.cpu_count() or 1
        except (ValueError, OSError, AttributeError):
            return 1

    @staticmethod
    def load_avg() -> float:
        try:
            with open("/proc/loadavg") as f:
                return float(f.read().split()[0])
        except (OSError, IndexError, ValueError):
            return 0.0

    @staticmethod
    def disk_free_mb(path: str = "/") -> int:
        try:
            st = os.statvfs(path)
            return (st.f_bavail * st.f_frsize) // (1024 * 1024)
        except OSError:
            return -1

    @staticmethod
    def gpu_available() -> bool:
        for tool in ("nvidia-smi", "rocm-smi"):
            import shutil
            if shutil.which(tool):
                return True
        return False

    # -- derived -------------------------------------------------------------
    def memory_pressure(self) -> bool:
        mem = self.available_memory_mb()
        if mem <= 0:
            return False
        return mem < self.reserve_mb

    def local_worker_budget(self) -> int:
        """How many local model workers can run right now."""
        mem = self.available_memory_mb()
        cpus = self.cpu_count()
        load = self.load_avg()
        max_by_cpu = max(1, int(cpus * self.max_cpu_fraction - load))
        if mem <= 0:
            budget = max_by_cpu
        else:
            max_by_mem = max(0, (mem - self.reserve_mb) // max(1, self.worker_est_mb))
            budget = max(1, min(max_by_mem, max_by_cpu))
        return min(budget, self.max_local_workers)

    def can_spawn(self) -> bool:
        with self._mu:
            return self._active_workers < self.local_worker_budget()

    def spawn(self) -> bool:
        """Reserve a local worker slot. True if a slot was free."""
        with self._mu:
            if self._active_workers >= self.local_worker_budget():
                return False
            self._active_workers += 1
            return True

    def release(self) -> None:
        with self._mu:
            if self._active_workers > 0:
                self._active_workers -= 1

    # -- provider capacity model --------------------------------------------
    def set_provider_load(self, name: str, count: int) -> None:
        with self._mu:
            self._provider_load[name] = count

    def provider_load(self) -> dict:
        with self._mu:
            return dict(self._provider_load)

    def report(self) -> dict:
        mem = self.available_memory_mb()
        total = self.total_memory_mb()
        return {
            "memory_mb_available": mem,
            "memory_mb_total": total,
            "memory_utilization": round((1 - mem / total) * 100, 1) if total else -1,
            "cpu_count": self.cpu_count(),
            "load_avg": self.load_avg(),
            "disk_free_mb": self.disk_free_mb(),
            "gpu_available": self.gpu_available(),
            "active_workers": self._active_workers,
            "local_worker_budget": self.local_worker_budget(),
            "memory_pressure": self.memory_pressure(),
            "provider_load": self.provider_load(),
        }


# Backward-compatible module-level helpers
def available_memory_mb() -> int:
    return ResourceManager.available_memory_mb()


def cpu_count() -> int:
    return ResourceManager.cpu_count()


def local_worker_budget(reserve_mb: int = 1536, worker_mb: int = 600,
                        cpu_per_worker: float = 1.0,
                        max_cpu_fraction: float = 0.8) -> int:
    rm = ResourceManager(reserve_mb=reserve_mb, worker_est_mb=worker_mb,
                         max_cpu_fraction=max_cpu_fraction)
    return max(1, rm.local_worker_budget())


def can_spawn(active: int, budget: int) -> bool:
    return active < budget
