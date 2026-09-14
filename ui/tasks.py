from __future__ import annotations

import queue
import threading
from tkinter import Misc
from typing import Callable, Optional, Set, TypeVar

from modules.errors import OptimizerError

T = TypeVar("T")


class TaskRunner:
    # runs blocking work on daemon threads and hands the result back on the tk thread,
    # tkinter widgets must never be touched from a worker thread
    def __init__(self, root: Misc, poll_ms: int = 80) -> None:
        self._root = root
        self._poll_ms = poll_ms
        self._callbacks: queue.Queue[Callable[[], None]] = queue.Queue()
        self._running: Set[str] = set()
        self._poll_id: Optional[str] = root.after(poll_ms, self._poll)

    def is_running(self, name: str) -> bool:
        return name in self._running

    def post(self, callback: Callable[[], None]) -> None:
        self._callbacks.put(callback)

    def run(self, name: str, work: Callable[[], T], on_done: Callable[[T], None], on_error: Callable[[str], None]) -> bool:
        if name in self._running:
            return False
        self._running.add(name)

        def target() -> None:
            try:
                result = work()
            except OptimizerError as exc:
                message = exc.message
                self.post(lambda: self._finish(name, lambda: on_error(message)))
                return
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                self.post(lambda: self._finish(name, lambda: on_error(message)))
                return
            self.post(lambda: self._finish(name, lambda: on_done(result)))

        threading.Thread(target=target, daemon=True).start()
        return True

    def stop(self) -> None:
        if self._poll_id is not None:
            self._root.after_cancel(self._poll_id)
            self._poll_id = None

    def _finish(self, name: str, callback: Callable[[], None]) -> None:
        self._running.discard(name)
        callback()

    def _poll(self) -> None:
        try:
            while True:
                self._callbacks.get_nowait()()
        except queue.Empty:
            pass
        self._poll_id = self._root.after(self._poll_ms, self._poll)
