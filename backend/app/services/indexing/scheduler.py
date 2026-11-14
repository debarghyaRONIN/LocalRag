import os
import asyncio
import logging
import shutil
import subprocess
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional, Tuple
import psutil

logger = logging.getLogger(__name__)


class ResourceScheduler:
    """
    Resource-aware scheduler monitoring system RAM and GPU VRAM.
    Enforces priority scheduling: throttles or yields background embedding
    and indexing when an interactive chat generation is in flight.
    """

    _instance: Optional["ResourceScheduler"] = None

    def __init__(
        self,
        ram_threshold_percent: float = float(os.getenv("INDEXING_RAM_THRESHOLD_PERCENT", "95.0")),
        vram_threshold_percent: float = float(os.getenv("INDEXING_VRAM_THRESHOLD_PERCENT", "95.0")),
        vram_min_free_mb: int = int(os.getenv("INDEXING_VRAM_MIN_FREE_MB", "500")),
    ):
        self.ram_threshold_percent = ram_threshold_percent
        self.vram_threshold_percent = vram_threshold_percent
        self.vram_min_free_mb = vram_min_free_mb

        self._active_chats: int = 0
        self._chat_lock = asyncio.Lock()
        self._smi_path: Optional[str] = shutil.which("nvidia-smi")

    @classmethod
    def get_instance(cls) -> "ResourceScheduler":
        if cls._instance is None:
            cls._instance = ResourceScheduler()
        return cls._instance

    # ---------------------------------------------------------
    # Priority Chat Generation Tracking
    # ---------------------------------------------------------
    @property
    def has_active_chats(self) -> bool:
        """True if any interactive chat generation or query is currently in flight."""
        return self._active_chats > 0

    @property
    def active_chats_count(self) -> int:
        return self._active_chats

    async def register_chat_start(self):
        """Register the start of an interactive chat generation."""
        async with self._chat_lock:
            self._active_chats += 1
            logger.debug(f"[PriorityScheduler] Interactive chat registered. Active: {self._active_chats}")

    async def register_chat_finish(self):
        """Register the completion of an interactive chat generation."""
        async with self._chat_lock:
            self._active_chats = max(0, self._active_chats - 1)
            logger.debug(f"[PriorityScheduler] Interactive chat finished. Active: {self._active_chats}")

    @asynccontextmanager
    async def priority_chat_scope(self):
        """Context manager to mark an interactive chat request in flight."""
        await self.register_chat_start()
        try:
            yield
        finally:
            await self.register_chat_finish()

    # ---------------------------------------------------------
    # Resource Monitoring (RAM & GPU VRAM)
    # ---------------------------------------------------------
    def get_ram_usage(self) -> Dict[str, Any]:
        """Inspect host system RAM using psutil."""
        try:
            vm = psutil.virtual_memory()
            return {
                "total_mb": vm.total // (1024 * 1024),
                "available_mb": vm.available // (1024 * 1024),
                "used_mb": vm.used // (1024 * 1024),
                "percent": vm.percent,
                "constrained": vm.percent >= self.ram_threshold_percent,
            }
        except Exception as e:
            logger.warning(f"Failed to read RAM usage: {e}")
            return {
                "total_mb": 0,
                "available_mb": 0,
                "used_mb": 0,
                "percent": 0.0,
                "constrained": False,
            }

    def get_vram_usage(self) -> List[Dict[str, Any]]:
        """Inspect GPU devices and their VRAM usage using nvidia-smi."""
        devices = []
        if not self._smi_path:
            return devices

        try:
            cmd = [
                self._smi_path,
                "--query-gpu=index,name,memory.total,memory.free,memory.used",
                "--format=csv,noheader,nounits",
            ]
            output = subprocess.check_output(cmd, encoding="utf-8", timeout=2.0).strip()
            if not output:
                return devices

            for line in output.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    idx = int(parts[0])
                    name = parts[1]
                    total_mb = int(parts[2])
                    free_mb = int(parts[3])
                    used_mb = int(parts[4])
                    percent = (used_mb / total_mb * 100.0) if total_mb > 0 else 0.0
                    constrained = (
                        percent >= self.vram_threshold_percent or free_mb < self.vram_min_free_mb
                    )
                    devices.append({
                        "index": idx,
                        "name": name,
                        "vram_total_mb": total_mb,
                        "vram_free_mb": free_mb,
                        "vram_used_mb": used_mb,
                        "percent": round(percent, 1),
                        "constrained": constrained,
                    })
        except Exception as e:
            logger.debug(f"Unable to query nvidia-smi for VRAM: {e}")

        return devices

    def check_constraints(self) -> Tuple[bool, List[str]]:
        """
        Check if system is resource-constrained or yielding for interactive chat.
        Returns (is_constrained, reasons).
        """
        reasons = []

        # 1. Interactive chat priority check
        if self.has_active_chats:
            reasons.append(f"Interactive chat in flight ({self._active_chats} active session(s))")

        # 2. RAM check
        ram = self.get_ram_usage()
        if ram.get("constrained"):
            reasons.append(f"High RAM usage: {ram.get('percent')}% >= {self.ram_threshold_percent}%")

        # 3. GPU VRAM check
        for dev in self.get_vram_usage():
            if dev.get("constrained"):
                reasons.append(
                    f"GPU {dev.get('index')} ({dev.get('name')}) VRAM constrained: "
                    f"{dev.get('percent')}% used, {dev.get('vram_free_mb')}MB free"
                )

        return len(reasons) > 0, reasons

    # ---------------------------------------------------------
    # Background Throttling & Yielding
    # ---------------------------------------------------------
    async def throttle_or_yield(
        self,
        job_id: Optional[str] = None,
        poll_interval: float = 0.2,
        max_wait_seconds: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Throttles or yields execution of background embedding / indexing tasks.
        If an interactive chat generation is active, pauses until the chat turn completes.
        If RAM/VRAM thresholds are exceeded, yields until resource levels drop below danger levels.
        Always performs a cooperative async sleep to prevent event loop starvation.
        """
        waited_seconds = 0.0
        throttled = False
        reasons_encountered = []

        while True:
            is_constrained, reasons = self.check_constraints()
            if not is_constrained or waited_seconds >= max_wait_seconds:
                if reasons:
                    reasons_encountered.extend(reasons)
                break

            throttled = True
            for r in reasons:
                if r not in reasons_encountered:
                    reasons_encountered.append(r)

            logger.info(
                f"[Scheduler] Throttling background indexing (job: {job_id or 'unknown'}): "
                f"{', '.join(reasons)}. Waiting {poll_interval}s..."
            )
            await asyncio.sleep(poll_interval)
            waited_seconds += poll_interval

        # Cooperative yield to FastAPI event loop
        await asyncio.sleep(0.005)

        return {
            "throttled": throttled,
            "waited_seconds": round(waited_seconds, 2),
            "reasons": reasons_encountered,
            "metrics": self.get_system_metrics(),
        }

    def get_system_metrics(self) -> Dict[str, Any]:
        """Aggregate snapshot of system RAM, GPU VRAM, active chat generations, and status."""
        ram = self.get_ram_usage()
        vram = self.get_vram_usage()
        is_constrained, reasons = self.check_constraints()

        return {
            "active_interactive_chats": self._active_chats,
            "is_throttled": is_constrained,
            "throttle_reasons": reasons,
            "ram": ram,
            "gpu_devices": vram,
        }


def get_resource_scheduler() -> ResourceScheduler:
    return ResourceScheduler.get_instance()
