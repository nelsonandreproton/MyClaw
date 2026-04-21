import ast
from dataclasses import dataclass, field

# Full module names whose import is forbidden
BLOCKED_MODULES: frozenset[str] = frozenset({"subprocess", "socket"})

# Dotted call paths that are forbidden (caught as ast.Call nodes)
BLOCKED_CALLS: frozenset[str] = frozenset({"os.system", "shutil.rmtree", "__import__"})


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)


def validate_code(code: str) -> ValidationResult:
    errors: list[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ValidationResult(
            is_valid=False,
            errors=[f"SyntaxError linha {exc.lineno}: {exc.msg}"],
        )

    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", "?")

        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in BLOCKED_MODULES:
                    errors.append(
                        f"Linha {lineno}: import bloqueado '{alias.name}'"
                    )

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root in BLOCKED_MODULES:
                errors.append(
                    f"Linha {lineno}: import bloqueado de '{module}'"
                )

        elif isinstance(node, ast.Call):
            name = _dotted_name(node.func)
            if name in BLOCKED_CALLS:
                errors.append(
                    f"Linha {lineno}: chamada bloqueada '{name}'"
                )

    return ValidationResult(is_valid=len(errors) == 0, errors=errors)


def _dotted_name(node: ast.expr) -> str:
    """Resolve a dotted attribute chain to a string, e.g. os.system → 'os.system'."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""
