"""
QThreadPool-based async worker utilities for background task execution.
"""

import logging
import traceback
import threading
from typing import Any, Callable, Optional
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)

# Global shutdown flag for thread-safe access
_shutdown_flag = threading.Event()


def is_shutting_down() -> bool:
    """Check if the application is shutting down."""
    return _shutdown_flag.is_set()


def set_shutting_down(value: bool = True) -> None:
    """Set the shutdown flag."""
    if value:
        _shutdown_flag.set()
    else:
        _shutdown_flag.clear()


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(object)


class Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        # Early exit if we're shutting down
        if is_shutting_down():
            return
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Background worker error: {e}\n{tb}")
            # Only emit if not shutting down
            if not is_shutting_down():
                try:
                    self.signals.error.emit({
                        "ok": False,
                        "error": {"title": "Background Error", "message": str(e)}
                    })
                except RuntimeError:
                    pass  # QObject already deleted
        else:
            # Only emit if not shutting down
            if not is_shutting_down():
                try:
                    self.signals.finished.emit(result)
                except RuntimeError:
                    pass  # QObject already deleted


class AsyncRunner(QObject):
    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()

    def run(self, fn: Callable[..., Any], on_finished: Callable[..., Any], on_error: Optional[Callable[..., Any]] = None, *args: Any, **kwargs: Any) -> Optional[Worker]:
        # Don't start new work if shutting down
        if is_shutting_down():
            logger.debug("AsyncRunner.run() called during shutdown, ignoring")
            return None
        w = Worker(fn, *args, **kwargs)
        w.signals.finished.connect(on_finished)
        if on_error:
            w.signals.error.connect(on_error)
        else:
            w.signals.error.connect(self._default_error_handler)
        self.pool.start(w)
        return w

    def _default_error_handler(self, err: Any) -> None:
        logger.error(f"Async worker error: {err}")
    
    def shutdown(self, wait_ms: int = 500) -> None:
        """Shutdown the async runner, waiting for active workers.
        
        Args:
            wait_ms: Maximum time to wait for workers to finish (milliseconds).
        """
        logger.debug("AsyncRunner.shutdown() - setting shutdown flag...")
        set_shutting_down(True)
        
        # Wait for thread pool to finish (with timeout)
        if self.pool:
            # Set a reasonable expiry timeout for the thread pool
            self.pool.setMaxThreadCount(1)  # Reduce concurrent threads
            if not self.pool.waitForDone(wait_ms):
                logger.debug("AsyncRunner.shutdown() - some workers did not finish in time")
            else:
                logger.debug("AsyncRunner.shutdown() - all workers finished")
