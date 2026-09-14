# gputil and py-cpuinfo ship without type hints
# pyright: reportMissingTypeStubs=false
from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional, cast

try:
    import cpuinfo
except ImportError:
    cpuinfo = None

try:
    import GPUtil
except Exception:
    # gputil needs distutils which is gone on python 3.12+ unless setuptools is installed
    GPUtil = None


# low end nvidia cards that ship without an nvenc block
_NO_NVENC = re.compile(r"\b(GT\s?(610|620|705|710|720|730|1010|1030)|MX\s?\d{3})\b", re.IGNORECASE)
_OLD_RADEON = re.compile(r"\bRadeon\s+HD\s?[2-6]\d{3}\b", re.IGNORECASE)
_IGNORED_ADAPTERS = ("basic display", "basic render", "virtual", "remote display", "parsec", "citrix", "vmware", "virtualbox")


@dataclass
class GPUInfo:
    name: str
    vendor: str
    vram_mb: Optional[int] = None


@dataclass
class SystemInfo:
    cpu_name: str
    physical_cores: int
    logical_cores: int
    ram_gb: float
    gpus: List[GPUInfo] = field(default_factory=list[GPUInfo])
    has_nvenc: bool = False
    has_amf: bool = False
    has_qsv: bool = False
    errors: List[str] = field(default_factory=list[str])


def gpu_vendor(name: str) -> str:
    lowered = name.lower()
    if any(k in lowered for k in ("nvidia", "geforce", "quadro", "tesla", "titan")):
        return "nvidia"
    if any(k in lowered for k in ("amd", "radeon", "firepro")):
        return "amd"
    if "intel" in lowered or re.search(r"\barc\b", lowered):
        return "intel"
    return "unknown"


def supports_nvenc(name: str) -> bool:
    return gpu_vendor(name) == "nvidia" and not _NO_NVENC.search(name)


def supports_amf(name: str) -> bool:
    return gpu_vendor(name) == "amd" and not _OLD_RADEON.search(name)


def supports_qsv(name: str) -> bool:
    return gpu_vendor(name) == "intel"


def _run(cmd: List[str], timeout: float = 10) -> str:
    # keeps a console window from flashing when launched from the gui
    creationflags: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, creationflags=creationflags)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _cpu_name() -> str:
    if cpuinfo is not None:
        try:
            name = cpuinfo.get_cpu_info().get("brand_raw", "")
            if name:
                return name.strip()
        except Exception:
            pass
    return (platform.processor() or "").strip()


def _nvidia_gpus() -> List[GPUInfo]:
    if GPUtil is not None:
        try:
            devices = cast(List[Any], GPUtil.getGPUs())
            found = [GPUInfo(str(g.name), "nvidia", int(g.memoryTotal)) for g in devices]
            if found:
                return found
        except Exception:
            pass

    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    gpus: List[GPUInfo] = []
    for line in _run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]).splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts[0]:
            continue
        try:
            vram = int(float(parts[1]))
        except (IndexError, ValueError):
            vram = None
        gpus.append(GPUInfo(parts[0], "nvidia", vram))
    return gpus


def _os_gpu_names() -> List[str]:
    names: List[str] = []
    if sys.platform == "win32":
        out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"])
        if not out.strip():
            out = "\n".join(_run(["wmic", "path", "win32_VideoController", "get", "name"]).splitlines()[1:])
        names = out.splitlines()
    elif sys.platform.startswith("linux"):
        for line in _run(["lspci"]).splitlines():
            if any(k in line for k in ("VGA compatible controller", "3D controller", "Display controller")):
                names.append(line.split(": ", 1)[-1])
    elif sys.platform == "darwin":
        for line in _run(["system_profiler", "SPDisplaysDataType"]).splitlines():
            if "Chipset Model:" in line:
                names.append(line.split(":", 1)[1])
    return [n.strip() for n in names if n.strip()]


def detect_gpus() -> List[GPUInfo]:
    gpus = _nvidia_gpus()
    seen = {g.name.lower() for g in gpus}
    has_nvidia = bool(gpus)
    for name in _os_gpu_names():
        lowered = name.lower()
        if lowered in seen or any(k in lowered for k in _IGNORED_ADAPTERS):
            continue
        # lspci names nvidia cards differently than nvidia-smi, trust nvidia-smi when it worked
        if has_nvidia and gpu_vendor(name) == "nvidia":
            continue
        seen.add(lowered)
        gpus.append(GPUInfo(name, gpu_vendor(name)))
    return gpus


def scan_system() -> SystemInfo:
    import psutil

    errors: List[str] = []

    cpu_name = _cpu_name()
    if not cpu_name:
        errors.append("Could not read the CPU model name.")

    logical = psutil.cpu_count(logical=True) or 1
    # physical count can be None on some vms
    physical = psutil.cpu_count(logical=False) or logical

    try:
        ram_gb = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception:
        ram_gb = 0.0
        errors.append("Could not read the installed RAM.")

    try:
        gpus = detect_gpus()
    except Exception:
        gpus = []
    if not gpus:
        errors.append("No GPU was detected. Hardware encoders are unavailable, x264 (CPU) will be used.")

    return SystemInfo(
        cpu_name=cpu_name or "Unknown CPU",
        physical_cores=physical,
        logical_cores=logical,
        ram_gb=ram_gb,
        gpus=gpus,
        has_nvenc=any(supports_nvenc(g.name) for g in gpus),
        has_amf=any(supports_amf(g.name) for g in gpus),
        has_qsv=any(supports_qsv(g.name) for g in gpus),
        errors=errors,
    )
