"""Experimental AST-selected source mounts for file-based Modal functions."""

import json
from pathlib import Path
from typing import Any, Callable

from ..image import Image
from ._ast_packaging import reduced_function_sources, sources_digest


def ast_function(
    app: Any,
    *,
    cache_dir: str | Path,
    include_modules: tuple[str, ...] = (),
    **function_options: Any,
) -> Callable[[Callable[..., Any]], Any]:
    """Register a simple Modal function from a reduced, dependency-aware source tree."""
    if "image" in function_options or "include_source" in function_options:
        raise ValueError("the experimental AST decorator manages image and include_source itself")
    if isinstance(include_modules, str):
        raise TypeError("include_modules must be a tuple of module names")
    options_json = json.dumps(function_options, sort_keys=True, separators=(",", ":"))

    def register(source: Callable[..., Any]) -> Any:
        sources = reduced_function_sources(source, tuple(include_modules))
        digest = sources_digest(sources)
        artifact_root = Path(cache_dir).resolve() / f"{source.__module__}-{source.__name__}-{digest}"
        for name, content in sources.items():
            output = artifact_root / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)

        image = Image.debian_slim().add_local_dir(artifact_root, "/root")
        function = app.function(image=image, include_source=False, **function_options)(source)
        entries = getattr(app, "_experimental_ast_fingerprints", None)
        if entries is None:
            entries = app._experimental_ast_fingerprints = {}
        entries[source.__name__] = {"artifact": digest, "options": options_json}
        return function

    return register
