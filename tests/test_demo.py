from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from quantumd import demo


def _create_artifacts(project: Path) -> None:
    execution_dir = (
        project
        / "evidence"
        / "executions"
        / "QEXEC-20260726-test"
    )
    execution_dir.mkdir(parents=True, exist_ok=True)
    (project / "evidence" / "public-key.pem").write_text(
        "test-public-key\n",
        encoding="utf-8",
    )
    (execution_dir / "results.json").write_text(
        json.dumps({"00": 4, "11": 4}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    (execution_dir / "receipt.json").write_text(
        json.dumps(
            {
                "execution_id": "QEXEC-20260726-test",
                "integrity": {
                    "signed": True,
                    "signature_status": "KMS_SIGNED",
                },
                "results": {"artifact": "results.json"},
                "target": {
                    "provider": "local",
                    "backend": "aer-simulator",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_tamper_and_restore_are_exact(tmp_path: Path) -> None:
    result_path = tmp_path / "results.json"
    original = (
        json.dumps({"00": 4, "11": 4}, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    result_path.write_bytes(original)
    saved = demo._tamper_result(result_path)
    assert saved == original
    assert result_path.read_bytes() != original
    demo._restore_result(result_path, saved)
    assert result_path.read_bytes() == original


def test_demo_command_completes(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "demo"
    monkeypatch.setattr(
        demo.tempfile,
        "mkdtemp",
        lambda prefix: str(project),
    )

    def fake_initialize(destination, *, project_name=None, force=False):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        _create_artifacts(destination)
        return []

    monkeypatch.setattr(demo, "initialize_project", fake_initialize)
    chain_calls = {"count": 0}

    def fake_run(arguments, *, cwd):
        command = tuple(arguments)
        if command[0] == "verify":
            output, code = "[STATUS] VERIFIED\n", 0
        elif command[0] == "run":
            output, code = (
                "[STATUS] EXECUTION COMPLETED AND ATTESTED\n",
                0,
            )
        else:
            chain_calls["count"] += 1
            if chain_calls["count"] == 2:
                output, code = (
                    "[STATUS] CHAIN VERIFICATION DENIED\n",
                    1,
                )
            else:
                output, code = (
                    "[STATUS] COMPLETE EVIDENCE CHAIN VERIFIED\n"
                    "IBM contacted:   False\n"
                    "KMS contacted:   False\n"
                    "Hardware action: None\n",
                    0,
                )
        return demo.CommandResult(command, code, output)

    monkeypatch.setattr(demo, "_run_quantumd", fake_run)
    result = CliRunner().invoke(
        demo.demo_command,
        ["--keep", "--shots", "8"],
    )
    assert result.exit_code == 0, result.output
    assert "GOVERNED DEMONSTRATION COMPLETE" in result.output
    assert "Adversarial result tampering" in result.output
    assert "DENIED" in result.output
