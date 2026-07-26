from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from quantumd.cli import cli
from quantumd.project_init import initialize_project


def test_initialize_project_creates_starter(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "governed-demo"

    created = initialize_project(
        destination,
        project_name="Governed Bell Demo",
    )

    assert created
    assert (destination / "experiment.yaml").is_file()
    assert (destination / "src" / "experiment.py").is_file()
    assert (destination / "data" / "dataset.csv").is_file()
    assert (destination / "README.md").is_file()
    assert (destination / ".gitignore").is_file()
    assert (destination / "evidence" / ".gitkeep").is_file()


def test_initialize_project_refuses_overwrite(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "existing-project"

    initialize_project(destination)

    try:
        initialize_project(destination)
    except FileExistsError as exc:
        assert "--force" in str(exc)
    else:
        raise AssertionError("Expected overwrite rejection.")


def test_initialize_project_force_overwrites(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "force-project"

    initialize_project(destination)

    experiment = destination / "src" / "experiment.py"
    experiment.write_text(
        "# unauthorized replacement\n",
        encoding="utf-8",
    )

    initialize_project(
        destination,
        force=True,
    )

    contents = experiment.read_text(encoding="utf-8")
    assert "unauthorized replacement" not in contents


def test_cli_init_command(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    destination = tmp_path / "cli-demo"

    result = runner.invoke(
        cli,
        [
            "init",
            str(destination),
            "--name",
            "CLI Governed Demo",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (
        "Simulator-first governed project initialized"
        in result.output
    )
    assert (destination / "experiment.yaml").exists()
    assert (destination / "src" / "experiment.py").exists()


def test_cli_init_rejects_existing_project(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    destination = tmp_path / "duplicate-demo"

    first = runner.invoke(
        cli,
        ["init", str(destination)],
    )

    second = runner.invoke(
        cli,
        ["init", str(destination)],
    )

    assert first.exit_code == 0, first.output
    assert second.exit_code != 0
    assert "--force" in second.output
