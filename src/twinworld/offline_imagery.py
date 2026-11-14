"""Repository-backed NASA globe tile package used by the local ENOM app."""

from __future__ import annotations

import json
import re
import shutil
import threading
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from PIL import Image
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[2]
TILE_ROOT = ROOT / "apps/twinworld/public/tiles/offline"
STATE_PATH = ROOT / "data/offline_globe_maps/state.json"
MAX_LEVEL = 6
WORKERS = 16
ESTIMATED_BYTES = 600 * 1024 * 1024
WMTS = "http://www.opengis.net/wmts/1.0"
OWS = "http://www.opengis.net/ows/1.1"
NS = {"wmts": WMTS, "ows": OWS}
OFFLINE_MATRIX_DIMENSIONS: dict[str, list[tuple[int, int]]] = {
    "earth": [(2, 1), (3, 2), (5, 3), (10, 5), (20, 10), (40, 20), (80, 40), (160, 80)],
    "mars": [(2, 1), (4, 2), (8, 4), (16, 8), (32, 16), (64, 32), (128, 64), (256, 128)],
    "moon": [(2, 1), (4, 2), (8, 4), (16, 8), (32, 16), (64, 32), (128, 64), (256, 128), (512, 256)],
}

SOURCES: dict[str, dict[str, str]] = {
    "earth": {
        "version": "blue-marble-next-generation-2004-v1",
        "layer": "BlueMarble_NextGeneration",
        "matrix_set": "500m",
        "capabilities": "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/1.0.0/WMTSCapabilities.xml",
        "url": "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/BlueMarble_NextGeneration/default/500m/{z}/{y}/{x}.jpeg",
        "ext": "jpeg",
    },
    "mars": {
        "version": "mars-viking-mdim21-global-1.0.0-v1",
        "layer": "Mars_Viking_MDIM21_ClrMosaic_global_232m",
        "matrix_set": "default028mm",
        "capabilities": "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/WMTSCapabilities.xml",
        "url": "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/{z}/{y}/{x}.jpg",
        "ext": "jpg",
    },
    "moon": {
        "version": "moon-lro-wac-global-v02-1.0.0-v1",
        "layer": "LRO_WAC_Mosaic_Global_303ppd_v02",
        "matrix_set": "default028mm",
        "capabilities": "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/WMTSCapabilities.xml",
        "url": "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{y}/{x}.jpg",
        "ext": "jpg",
    },
}
SOURCE_VERSIONS = {body: source["version"] for body, source in SOURCES.items()}

_lock = threading.RLock()
_stop_mode: str | None = None
_worker_thread: threading.Thread | None = None
_state: dict[str, Any] = {
    "status": "idle", "completed": 0, "total": 0, "bytes": 0,
    "required_bytes": ESTIMATED_BYTES, "error": None, "source_versions": SOURCE_VERSIONS,
}
_metadata_cache: dict[str, list[dict[str, Any]]] = {}


def _state_path() -> Path:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return STATE_PATH


def _save_state() -> None:
    path = _state_path()
    temp = path.with_name(f"{path.stem}.{threading.get_ident()}.tmp")
    temp.write_text(json.dumps(_state, indent=2), encoding="utf-8")
    temp.replace(path)


def _read_metadata(body: str) -> list[dict[str, Any]]:
    if body in _metadata_cache:
        return _metadata_cache[body]
    source = SOURCES[body]
    request = urllib.request.Request(source["capabilities"], headers={"User-Agent": "ENOM globe tile package"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            root = ET.fromstring(response.read())
    except Exception:
        matrices = [
            {"id": str(level), "width": width, "height": height}
            for level, (width, height) in enumerate(OFFLINE_MATRIX_DIMENSIONS[body])
        ]
        _metadata_cache[body] = matrices
        return matrices
    layer = next((node for node in root.findall(".//wmts:Layer", NS) if node.findtext("ows:Identifier", namespaces=NS) == source["layer"]), None)
    if layer is None:
        raise RuntimeError(f"NASA WMTS layer missing for {body}")
    linked = {
        node.findtext("wmts:TileMatrixSet", namespaces=NS)
        for node in layer.findall("wmts:TileMatrixSetLink", NS)
    }
    if source["matrix_set"] not in linked:
        raise RuntimeError(f"NASA matrix set missing for {body}")
    matrix_set = next(
        (node for node in root.findall(".//wmts:TileMatrixSet", NS) if node.findtext("ows:Identifier", namespaces=NS) == source["matrix_set"]),
        None,
    )
    if matrix_set is None:
        raise RuntimeError(f"NASA matrix metadata missing for {body}")
    matrices = []
    for node in matrix_set.findall("wmts:TileMatrix", NS):
        identifier = node.findtext("ows:Identifier", namespaces=NS) or ""
        width = int(float(node.findtext("wmts:MatrixWidth", namespaces=NS) or "0"))
        height = int(float(node.findtext("wmts:MatrixHeight", namespaces=NS) or "0"))
        if identifier and width > 0 and height > 0:
            matrices.append({"id": identifier, "width": width, "height": height})
    _metadata_cache[body] = matrices
    return matrices


def _tile_path(body: str, matrix_id: str, row: int, col: int) -> Path:
    source = SOURCES[body]
    return TILE_ROOT / body / source["version"] / source["matrix_set"] / matrix_id / str(row) / f"{col}.{source['ext']}"


def _missing_path(body: str, matrix_id: str, row: int, col: int) -> Path:
    return _tile_path(body, matrix_id, row, col).with_suffix(".missing")


def _tile_url(body: str, matrix_id: str, row: int, col: int) -> str:
    return SOURCES[body]["url"].format(z=matrix_id, y=row, x=col)


def _manifest() -> list[tuple[str, str, int, int]]:
    items: list[tuple[str, str, int, int]] = []
    for body in SOURCES:
        for matrix in _read_metadata(body)[: MAX_LEVEL + 1]:
            for row in range(matrix["height"]):
                for col in range(matrix["width"]):
                    items.append((body, matrix["id"], row, col))
    return items


def _snapshot() -> dict[str, Any]:
    with _lock:
        has_saved_tiles = TILE_ROOT.exists() and next((path for path in TILE_ROOT.rglob("*") if path.is_file()), None) is not None
        return {**_state, "available_bytes": _available_bytes(), "persistent": None, "has_saved_tiles": has_saved_tiles}


def _available_bytes() -> int | None:
    try:
        import shutil as disk_usage
        return disk_usage.disk_usage(ROOT).free
    except OSError:
        return None


def _evict_old_viewed_tiles(incoming_bytes: int, keep: Path) -> None:
    available = _available_bytes()
    if available is None or available >= incoming_bytes + 256 * 1024 * 1024:
        return
    candidates: list[tuple[float, Path]] = []
    for path in TILE_ROOT.rglob("*"):
        if not path.is_file() or path == keep or path.suffix.lower() not in {".jpg", ".jpeg"}:
            continue
        try:
            level = int(path.parent.parent.name)
        except ValueError:
            continue
        if level > MAX_LEVEL:
            candidates.append((path.stat().st_mtime, path))
    for _, path in sorted(candidates):
        path.unlink(missing_ok=True)
        available = _available_bytes()
        if available is None or available >= incoming_bytes + 256 * 1024 * 1024:
            return


def status() -> dict[str, Any]:
    state_file = _state_path()
    with _lock:
        active_thread = _worker_thread is not None and _worker_thread.is_alive()
        active_state = _state["status"] in {"downloading", "preparing"}
    if active_state and active_thread:
        return _snapshot()
    if state_file.is_file():
        try:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
            with _lock:
                _state.update(saved)
                source_stale = _state.get("source_versions") != SOURCE_VERSIONS and _state.get("total", 0)
                interrupted = _state["status"] in {"downloading", "preparing"}
            if source_stale:
                with _lock:
                    _state.update(status="stale", error="NASA source version changed. Start a new repository download to refresh saved tiles.")
                    _save_state()
            elif interrupted:
                try:
                    items = _manifest()
                    complete = sum(
                        1 for body, matrix_id, row, col in items
                        if _tile_path(body, matrix_id, row, col).is_file() or _missing_path(body, matrix_id, row, col).is_file()
                    )
                    total_bytes = sum(
                        path.stat().st_size for path in TILE_ROOT.rglob("*")
                        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}
                    )
                    with _lock:
                        _state.update(
                            status="complete" if complete == len(items) else "paused",
                            completed=complete,
                            total=len(items),
                            bytes=total_bytes,
                            error=None if complete == len(items) else "Server restarted; resume the local map download when ready.",
                        )
                        _save_state()
                except Exception:
                    with _lock:
                        _state.update(status="paused", error="Server restarted; resume the local map download when ready.")
        except (OSError, ValueError):
            pass
    return _snapshot()


def _valid_tile(body: str, matrix_set: str, matrix_id: str, row: int, col: int) -> bool:
    if body not in SOURCES or SOURCES[body]["matrix_set"] != matrix_set or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", matrix_id):
        return False
    matrix = next((item for item in _read_metadata(body) if item["id"] == matrix_id), None)
    return matrix is not None and 0 <= row < matrix["height"] and 0 <= col < matrix["width"]


def tile_file(body: str, version: str, matrix_set: str, matrix_id: str, row: int, col: int) -> Path | None:
    source = SOURCES.get(body)
    if source is None or source["version"] != version or not _valid_tile(body, matrix_set, matrix_id, row, col):
        return None
    path = _tile_path(body, matrix_id, row, col)
    return path if path.is_file() else None


def tile_is_missing(body: str, version: str, matrix_set: str, matrix_id: str, row: int, col: int) -> bool:
    source = SOURCES.get(body)
    if source is None or source["version"] != version or not _valid_tile(body, matrix_set, matrix_id, row, col):
        return False
    return _missing_path(body, matrix_id, row, col).is_file()


def save_viewed_tile(body: str, version: str, matrix_set: str, matrix_id: str, row: int, col: int, content: bytes) -> bool:
    source = SOURCES.get(body)
    if source is None or source["version"] != version or not _valid_tile(body, matrix_set, matrix_id, row, col):
        return False
    if len(content) > 4 * 1024 * 1024:
        return False
    try:
        from io import BytesIO
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except Exception:
        return False
    path = _tile_path(body, matrix_id, row, col)
    if matrix_id.isdigit() and int(matrix_id) > MAX_LEVEL:
        _evict_old_viewed_tiles(len(content), path)
        available = _available_bytes()
        if available is not None and available < len(content):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(content)
    temp.replace(path)
    _missing_path(body, matrix_id, row, col).unlink(missing_ok=True)
    return True


def _fetch_one(item: tuple[str, str, int, int], session: requests.Session) -> tuple[str, int]:
    body, matrix_id, row, col = item
    path = _tile_path(body, matrix_id, row, col)
    missing = _missing_path(body, matrix_id, row, col)
    if path.is_file() or missing.is_file():
        return "existing", path.stat().st_size if path.is_file() else 0
    response = session.get(_tile_url(body, matrix_id, row, col), timeout=(10, 30))
    if response.status_code in {404, 204}:
        missing.parent.mkdir(parents=True, exist_ok=True)
        missing.touch()
        return "missing", 0
    response.raise_for_status()
    content = response.content
    if len(content) > 4 * 1024 * 1024 or not response.headers.get("Content-Type", "").startswith("image/"):
        raise RuntimeError("NASA returned an invalid tile response")
    from io import BytesIO
    with Image.open(BytesIO(content)) as image:
        image.verify()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(content)
    temp.replace(path)
    return "saved", len(content)


def _run_download(items: list[tuple[str, str, int, int]]) -> None:
    global _stop_mode
    completed = 0
    bytes_saved = 0
    total = len(items)
    with _lock:
        _state.update(status="downloading", completed=0, total=total, bytes=0, error=None, required_bytes=ESTIMATED_BYTES)
        _save_state()
    iterator = iter(items)
    iterator_lock = threading.Lock()
    failed: list[Exception] = []

    def worker() -> None:
        global _stop_mode
        nonlocal completed, bytes_saved
        retry = Retry(
            total=5, connect=4, read=3, status=5, backoff_factor=0.35,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=1, pool_maxsize=1)
        with requests.Session() as session:
            session.headers.update({"User-Agent": "ENOM globe tile package"})
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            while True:
                with _lock:
                    if _stop_mode:
                        return
                with iterator_lock:
                    item = next(iterator, None)
                if item is None:
                    return
                try:
                    result, size = _fetch_one(item, session)
                except Exception as error:
                    with _lock:
                        failed.append(error)
                        _stop_mode = "error"
                    return
                with _lock:
                    completed += 1
                    bytes_saved += size
                    _state.update(completed=completed, bytes=bytes_saved)
                    if completed % 20 == 0:
                        _save_state()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(worker) for _ in range(WORKERS)]
        for future in futures:
            try:
                future.result()
            except Exception as error:
                with _lock:
                    failed.append(error)
                    _stop_mode = "error"
    with _lock:
        if failed:
            _state.update(status="error", error=str(failed[0]))
        elif _stop_mode == "pause":
            _state.update(status="paused")
        elif _stop_mode == "cancel":
            _state.update(status="cancelled")
        elif completed == total:
            _state.update(status="complete", completed=total, error=None)
        _stop_mode = None
        _save_state()


def start() -> dict[str, Any]:
    global _worker_thread, _stop_mode
    with _lock:
        if _worker_thread and _worker_thread.is_alive():
            return _snapshot()
        _stop_mode = None
        _state.update(status="preparing", error=None)
        _save_state()
    try:
        TILE_ROOT.mkdir(parents=True, exist_ok=True)
        for body, version in SOURCE_VERSIONS.items():
            body_root = TILE_ROOT / body
            if body_root.is_dir():
                for old_version in body_root.iterdir():
                    if old_version.name != version:
                        shutil.rmtree(old_version, ignore_errors=True)
    except OSError as error:
        with _lock:
            _state.update(status="error", error=f"Could not prepare repository tile storage: {error}")
            _save_state()
        return _snapshot()
    try:
        items = _manifest()
    except Exception as error:
        with _lock:
            _state.update(status="error", error=str(error))
            _save_state()
        return _snapshot()
    remaining = sum(
        1 for body, matrix_id, row, col in items
        if not _tile_path(body, matrix_id, row, col).is_file() and not _missing_path(body, matrix_id, row, col).is_file()
    )
    remaining_estimate = int(ESTIMATED_BYTES * remaining / max(1, len(items)))
    available = _available_bytes()
    if available is not None and available < remaining_estimate:
        with _lock:
            _state.update(status="error", error=f"Not enough free repository disk space for the remaining estimated {remaining_estimate / 1024 ** 2:.0f} MB of tiles.")
            _save_state()
        return _snapshot()
    with _lock:
        _state.update(status="downloading", total=len(items), required_bytes=ESTIMATED_BYTES, source_versions=SOURCE_VERSIONS)
        _worker_thread = threading.Thread(target=_run_download, args=(items,), daemon=True, name="enom-globe-map-download")
        _worker_thread.start()
    return _snapshot()


def pause() -> dict[str, Any]:
    global _stop_mode
    with _lock:
        if _state["status"] == "downloading":
            _stop_mode = "pause"
    return _snapshot()


def cancel() -> dict[str, Any]:
    global _stop_mode
    with _lock:
        if _state["status"] == "downloading":
            _stop_mode = "cancel"
    return _snapshot()


def clear() -> dict[str, Any]:
    global _stop_mode
    with _lock:
        if _worker_thread and _worker_thread.is_alive():
            raise RuntimeError("Pause or cancel the download before clearing maps")
        _stop_mode = None
        shutil.rmtree(TILE_ROOT, ignore_errors=True)
        STATE_PATH.unlink(missing_ok=True)
        _state.update(status="idle", completed=0, total=0, bytes=0, error=None, required_bytes=ESTIMATED_BYTES, source_versions=SOURCE_VERSIONS)
        return _snapshot()
