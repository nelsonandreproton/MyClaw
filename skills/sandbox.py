import builtins
import concurrent.futures
import datetime as _dt
import io
import json as _json
from dataclasses import dataclass

EXECUTION_TIMEOUT = 30  # seconds

# Builtins exposed inside the sandbox (spec section 6)
_SAFE_BUILTIN_NAMES: list[str] = [
    # core functions
    "print", "len", "range", "str", "int", "float",
    "list", "dict", "tuple", "set", "bool", "type",
    "enumerate", "zip", "map", "filter", "sorted",
    "min", "max", "sum", "abs", "round",
    "isinstance", "hasattr", "getattr", "setattr",
    "any", "all", "next", "iter", "repr", "id", "hash",
    "format", "vars",
    # exceptions
    "Exception", "ValueError", "TypeError", "KeyError",
    "AttributeError", "RuntimeError", "StopIteration",
    "IndexError", "OSError", "IOError", "NotImplementedError",
    # required by Python internals (class/import machinery)
    "__import__", "__build_class__", "__name__",
]


@dataclass
class ExecutionResult:
    success: bool
    output: str
    error: str | None = None


def execute_in_sandbox(
    code: str,
    injected_context: dict,
    timeout: int = EXECUTION_TIMEOUT,
) -> ExecutionResult:
    """Execute *code* in a restricted namespace inside a worker thread.

    stdout is captured and returned in ExecutionResult.output.
    The thread is given at most *timeout* seconds before being abandoned.
    """
    captured = io.StringIO()

    # Build a minimal builtins dict from the safe list
    safe_builtins: dict = {}
    for name in _SAFE_BUILTIN_NAMES:
        obj = getattr(builtins, name, None)
        if obj is not None:
            safe_builtins[name] = obj

    # Redirect print to the capture buffer
    def _print(*args, sep: str = " ", end: str = "\n", file=None, flush: bool = False) -> None:
        captured.write(sep.join(str(a) for a in args) + end)

    safe_builtins["print"] = _print

    # Inject safe stdlib objects referenced in the spec's ALLOWED_BUILTINS
    safe_builtins["datetime"] = _dt.datetime
    safe_builtins["date"] = _dt.date
    safe_builtins["json"] = _json

    namespace: dict = {
        "__builtins__": safe_builtins,
        **injected_context,
    }

    def _run() -> None:
        exec(compile(code, "<skill>", "exec"), namespace)  # noqa: S102

    # Use shutdown(wait=False) so a timed-out thread doesn't block the caller.
    # Python cannot forcibly kill threads; the thread may linger in the background
    # until it finishes, but our caller returns immediately after the timeout.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_run)
    pool.shutdown(wait=False)

    try:
        future.result(timeout=timeout)
        return ExecutionResult(success=True, output=captured.getvalue())
    except concurrent.futures.TimeoutError:
        return ExecutionResult(
            success=False,
            output=captured.getvalue(),
            error=f"Timeout: execução excedeu {timeout}s",
        )
    except Exception as exc:  # noqa: BLE001
        return ExecutionResult(
            success=False,
            output=captured.getvalue(),
            error=str(exc),
        )
