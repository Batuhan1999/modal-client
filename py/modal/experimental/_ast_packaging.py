"""Build a reduced, importable Python source tree for one function."""

import ast
import copy
import hashlib
import inspect
from pathlib import Path
from typing import Any, Callable


def _definitions(tree: ast.Module) -> dict[str, ast.stmt]:
    definitions: dict[str, ast.stmt] = {}
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions[statement.name] = statement
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = statement
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                definitions[alias.asname or alias.name.split(".")[0]] = statement
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                definitions[alias.asname or alias.name.split(".")[0]] = statement
    return definitions


def _read_globals(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        reads = {
            child.id
            for statement in node.body
            for child in ast.walk(statement)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
        }
        locals_ = {
            child.id
            for statement in node.body
            for child in ast.walk(statement)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
        }
        parameters = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        if node.args.vararg is not None:
            parameters.add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            parameters.add(node.args.kwarg.arg)
        return reads - locals_ - parameters
    if isinstance(node, ast.Assign):
        return {
            child.id
            for child in ast.walk(node.value)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
        }
    return set()


def _source_package(source_file: Path) -> tuple[Path, tuple[str, ...]]:
    package_parts: list[str] = []
    directory = source_file.parent
    while (directory / "__init__.py").is_file():
        package_parts.insert(0, directory.name)
        directory = directory.parent
    return directory, tuple(package_parts)


def _collect_local_sources(
    project_root: Path, entry_path: Path, reduced_source: str, include_modules: tuple[str, ...]
) -> dict[str, bytes]:
    project_root = project_root.resolve()
    sources = {entry_path.as_posix(): reduced_source.encode("utf-8")}
    pending = [(entry_path, sources[entry_path.as_posix()])]

    def add_file(path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_relative_to(project_root):
            raise ValueError(f"local module escapes project root: {path}")
        archive_path = path.relative_to(project_root).as_posix()
        content = path.read_bytes()
        if archive_path in sources:
            if sources[archive_path] != content:
                raise ValueError(f"generated function conflicts with local module {archive_path!r}")
            return
        sources[archive_path] = content
        pending.append((Path(archive_path), content))
        parent = path.parent
        while parent != project_root:
            init = parent / "__init__.py"
            if init.is_file():
                add_file(init)
            parent = parent.parent

    def add_module(parts: tuple[str, ...], *, recursive: bool = False) -> bool:
        if not parts:
            return False
        module_path = project_root.joinpath(*parts)
        module_file = module_path.with_suffix(".py")
        package_init = module_path / "__init__.py"
        if module_file.is_file():
            add_file(module_file)
            return True
        if package_init.is_file() or (recursive and module_path.is_dir()):
            if package_init.is_file():
                add_file(package_init)
            if recursive:
                for child in sorted(module_path.rglob("*.py")):
                    add_file(child)
            return True
        return False

    for module_name in include_modules:
        if (
            not isinstance(module_name, str)
            or not module_name
            or not all(part.isidentifier() for part in module_name.split("."))
        ):
            raise ValueError(f"invalid included module name {module_name!r}")
        if not add_module(tuple(module_name.split(".")), recursive=True):
            raise ValueError(f"included local module {module_name!r} was not found")

    while pending:
        archive_path, content = pending.pop()
        package = archive_path.parent.parts if archive_path.parent != Path(".") else ()
        tree = ast.parse(content, filename=archive_path.as_posix())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    add_module(tuple(alias.name.split(".")))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(package):
                        raise ValueError(f"relative import beyond package in {archive_path}")
                    base = package[: len(package) - node.level + 1]
                else:
                    base = ()
                module = base + tuple(node.module.split(".")) if node.module else base
                add_module(module)
                for alias in node.names:
                    if alias.name != "*":
                        add_module(module + (alias.name,))
    return sources


def reduced_function_sources(source: Callable[..., Any], include_modules: tuple[str, ...] = ()) -> dict[str, bytes]:
    """Select the function and same-file definitions it reads, then follow local imports."""
    if source.__qualname__ != source.__name__:
        raise ValueError("AST packaging requires a module-level function")
    source_file_name = inspect.getsourcefile(source)
    if source_file_name is None:
        raise ValueError(f"cannot find source for {source.__name__}")
    source_file = Path(source_file_name).resolve()
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    definitions = _definitions(tree)
    root = definitions.get(source.__name__)
    if not isinstance(root, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError(f"cannot find module-level function {source.__name__!r}")
    if len(root.decorator_list) != 1:
        raise ValueError("AST packaging supports only its own decorator on the target function")

    selected_ids = set()
    visited = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        node = definitions[name]
        selected_ids.add(id(node))
        for dependency in sorted(_read_globals(node) & definitions.keys()):
            visit(dependency)

    visit(source.__name__)
    selected = [copy.deepcopy(node) for node in tree.body if id(node) in selected_ids]
    for node in selected:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == source.__name__:
            node.decorator_list = []

    reduced_source = ast.unparse(ast.Module(body=selected, type_ignores=[]))
    project_root, package = _source_package(source_file)
    entry_path = Path(*package, source_file.name)
    return _collect_local_sources(project_root, entry_path, reduced_source, include_modules)


def sources_digest(sources: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(sources.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
