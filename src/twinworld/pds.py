"""Verified byte-range reads for PDS raster products."""

from __future__ import annotations

import requests


def read_byte_range(
    url: str,
    start_byte: int,
    end_byte: int,
    *,
    timeout: float | tuple[float, float],
    session: requests.Session | None = None,
    product_name: str = "PDS",
) -> bytes:
    """Read exactly one inclusive HTTP byte range or raise with its failure reason."""
    if start_byte < 0 or end_byte < start_byte:
        raise ValueError("byte range must have a non-negative start and end >= start")

    get = session.get if session is not None else requests.get
    response = get(
        url,
        headers={"Range": f"bytes={start_byte}-{end_byte}"},
        timeout=timeout,
        stream=True,
    )
    try:
        response.raise_for_status()
        expected_range = f"bytes {start_byte}-{end_byte}/"
        if response.status_code != 206:
            raise RuntimeError(f"{product_name} server did not honor the byte-range request")
        if not response.headers.get("Content-Range", "").startswith(expected_range):
            raise RuntimeError(f"{product_name} returned an unexpected Content-Range")
        payload = response.content
        if len(payload) != end_byte - start_byte + 1:
            raise RuntimeError(f"{product_name} range length does not match the request")
        return payload
    finally:
        response.close()
