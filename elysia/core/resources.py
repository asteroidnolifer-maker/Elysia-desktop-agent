"""Resource-aware execution: classes, live monitoring, adaptive policy,
reservation ledger and per-task resource estimation.

The central rule for the whole system:

    LOGICAL AGENT != MODEL PROCESS != OS PROCESS != PROVIDER REQUEST

Dozens or hundreds of logical agents are cheap in-process roles. The expensive
things are model inference, builds and heavy CPU work. On the target machine
(Intel i5-6300U, 2 cores / 4 threads, 16 GB, no useful GPU) only a very small
number of expensive operations may run at once, so they are serialized through
a reservation ledger while logical agents keep flowing.

This module is the single source of truth for:

  - ``ResourceClass``     the cost class of a unit of work
  - ``TaskPriority``      CRITICAL / INTERACTIVE / NORMAL / BACKGROUND / IDLE
  - ``ResourceMonitor``   live CPU, per-process CPU, load, RAM, swap, disk,
                          temperature, active inference/builds, model memory
  - ``ResourcePolicy``    configurable thresholds -> admit / defer decision
  - ``ResourceLedger``    reservations for expensive classes (one heavy slot)
  - ``estimate_resource_class`` / ``task_resource_needs``

It never fabricates a metric: anything the platform cannot read is reported as
``None``/``-1`` and treated as "unknown", never as healthy.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Resource classes
# ---------------------------------------------------------------------------
LIGHT = "light"
IO = "io"
NETWORK = "network"
CPU = "cpu"
CPU_HEAVY = "cpu_heavy"
MEMORY_HEAVY = "memory_heavy"
LOCAL_LLM = "local_llm"
REMOTE_LLM = "remote_llm"
BUILD = "build"

ALL_CLASSES = (LIGHT, IO, NETWORK, CPU, CPU_HEAVY, MEMORY_HEAVY, LOCAL_LLM,
               REMOTE_LLM, BUILD)

#: A provider request to a model running on THIS machine competes with local
#: builds and heavy CPU work for the same scarce cores.
HEAVY_CLASSES = frozenset({CPU_HEAVY, MEMORY_HEAVY, LOCAL_LLM, BUILD})

#: Classes cheap enough to run alongside heavy work.
LIGHTWEIGHT_CLASSES = frozenset({LIGHT, IO, NETWORK, REMOTE_LLM, CPU})

# ---------------------------------------------------------------------------
# Priorities
# ---------------------------------------------------------------------------
CRITICAL = "critical"
INTERACTIVE = "interactive"
NORMAL = "normal"
BACKGROUND = "background"
IDLE = "idle"

#: Lower rank = scheduled first. Interactive user work beats background
#: self-improvement by construction.
_PRIORITY_RANK = {CRITICAL: 0, INTERACTIVE: 1, NORMAL: 2, BACKGROUND: 3,
                  IDLE: 4}


def priority_rank(name: str | None) -> int:
    return _PRIORITY_RANK.get((name or NORMAL).lower(), _PRIORITY_RANK[NORMAL])


def priority_name(rank: int) -> str:
    for k, v in _PRIORITY_RANK.items():
        if v == rank:
            return k
    return NORMAL


# ---------------------------------------------------------------------------
# Live monitoring
# ---------------------------------------------------------------------------
@dataclass
class MonitorSnapshot:
    """One consistent read of machine state. Unknown values are None/-1."""
    cpu_pct: float | None = None
    load_avg: float | None = None
    cpu_count: int = 1
    mem_available_mb: int = -1
    mem_total_mb: int = -1
    swap_used_mb: int = -1
    swap_total_mb: int = -1
    disk_free_mb: int = -1
    temperature_c: float | None = None
    active_local_inference: int = 0
    active_builds: int = 0
    heavy_in_use: int = 0
    model_memory_mb: int | None = None
    per_process: list = field(default_factory=list)
    sampled_at: float = 0.0

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["heavy_in_use"] = self.heavy_in_use
        return d


def _read_meminfo() -> dict:
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        out[parts[0].strip()] = int(parts[1].split()[0])
                    except (ValueError, IndexError):
                        continue
    except OSError:
        pass
    return out


def _read_cpu_jiffies() -> tuple[int, int] | None:
    """(total, idle) jiffies from /proc/stat, or None when unavailable."""
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        values = [int(v) for v in parts[1:11]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle
    except (OSError, ValueError, IndexError):
        return None


def _read_temperature() -> float | None:
    """Max readable thermal zone in Celsius, or None (never guessed)."""
    base = "/sys/class/thermal"
    try:
        zones = [z for z in os.listdir(base) if z.startswith("thermal_zone")]
    except OSError:
        return None
    hottest = None
    for z in sorted(zones):
        p = os.path.join(base, z, "temp")
        try:
            with open(p) as f:
                milli = int(f.read().strip())
        except (OSError, ValueError):
            continue
        c = milli / 1000.0
        if hottest is None or c > hottest:
            hottest = c
    return hottest


def _proc_cpu_map() -> dict[int, int]:
    """pid -> total CPU jiffies, for per-process CPU accounting."""
    out: dict[int, int] = {}
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat", "rb") as f:
                data = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        # comm may contain spaces/parens: parse after the LAST ')'
        r = data.rfind(")")
        if r < 0:
            continue
        try:
            fields = data[r + 2:].split()
            utime, stime = int(fields[11]), int(fields[12])
        except (ValueError, IndexError):
            continue
        out[int(pid)] = utime + stime
    return out


class ResourceMonitor:
    """Samples live machine state. Cheap, cached, never raises.

    ``hpp``/``interval`` are tunable; tests inject a fixed snapshot through
    :meth:`set_snapshot` so scheduling decisions are deterministic.
    """

    def __init__(self, sample_interval_s: float = 1.0,
                 cpu_sample_window_s: float = 0.05, top_processes: int = 5,
                 proc_cpu_enabled: bool = True):
        self.sample_interval_s = sample_interval_s
        self.cpu_sample_window_s = cpu_sample_window_s
        self.top_processes = top_processes
        self.proc_cpu_enabled = proc_cpu_enabled
        self._lock = threading.Lock()
        self._snapshot: MonitorSnapshot | None = None
        self._snapshot_at = 0.0
        self._prev_cpu: tuple[int, int] | None = None
        self._prev_proc: dict[int, int] = {}
        self._prev_proc_at = 0.0
        self._injected: MonitorSnapshot | None = None
        # counters owned by the ledger/pool, read back into snapshots
        self._counters = {"local_inference": 0, "builds": 0, "heavy": 0}

    # -- injection (tests / offline simulation) -------------------------------
    def set_snapshot(self, snapshot: MonitorSnapshot | None) -> None:
        with self._lock:
            self._injected = snapshot

    def note_counters(self, local_inference: int = 0, builds: int = 0,
                      heavy: int = 0) -> None:
        with self._lock:
            self._counters = {"local_inference": local_inference,
                              "builds": builds, "heavy": heavy}

    # -- sampling -------------------------------------------------------------
    def _cpu_pct(self) -> float | None:
        first = _read_cpu_jiffies()
        if first is None:
            return None
        if self.cpu_sample_window_s > 0:
            time.sleep(self.cpu_sample_window_s)
        second = _read_cpu_jiffies()
        if second is None:
            return None
        dt, di = second[0] - first[0], second[1] - first[1]
        if dt <= 0:
            return None
        return round(max(0.0, min(100.0, (1 - di / dt) * 100)), 1)

    def _per_process(self) -> list:
        if not self.proc_cpu_enabled:
            return []
        now = time.time()
        cur = _proc_cpu_map()
        prev, prev_at = self._prev_proc, self._prev_proc_at
        self._prev_proc, self._prev_proc_at = cur, now
        if not prev or now <= prev_at:
            return []
        dt = now - prev_at
        if dt <= 0:
            return []
        hz = 100.0
        rows = []
        for pid, jiffies in cur.items():
            delta = jiffies - prev.get(pid, jiffies)
            if delta <= 0:
                continue
            pct = (delta / hz) / dt * 100.0
            try:
                with open(f"/proc/{pid}/comm") as f:
                    comm = f.read().strip()
            except OSError:
                comm = f"pid {pid}"
            rows.append({"pid": pid, "name": comm, "cpu_pct": round(pct, 1)})
        rows.sort(key=lambda r: r["cpu_pct"], reverse=True)
        return rows[:self.top_processes]

    def snapshot(self, force: bool = False) -> MonitorSnapshot:
        with self._lock:
            if self._injected is not None:
                return self._injected
            if (not force and self._snapshot is not None
                    and time.time() - self._snapshot_at < self.sample_interval_s):
                return self._snapshot
        info = _read_meminfo()
        mem_avail = info.get("MemAvailable", -1) // 1024 if info else -1
        mem_total = info.get("MemTotal", -1) // 1024 if info else -1
        swap_total = info.get("SwapTotal", 0) // 1024 if info else -1
        swap_free = info.get("SwapFree", 0) // 1024 if info else -1
        swap_used = (swap_total - swap_free) if swap_total > 0 else 0
        try:
            load = os.getloadavg()[0]
        except (OSError, AttributeError):
            load = None
        with self._lock:
            counters = dict(self._counters)
        snap = MonitorSnapshot(
            cpu_pct=self._cpu_pct(),
            load_avg=load,
            cpu_count=ResourceManager.cpu_count(),
            mem_available_mb=mem_avail,
            mem_total_mb=mem_total,
            swap_used_mb=max(0, swap_used),
            swap_total_mb=max(0, swap_total),
            disk_free_mb=ResourceManager.disk_free_mb(),
            temperature_c=_read_temperature(),
            active_local_inference=counters["local_inference"],
            active_builds=counters["builds"],
            heavy_in_use=counters["heavy"],
            model_memory_mb=self._model_memory_mb(),
            per_process=self._per_process(),
            sampled_at=time.time(),
        )
        with self._lock:
            self._snapshot, self._snapshot_at = snap, time.time()
            self._injected = None
        return snap

    def _model_memory_mb(self) -> int | None:
        """RSS of a local inference process, when one is identifiable.

        Scans /proc cmdlines for a model/llama/ollama process. Returns None
        rather than a made-up number when nothing identifiable is running.
        """
        needles = ("llama-server", "llama.cpp", "ollama", "llamafile",
                   "model.gguf", ".gguf")
        total = 0
        found = False
        try:
            pids = [p for p in os.listdir("/proc") if p.isdigit()]
        except OSError:
            return None
        for pid in pids:
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read().decode("utf-8", "replace").replace("\0", " ")
            except OSError:
                continue
            low = cmd.lower()
            if not any(n in low for n in needles):
                continue
            try:
                with open(f"/proc/{pid}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            total += int(line.split()[1]) // 1024
                            found = True
                            break
            except (OSError, ValueError, IndexError):
                continue
        return total if found else None


# ---------------------------------------------------------------------------
# Adaptive policy
# ---------------------------------------------------------------------------
@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    throttle: str = "normal"   # normal | cautious | defer | critical

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason,
                "throttle": self.throttle}


class ResourcePolicy:
    """Turns live metrics into an admit/defer decision per resource class.

    Thresholds are configurable (``resources.*``); the defaults implement the
    documented ladder for a 2-core/16 GB laptop.
    """

    def __init__(self, cpu_busy_pct: float = 50.0, cpu_high_pct: float = 75.0,
                 cpu_critical_pct: float = 90.0, ram_min_free_mb: int = 2048,
                 ram_block_infer_mb: int = 1024, swap_max_used_mb: int = 1024,
                 temp_max_c: float | None = 90.0, heavy_exclusive: bool = True,
                 allow_remote_under_pressure: bool = True):
        self.cpu_busy_pct = cpu_busy_pct
        self.cpu_high_pct = cpu_high_pct
        self.cpu_critical_pct = cpu_critical_pct
        self.ram_min_free_mb = ram_min_free_mb
        self.ram_block_infer_mb = ram_block_infer_mb
        self.swap_max_used_mb = swap_max_used_mb
        self.temp_max_c = temp_max_c
        self.heavy_exclusive = heavy_exclusive
        self.allow_remote_under_pressure = allow_remote_under_pressure

    @classmethod
    def from_config(cls, cfg=None) -> "ResourcePolicy":
        rc = getattr(cfg, "resources", cfg) or None
        if rc is None:
            return cls()
        def g(name, default):
            return getattr(rc, name, default)
        return cls(
            cpu_busy_pct=float(g("cpu_busy_pct", 50.0)),
            cpu_high_pct=float(g("cpu_high_pct", 75.0)),
            cpu_critical_pct=float(g("cpu_critical_pct", 90.0)),
            ram_min_free_mb=int(g("ram_min_free_mb", 2048)),
            ram_block_infer_mb=int(g("ram_block_infer_mb", 1024)),
            swap_max_used_mb=int(g("swap_max_used_mb", 1024)),
            temp_max_c=(None if g("temp_max_c", 90.0) in (None, 0)
                        else float(g("temp_max_c", 90.0))),
            heavy_exclusive=bool(g("heavy_exclusive", True)),
            allow_remote_under_pressure=bool(
                g("allow_remote_under_pressure", True)),
        )

    # -- decisions -----------------------------------------------------------
    def decide(self, resource_class: str, snap: MonitorSnapshot,
               priority: str = NORMAL) -> Decision:
        cpu = snap.cpu_pct
        ram = snap.mem_available_mb
        swap = snap.swap_used_mb
        temp = snap.temperature_c
        heavy = resource_class in HEAVY_CLASSES
        background = priority_rank(priority) >= _PRIORITY_RANK[BACKGROUND]

        # -- temperature: the last safety net on fanless laptops -------------
        if temp is not None and self.temp_max_c is not None \
                and temp >= self.temp_max_c and heavy:
            return Decision(False, f"thermal limit {temp:.0f}C "
                                   f">= {self.temp_max_c:.0f}C", "defer")

        # -- RAM ladder ------------------------------------------------------
        if ram and ram >= 0:
            if ram < self.ram_block_infer_mb and resource_class in (
                    LOCAL_LLM, MEMORY_HEAVY):
                return Decision(False, f"free RAM {ram} MB "
                                       f"< {self.ram_block_infer_mb} MB — "
                                       "local inference blocked "
                                       "(memory recovery pending)", "critical")
            if ram < self.ram_min_free_mb and resource_class in (
                    LOCAL_LLM, MEMORY_HEAVY, CPU_HEAVY, BUILD):
                return Decision(False, f"free RAM {ram} MB "
                                       f"< {self.ram_min_free_mb} MB — "
                                       "not loading another model / heavy job",
                                "defer")

        # -- swap pressure ---------------------------------------------------
        if swap and swap > self.swap_max_used_mb and resource_class in (
                MEMORY_HEAVY, LOCAL_LLM):
            return Decision(False, f"swap in use {swap} MB "
                                   f"> {self.swap_max_used_mb} MB", "defer")

        # -- CPU ladder ------------------------------------------------------
        if cpu is not None:
            if cpu >= self.cpu_critical_pct:
                if resource_class in LIGHTWEIGHT_CLASSES:
                    return Decision(True, f"CPU {cpu:.0f}% — only lightweight/"
                                           "network/remote work may start",
                                    "critical")
                return Decision(False, f"CPU pressure {cpu:.0f}% "
                                       f">= {self.cpu_critical_pct:.0f}% — "
                                       "heavy work deferred", "critical")
            if cpu >= self.cpu_high_pct and (heavy or background):
                who = "background " if background else ""
                return Decision(False, f"CPU pressure {cpu:.0f}% "
                                       f">= {self.cpu_high_pct:.0f}% — "
                                       f"{who}heavy work deferred", "defer")
            if cpu >= self.cpu_busy_pct and resource_class in (CPU_HEAVY, BUILD):
                return Decision(False, f"CPU busy {cpu:.0f}% "
                                       f">= {self.cpu_busy_pct:.0f}% — "
                                       "avoid launching more CPU-heavy jobs",
                                "cautious")

        # -- heavy exclusivity ----------------------------------------------
        if self.heavy_exclusive and heavy and snap.heavy_in_use > 0:
            return Decision(False, "one heavy job at a time (local model / "
                                   "build / heavy CPU already running)",
                            "normal")
        return Decision(True, "", "normal")

    def limits(self) -> dict:
        return {"cpu_busy_pct": self.cpu_busy_pct,
                "cpu_high_pct": self.cpu_high_pct,
                "cpu_critical_pct": self.cpu_critical_pct,
                "ram_min_free_mb": self.ram_min_free_mb,
                "ram_block_infer_mb": self.ram_block_infer_mb,
                "swap_max_used_mb": self.swap_max_used_mb,
                "temp_max_c": self.temp_max_c,
                "heavy_exclusive": self.heavy_exclusive}


# ---------------------------------------------------------------------------
# Reservation ledger
# ---------------------------------------------------------------------------
@dataclass
class Reservation:
    id: int
    resource_class: str
    owner: str
    priority: str
    note: str = ""
    created_at: float = 0.0

    def as_dict(self) -> dict:
        return {"id": self.id, "resource_class": self.resource_class,
                "owner": self.owner, "priority": self.priority,
                "note": self.note, "age_s": round(time.time() - self.created_at, 1)}


class ResourceLedger:
    """Slots for expensive work, so nothing starts without capacity.

    Heavy classes (local model, build, heavy CPU, memory-heavy) share ONE
    exclusive slot by default — this is what makes "do not run a local 7B model
    and a large build simultaneously on a 2-core CPU" true. Cheap classes have
    their own caps and run alongside.
    """

    def __init__(self, heavy_slots: int = 1, local_llm_slots: int = 1,
                 remote_slots: int = 8, cpu_slots: int | None = None,
                 io_slots: int = 4, network_slots: int = 8,
                 monitor: ResourceMonitor | None = None,
                 policy: ResourcePolicy | None = None):
        self.limits = {
            LIGHT: 10 ** 6,
            IO: max(1, int(io_slots)),
            NETWORK: max(1, int(network_slots)),
            CPU: max(1, int(cpu_slots if cpu_slots else (os.cpu_count() or 1))),
            CPU_HEAVY: max(1, int(heavy_slots)),
            MEMORY_HEAVY: max(1, int(heavy_slots)),
            LOCAL_LLM: min(max(1, int(heavy_slots)), max(1, int(local_llm_slots))),
            BUILD: max(1, int(heavy_slots)),
            REMOTE_LLM: max(1, int(remote_slots)),
        }
        self.monitor = monitor
        self.policy = policy
        self._held: dict[int, Reservation] = {}
        self._next_id = 1
        # re-entrant: reserve() updates the monitor's counters from inside the
        # critical section, and a plain Lock deadlocks there.
        self._mu = threading.RLock()
        self._waits: dict[str, str] = {}   # owner -> reason it is waiting

    @classmethod
    def from_config(cls, cfg=None, monitor=None, policy=None) -> "ResourceLedger":
        rc = getattr(cfg, "resources", cfg) or None

        def g(name, default):
            return getattr(rc, name, default) if rc is not None else default
        return cls(heavy_slots=int(g("heavy_slots", 1)),
                   local_llm_slots=int(g("local_llm_concurrency", 1)),
                   remote_slots=int(g("remote_slots", 8)),
                   io_slots=int(g("io_slots", 4)),
                   network_slots=int(g("network_slots", 8)),
                   monitor=monitor, policy=policy)

    # -- accounting ----------------------------------------------------------
    def _heavy_in_use(self) -> int:
        return sum(1 for r in self._held.values()
                   if r.resource_class in HEAVY_CLASSES)

    def counts(self) -> dict:
        with self._mu:
            held = list(self._held.values())
        out = {c: 0 for c in ALL_CLASSES}
        for r in held:
            out[r.resource_class] = out.get(r.resource_class, 0) + 1
        out["heavy"] = sum(1 for r in held
                           if r.resource_class in HEAVY_CLASSES)
        return out

    def in_use(self, resource_class: str) -> int:
        with self._mu:
            return sum(1 for r in self._held.values()
                       if r.resource_class == resource_class)

    def held(self) -> list:
        with self._mu:
            return [r.as_dict() for r in self._held.values()]

    def waiting(self) -> dict:
        with self._mu:
            return dict(self._waits)

    def snap_counters(self, held: list | None = None) -> None:
        """Push live counters into the monitor so policies see them.

        ``held`` may be supplied by a caller that already owns the lock (and
        must then NOT take it again).
        """
        if self.monitor is None:
            return
        if held is None:
            with self._mu:
                held = list(self._held.values())
        self.monitor.note_counters(
            local_inference=sum(1 for r in held
                                if r.resource_class == LOCAL_LLM),
            builds=sum(1 for r in held if r.resource_class == BUILD),
            heavy=sum(1 for r in held if r.resource_class in HEAVY_CLASSES))

    # -- reserve / release ---------------------------------------------------
    def reserve(self, resource_class: str, owner: str,
                priority: str = NORMAL, note: str = "",
                check_policy: bool = True) -> Reservation | None:
        """Try to reserve one slot for ``resource_class``.

        Returns a :class:`Reservation` (call ``release`` when done) or None.
        ``check_policy=False`` skips the live CPU/RAM ladder (used when the
        caller has already consulted it, e.g. the scheduler).
        """
        reason = None
        if check_policy and self.policy is not None and self.monitor is not None:
            snap = self.monitor.snapshot()
            dec = self.policy.decide(resource_class, snap, priority)
            if not dec.allowed:
                reason = dec.reason
        with self._mu:
            if reason is None:
                if len(self._held) >= 0:
                    used = sum(1 for r in self._held.values()
                               if r.resource_class == resource_class)
                    cap = self.limits.get(resource_class, 1)
                    if used >= cap:
                        if resource_class in HEAVY_CLASSES:
                            occupant = next(
                                (r for r in self._held.values()
                                 if r.resource_class in HEAVY_CLASSES), None)
                            reason = (f"heavy slot occupied by "
                                      f"{occupant.owner}" if occupant
                                      else "no free slot")
                        else:
                            reason = (f"{resource_class} slots "
                                      f"{used}/{cap} in use")
            if reason is None:
                rid = self._next_id
                self._next_id += 1
                res = Reservation(id=rid, resource_class=resource_class,
                                  owner=owner, priority=priority,
                                  note=note, created_at=time.time())
                self._held[rid] = res
                self._waits.pop(owner, None)
                self._after_change(list(self._held.values()))
                return res
            self._waits[owner] = reason
        self._after_change()
        return None

    def release(self, reservation: Reservation | None) -> None:
        if reservation is None:
            return
        with self._mu:
            self._held.pop(reservation.id, None)
        self._after_change()

    def release_owner(self, owner: str) -> int:
        """Release every slot held by an owner (crash cleanup)."""
        with self._mu:
            ids = [r.id for r in self._held.values() if r.owner == owner]
            for i in ids:
                self._held.pop(i, None)
        self._after_change()
        return len(ids)

    def _after_change(self, held: list | None = None) -> None:
        self.snap_counters(held)

    def status(self) -> dict:
        with self._mu:
            held = list(self._held.values())
            waits = dict(self._waits)
        return {"limits": dict(self.limits), "held": [r.as_dict() for r in held],
                "waiting": waits, "counts": self.counts()}


# ---------------------------------------------------------------------------
# Per-task estimation
# ---------------------------------------------------------------------------
_MODEL_ROLES = {"planner", "architect", "implementer", "tester", "debugger",
                "code_reviewer", "security_reviewer", "documentation_agent",
                "research_agent", "integration_agent", "release_agent"}

_BUILD_HINTS = ("build", "compile", "test", "bundle", "package", "gradle",
                "cargo", "gofmt", "tsc", "pytest")
_HEAVY_HINTS = ("refactor", "rewrite", "migrate", "analyze", "profile",
                "benchmark", "optimize")


def task_resource_needs(task: dict, use_local: bool = True) -> list[str]:
    """The resource classes one task needs, without double-taking the heavy slot.

    A model-using task needs exactly one model class (LOCAL_LLM or REMOTE_LLM)
    and, when it runs tests/compiles, BUILD. Because LOCAL_LLM and BUILD share
    the single heavy slot in the ledger, the task still only holds one heavy
    reservation — which is exactly the machine's real constraint.
    """
    needs: list[str] = []
    declared = (task.get("resource_class") or "").strip()
    if declared in ALL_CLASSES:
        needs.append(declared)
    text = f"{task.get('title', '')} {task.get('description', '')}".lower()
    role = (task.get("agent_role") or "").strip()
    if not needs:
        if role in _MODEL_ROLES or task.get("kind") in ("task", "subtask"):
            needs.append(LOCAL_LLM if use_local else REMOTE_LLM)
        elif any(h in text for h in _BUILD_HINTS):
            needs.append(BUILD)
        else:
            needs.append(CPU if any(h in text for h in _HEAVY_HINTS) else LIGHT)
    # a model task that also runs tests/builds additionally needs the build slot
    if BUILD not in needs and any(h in text for h in _BUILD_HINTS) \
            and (LOCAL_LLM in needs or REMOTE_LLM in needs):
        needs.append(BUILD)
    if CPU_HEAVY not in needs and any(h in text for h in _HEAVY_HINTS):
        needs.append(CPU)
    return needs


def estimate_resource_class(task: dict, use_local: bool = True) -> str:
    """The single primary class for a task (the heavy one when present)."""
    needs = task_resource_needs(task, use_local=use_local)
    for c in (LOCAL_LLM, BUILD, MEMORY_HEAVY, CPU_HEAVY, REMOTE_LLM, CPU,
              NETWORK, IO, LIGHT):
        if c in needs:
            return c
    return LIGHT


def self_improvement_priority(goal: str) -> str:
    """Elysia's own upgrades default to BACKGROUND (they never block a user)."""
    low = (goal or "").lower()
    markers = ("self-improve", "self improve", "refactor elysia", "upgrade elysia",
               "optimize elysia", "technical debt", "improve elysia",
               "self-modification", "self modification")
    return BACKGROUND if any(m in low for m in markers) else NORMAL


# ---------------------------------------------------------------------------
# Backward-compatible ResourceManager (kept: existing callers depend on it)
# ---------------------------------------------------------------------------
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
        info = _read_meminfo()
        if "MemAvailable" in info:
            return info["MemAvailable"] // 1024
        total = 0
        try:
            total = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
        except (ValueError, OSError, AttributeError):
            pass
        return total

    @staticmethod
    def total_memory_mb() -> int:
        info = _read_meminfo()
        if "MemTotal" in info:
            return info["MemTotal"] // 1024
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
        import shutil
        return any(shutil.which(t) for t in ("nvidia-smi", "rocm-smi"))

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
