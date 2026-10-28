from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("w")
    try:
        try:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass
        except BlockingIOError as exc:
            raise RuntimeError("Another arxiv-scraper process is already running") from exc
        stream.write(str(__import__("os").getpid()))
        stream.flush()
        yield
    finally:
        stream.close()
