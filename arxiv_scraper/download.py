from __future__ import annotations

import hashlib
from pathlib import Path

from .feed import ThrottledClient


def download_pdf(client: ThrottledClient, url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    digest = hashlib.sha256()
    first = b""
    try:
        with client.open(url) as response, temporary.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                if not first:
                    first = block[:5]
                digest.update(block)
                output.write(block)
        if first != b"%PDF-":
            raise ValueError(f"Downloaded content is not a PDF: {url}")
        temporary.replace(destination)
        return digest.hexdigest()
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
