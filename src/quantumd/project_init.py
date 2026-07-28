from __future__ import annotations

import base64
import re
from pathlib import Path


_TEMPLATE_FILES: dict[str, str] = {'data/dataset.csv': 'ZmVhdHVyZV8xLGZlYXR1cmVfMixkaWFnbm9zaXMKMC4xLDAuMiwwCjAuOSwwLjgsMQowLjIsMC4xLDAKMC44LDAuOSwxCjAuMTUsMC4xNSwwCjAuODUsMC44NSwxCjAuMSwwLjMsMAowLjksMC43LDEK',
 'experiment.yaml': 'YXBpVmVyc2lvbjogcXVhbnR1bWQuYWkvdjAuMQpraW5kOiBRdWFudHVtRXhwZXJpbWVudAoKbWV0YWRhdGE6CiAgbmFtZTogYnJlYXN0LWNhbmNlci1xdWFudHVtLWtlcm5lbAogIG93bmVyOiBsb2NhbC11c2VyCiAgcHVycG9zZTogcmVzZWFyY2gKICBsYWJlbHM6CiAgICBkb21haW46IHF1YW50dW0tbWwKCmludGVudDoKICB0YXNrOiBiaW5hcnktY2xhc3NpZmljYXRpb24KICBoeXBvdGhlc2lzOiA+CiAgICBFdmFsdWF0ZSB3aGV0aGVyIHRoZSBkZWNsYXJlZCBxdWFudHVtIGtlcm5lbCBtZWV0cyB0aGUKICAgIHByZS1yZWdpc3RlcmVkIHV0aWxpdHkgdGhyZXNob2xkIHVuZGVyIG5vaXN5IHNpbXVsYXRpb24uCiAgZnJvemVuOiB0cnVlCgppbnB1dHM6CiAgZGF0YXNldDoKICAgIHBhdGg6IGRhdGEvZGF0YXNldC5jc3YKICAgIHNoYTI1NjogUkVRVUlSRUQKICB0YXJnZXRfY29sdW1uOiBkaWFnbm9zaXMKICB0cmFpbl90ZXN0X3NwbGl0OgogICAgdGVzdF9zaXplOiAwLjIwCiAgICByYW5kb21fc2VlZDogMTcyOQoKY29udHJhY3Q6CiAgbWluaW11bV90ZXN0X2FjY3VyYWN5OiAwLjc1CiAgbWF4aW11bV9hY2N1cmFjeV9kcm9wX25vaXN5OiAwLjEyCiAgcmVxdWlyZWRfb3V0cHV0X2xhYmVsczogWzAsIDFdCgppbXBsZW1lbnRhdGlvbjoKICBmcmFtZXdvcms6IHFpc2tpdAogIGVudHJ5cG9pbnQ6IHNyYy9leHBlcmltZW50LnB5CiAgY2lyY3VpdF9leHBvcnQ6IG9wZW5xYXNtMwoKdmVyaWZpY2F0aW9uOgogIHByb2ZpbGU6IHF1YW50dW1fbWxfc3RyaWN0CiAgcmVwYWlyX3BvbGljeToKICAgIGVuYWJsZWQ6IHRydWUKICAgIG1heGltdW1fYXR0ZW1wdHM6IDIKICAgIG1heV9jaGFuZ2U6CiAgICAgIC0gdHJhbnNwaWxlcl9vcHRpbWl6YXRpb24KICAgICAgLSBzaG90X2NvdW50CiAgICAgIC0gaW1wbGVtZW50YXRpb25fZGVmZWN0cwogICAgbWF5X25vdF9jaGFuZ2U6CiAgICAgIC0gZGF0YXNldF9zcGxpdAogICAgICAtIGFjY2VwdGFuY2VfdGhyZXNob2xkcwogICAgICAtIGNsYXNzaWNhbF9iYXNlbGluZXMKICAgICAgLSBkZWNsYXJlZF9oeXBvdGhlc2lzCgpjbGFzc2ljYWxfYmFzZWxpbmVzOgogIC0gYWxnb3JpdGhtOiByYmZfc3ZtCiAgICBwYXJhbWV0ZXJzOgogICAgICBDOiAxLjAKICAgICAgZ2FtbWE6IHNjYWxlCiAgLSBhbGdvcml0aG06IGxvZ2lzdGljX3JlZ3Jlc3Npb24KICAtIGFsZ29yaXRobTogcmFuZG9tX2ZvcmVzdAoKZXhlY3V0aW9uOgogIHByZWZlcnJlZF90YXJnZXQ6IG5vaXN5X3NpbXVsYXRvcgogIHBlcm1pdHRlZF90YXJnZXRzOgogICAgLSBpZGVhbF9zaW11bGF0b3IKICAgIC0gbm9pc3lfc2ltdWxhdG9yCiAgICAtIGlibV9xcHUKICBsaW1pdHM6CiAgICBtYXhpbXVtX3F1Yml0czogMTIKICAgIG1heGltdW1fdHJhbnNwaWxlZF9kZXB0aDogNTAwCiAgICBtYXhpbXVtX3Nob3RzOiAyMDAwMAogICAgbWF4aW11bV9xcHVfcnVudGltZV9zZWNvbmRzOiA2MAogICAgbWF4aW11bV9jb3N0X3VzZDogMTAuMDAKCnNlY3VyaXR5OgogIGNyZWRlbnRpYWxfYWNjZXNzOiBicm9rZXJlZAogIGFsbG93ZWRfcHJvdmlkZXJzOgogICAgLSBpYm1fcXVhbnR1bQogIGRhdGFfZWdyZXNzOiBwcm9oaWJpdGVkCiAgcmV0YWluX3Jhd19wcm92aWRlcl9wYXlsb2FkczogZmFsc2UKCmFwcHJvdmFsOgogIHFwdV9leGVjdXRpb246IGh1bWFuX3JlcXVpcmVkCgpldmlkZW5jZToKICBzaWduOiB0cnVlCiAgaW5jbHVkZV9zb3VyY2Vfc25hcHNob3Q6IHRydWUKICBpbmNsdWRlX2Vudmlyb25tZW50X2xvY2s6IHRydWUKICByZXBvcnRfZm9ybWF0czoKICAgIC0ganNvbgogICAgLSBodG1sCiAgICAtIHBkZgo=',
 'src/experiment.py': 'ZnJvbSBxaXNraXQgaW1wb3J0IFF1YW50dW1DaXJjdWl0CgpkZWYgZ2V0X2NpcmN1aXQoKToKICAgIHFjID0gUXVhbnR1bUNpcmN1aXQoMiwgMikKICAgIHFjLmgoMCkKICAgIHFjLmN4KDAsIDEpCiAgICBxYy5tZWFzdXJlKDAsIDApCiAgICBxYy5tZWFzdXJlKDEsIDEpCiAgICByZXR1cm4gcWMK'}

_TEXT_SUFFIXES = {
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".md",
    ".txt",
}

_TEXT_FILENAMES = {
    ".gitignore",
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    slug = re.sub(r"-+", "-", slug).strip("-_").lower()

    if not slug:
        raise ValueError("Project name must contain letters or numbers.")

    return slug


def _render_template(
    relative_path: str,
    data: bytes,
    *,
    display_name: str,
    slug: str,
) -> bytes:
    path = Path(relative_path)

    if (
        path.suffix.lower() not in _TEXT_SUFFIXES
        and path.name not in _TEXT_FILENAMES
    ):
        return data

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data

    python_slug = slug.replace("-", "_")

    replacements = {
        "QuantumD Quantum Kernel": f"QuantumD {display_name}",
        "Quantum Kernel": display_name,
        "quantum_kernel": python_slug,
        "quantum-kernel": slug,
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text.encode("utf-8")


def initialize_project(
    destination: str | Path,
    *,
    project_name: str | None = None,
    force: bool = False,
) -> list[Path]:
    destination_path = Path(destination).expanduser().resolve()

    display_name = (
        project_name.strip()
        if project_name and project_name.strip()
        else destination_path.name
    )

    if not display_name:
        display_name = "quantumd-project"

    slug = _slugify(display_name)

    planned_paths = set(_TEMPLATE_FILES)
    planned_paths.update(
        {
            "README.md",
            ".gitignore",
            "evidence/.gitkeep",
        }
    )

    conflicts = sorted(
        relative_path
        for relative_path in planned_paths
        if (destination_path / relative_path).exists()
    )

    if conflicts and not force:
        formatted = ", ".join(conflicts)
        raise FileExistsError(
            "Refusing to overwrite existing project files: "
            f"{formatted}. Use --force to replace them."
        )

    destination_path.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []

    for relative_path, encoded in sorted(_TEMPLATE_FILES.items()):
        output_path = destination_path / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        raw = base64.b64decode(encoded)
        rendered = _render_template(
            relative_path,
            raw,
            display_name=display_name,
            slug=slug,
        )

        output_path.write_bytes(rendered)
        created.append(output_path)

    readme_path = destination_path / "README.md"

    if "README.md" not in _TEMPLATE_FILES:
        readme_text = (
            f"# {display_name}\n\n"
            "This project was initialized by QuantumD.\n\n"
            "## Governed quickstart\n\n"
            "```bash\n"
            "quantumd verify .\n"
            "quantumd run . --target aer-simulator --latest\n"
            "quantumd verify-chain . --latest\n"
            "```\n\n"
            "QuantumD independently verifies, authorizes, executes,\n"
            "and attests this quantum workload.\n"
        )
        readme_path.write_text(readme_text, encoding="utf-8")
        created.append(readme_path)

    gitignore_path = destination_path / ".gitignore"

    if ".gitignore" not in _TEMPLATE_FILES:
        gitignore_text = (
            "__pycache__/\n"
            "*.py[cod]\n"
            ".venv/\n"
            ".env\n"
            ".pytest_cache/\n\n"
            ".quantumd/local-trust/\n\n"
            "evidence/*\n"
            "!evidence/.gitkeep\n"
        )
        gitignore_path.write_text(gitignore_text, encoding="utf-8")
        created.append(gitignore_path)

    evidence_keep = destination_path / "evidence" / ".gitkeep"
    evidence_keep.parent.mkdir(parents=True, exist_ok=True)
    evidence_keep.write_text("", encoding="utf-8")
    created.append(evidence_keep)

    return sorted(set(created))
