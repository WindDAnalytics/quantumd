"""Non-destructive adversarial hardening tests for a completed evidence chain."""

from __future__ import annotations

import concurrent.futures
import copy
import json
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import click

from quantumd.chain import _load_chain, _verify_chain
from quantumd.submission import SubmissionError, write_json


class AdversarialTestError(RuntimeError):
    """Raised when a security test does not produce the required outcome."""


def _write_pretty(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(value, dict):
        raise AdversarialTestError(
            f"Expected JSON object: {path}"
        )

    return value


def _flip_byte(path: Path) -> None:
    data = bytearray(path.read_bytes())

    if not data:
        raise AdversarialTestError(
            f"Cannot mutate empty artifact: {path}"
        )

    index = len(data) // 2
    data[index] ^= 0x01
    path.write_bytes(bytes(data))


def _sandbox(
    source_project: Path,
    temporary_root: Path,
    name: str,
) -> Path:
    destination = temporary_root / name
    destination.mkdir(parents=True, exist_ok=False)

    source_evidence = source_project / "evidence"
    destination_evidence = destination / "evidence"

    if not source_evidence.is_dir():
        raise AdversarialTestError(
            f"Evidence directory not found: {source_evidence}"
        )

    shutil.copytree(
        source_evidence,
        destination_evidence,
        copy_function=shutil.copy2,
    )

    # Authentic evidence artifacts are intentionally read-only. copy2()
    # preserves those modes, so make only the disposable sandbox copy
    # writable before applying adversarial mutations.
    destination_evidence.chmod(0o755)

    for copied_path in destination_evidence.rglob("*"):
        if copied_path.is_dir():
            copied_path.chmod(0o755)
        elif copied_path.is_file():
            copied_path.chmod(0o644)

    return destination


def _expect_chain_denial(
    project: Path,
    execution_id: str,
) -> str:
    try:
        context = _load_chain(
            project,
            execution_id,
            None,
            False,
        )
        _verify_chain(context)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"

    raise AdversarialTestError(
        "Mutated chain was incorrectly accepted."
    )


def _mutate_plan_shots(
    project: Path,
    ids: dict[str, str],
) -> None:
    path = (
        project
        / "evidence"
        / "plans"
        / ids["plan_id"]
        / "plan.json"
    )
    value = _read_object(path)
    value["execution_parameters"]["shots"] += 1
    _write_pretty(path, value)


def _mutate_isa_byte(
    project: Path,
    ids: dict[str, str],
) -> None:
    plan_path = (
        project
        / "evidence"
        / "plans"
        / ids["plan_id"]
        / "plan.json"
    )
    plan = _read_object(plan_path)
    artifact = plan["workload"]["isa_circuit"]["artifact"]

    _flip_byte(plan_path.parent / artifact)


def _mutate_approval_shots(
    project: Path,
    ids: dict[str, str],
) -> None:
    path = (
        project
        / "evidence"
        / "approvals"
        / ids["approval_id"]
        / "approval.json"
    )
    value = _read_object(path)
    value["binding"]["shots"] += 1
    _write_pretty(path, value)


def _mutate_submission_job(
    project: Path,
    ids: dict[str, str],
) -> None:
    path = (
        project
        / "evidence"
        / "submissions"
        / ids["submission_id"]
        / "submission.json"
    )
    value = _read_object(path)
    value["ibm"]["job_id"] = "forged-job-id"
    _write_pretty(path, value)


def _mutate_counts(
    project: Path,
    ids: dict[str, str],
) -> None:
    receipt_path = (
        project
        / "evidence"
        / "executions"
        / ids["execution_id"]
        / "receipt.json"
    )
    receipt = _read_object(receipt_path)
    artifact = receipt["results"]["counts"]["artifact"]
    path = receipt_path.parent / artifact
    value = _read_object(path)
    counts = value["counts"]
    first_key = sorted(counts)[0]
    counts[first_key] = int(counts[first_key]) + 1
    value["observed_shots"] = int(
        value["observed_shots"]
    ) + 1
    _write_pretty(path, value)


def _mutate_receipt_status(
    project: Path,
    ids: dict[str, str],
) -> None:
    path = (
        project
        / "evidence"
        / "executions"
        / ids["execution_id"]
        / "receipt.json"
    )
    value = _read_object(path)
    value["status"] = "EXECUTION_COMPLETED_FORGED"
    _write_pretty(path, value)


def _delete_metadata(
    project: Path,
    ids: dict[str, str],
) -> None:
    receipt_path = (
        project
        / "evidence"
        / "executions"
        / ids["execution_id"]
        / "receipt.json"
    )
    receipt = _read_object(receipt_path)
    artifact = receipt["ibm"]["metadata_artifact"][
        "artifact"
    ]
    (receipt_path.parent / artifact).unlink()


def _truncate_receipt(
    project: Path,
    ids: dict[str, str],
) -> None:
    path = (
        project
        / "evidence"
        / "executions"
        / ids["execution_id"]
        / "receipt.json"
    )
    raw = path.read_bytes()
    path.write_bytes(raw[: max(1, len(raw) // 3)])


def _corrupt_public_key(
    project: Path,
    ids: dict[str, str],
) -> None:
    path = (
        project
        / "evidence"
        / "approvals"
        / ids["approval_id"]
        / "public-key.pem"
    )
    data = path.read_text(encoding="utf-8")
    path.write_text(
        data.replace(
            "BEGIN PUBLIC KEY",
            "BEGIN CORRUPTED KEY",
            1,
        ),
        encoding="utf-8",
    )


def _replay_attempt(
    project: Path,
    ids: dict[str, str],
) -> str:
    consumption = (
        project
        / "evidence"
        / "approvals"
        / ids["approval_id"]
        / "consumption.json"
    )

    if not consumption.exists():
        raise AdversarialTestError(
            "Authentic consumed approval has no consumption record."
        )

    try:
        write_json(
            consumption,
            {
                "status": "CLAIMED_AGAIN",
                "probe": True,
            },
            exclusive=True,
        )
    except SubmissionError as exc:
        return f"SubmissionError: {exc}"

    raise AdversarialTestError(
        "Consumed approval was incorrectly claimable again."
    )


def _uncertain_retry_attempt(
    temporary_root: Path,
) -> str:
    path = temporary_root / "uncertain-consumption.json"

    _write_pretty(
        path,
        {
            "status": "SUBMISSION_UNCERTAIN",
            "retry_permitted": False,
        },
    )

    try:
        write_json(
            path,
            {
                "status": "CLAIMED",
                "probe": True,
            },
            exclusive=True,
        )
    except SubmissionError as exc:
        return f"SubmissionError: {exc}"

    raise AdversarialTestError(
        "SUBMISSION_UNCERTAIN state was incorrectly reusable."
    )


def _concurrent_claim_test(
    temporary_root: Path,
) -> str:
    path = temporary_root / "concurrent-consumption.json"

    def attempt(number: int) -> tuple[int, str]:
        try:
            write_json(
                path,
                {
                    "status": "CLAIMED",
                    "contender": number,
                },
                exclusive=True,
            )
        except SubmissionError:
            return number, "DENIED"
        return number, "CLAIMED"

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=2
    ) as executor:
        results = list(
            executor.map(
                attempt,
                (1, 2),
            )
        )

    claimed = [
        number
        for number, outcome in results
        if outcome == "CLAIMED"
    ]
    denied = [
        number
        for number, outcome in results
        if outcome == "DENIED"
    ]

    if len(claimed) != 1 or len(denied) != 1:
        raise AdversarialTestError(
            "Concurrent single-use claim invariant failed: "
            f"{results}"
        )

    return (
        f"contender {claimed[0]} claimed; "
        f"contender {denied[0]} denied"
    )


MUTATION_CASES: list[
    tuple[
        str,
        str,
        Callable[[Path, dict[str, str]], None],
    ]
] = [
    (
        "plan-field-mutation",
        "Changing the signed QPLAN shot count",
        _mutate_plan_shots,
    ),
    (
        "isa-byte-mutation",
        "Flipping one byte in the approved ISA QPY",
        _mutate_isa_byte,
    ),
    (
        "approval-binding-mutation",
        "Changing the QAPPROVAL shot binding",
        _mutate_approval_shots,
    ),
    (
        "ibm-job-substitution",
        "Replacing the IBM job ID in QSUB",
        _mutate_submission_job,
    ),
    (
        "counts-artifact-mutation",
        "Changing one observed result count",
        _mutate_counts,
    ),
    (
        "qexec-receipt-mutation",
        "Changing the signed QEXEC status",
        _mutate_receipt_status,
    ),
    (
        "metadata-deletion",
        "Deleting the IBM job metadata artifact",
        _delete_metadata,
    ),
    (
        "partial-write-simulation",
        "Truncating the QEXEC receipt",
        _truncate_receipt,
    ),
    (
        "public-key-corruption",
        "Corrupting the cached public verification key",
        _corrupt_public_key,
    ),
]


@click.command("adversarial-test")
@click.argument(
    "project",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
        path_type=Path,
    ),
)
@click.option(
    "--execution-id",
    required=True,
    help="Completed authentic QEXEC chain to attack in copies.",
)
@click.option(
    "--keep-sandboxes",
    is_flag=True,
    help="Retain mutated temporary evidence copies for inspection.",
)
def adversarial_test_command(
    project: Path,
    execution_id: str,
    keep_sandboxes: bool,
) -> None:
    """Attack temporary evidence copies and require fail-closed denial."""

    temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    try:
        project = project.resolve()

        authentic = _load_chain(
            project,
            execution_id,
            None,
            False,
        )
        authentic_checks = _verify_chain(authentic)

        ids = {
            "execution_id": authentic["execution_id"],
            "submission_id": authentic["submission_id"],
            "approval_id": authentic["approval_id"],
            "plan_id": authentic["plan_id"],
        }

        if keep_sandboxes:
            temporary_root = Path(
                tempfile.mkdtemp(
                    prefix="quantumd-adversarial-"
                )
            )
        else:
            temporary_directory = tempfile.TemporaryDirectory(
                prefix="quantumd-adversarial-"
            )
            temporary_root = Path(
                temporary_directory.name
            )

        print("=== QuantumD Adversarial Chain Hardening ===")
        print(f"Authentic QEXEC:      {execution_id}")
        print(f"Temporary root:       {temporary_root}")
        print("IBM contacted:        False")
        print("KMS contacted:        False")
        print("Authentic evidence:   Read-only")
        print()

        click.secho(
            "[BASELINE] Authentic chain verification........ PASS",
            fg="green",
        )

        results: list[dict[str, Any]] = []

        for number, (
            slug,
            description,
            mutation,
        ) in enumerate(MUTATION_CASES, start=1):
            sandbox = _sandbox(
                project,
                temporary_root,
                f"{number:02d}-{slug}",
            )

            mutation(sandbox, ids)
            denial = _expect_chain_denial(
                sandbox,
                execution_id,
            )

            results.append(
                {
                    "case": slug,
                    "description": description,
                    "outcome": "DENIED_AS_REQUIRED",
                    "denial": denial,
                    "sandbox": str(sandbox),
                }
            )

            click.secho(
                f"[ATTACK {number:02d}] "
                f"{description:.<48} BLOCKED",
                fg="green",
            )

        replay_project = _sandbox(
            project,
            temporary_root,
            "10-approval-replay",
        )
        replay_denial = _replay_attempt(
            replay_project,
            ids,
        )
        results.append(
            {
                "case": "approval-replay",
                "description": (
                    "Attempting to claim a consumed approval again"
                ),
                "outcome": "DENIED_AS_REQUIRED",
                "denial": replay_denial,
                "sandbox": str(replay_project),
            }
        )
        click.secho(
            "[ATTACK 10] Attempting consumed approval replay"
            "........... BLOCKED",
            fg="green",
        )

        uncertain_denial = _uncertain_retry_attempt(
            temporary_root,
        )
        results.append(
            {
                "case": "uncertain-retry",
                "description": (
                    "Retrying a SUBMISSION_UNCERTAIN approval"
                ),
                "outcome": "DENIED_AS_REQUIRED",
                "denial": uncertain_denial,
            }
        )
        click.secho(
            "[ATTACK 11] Retrying SUBMISSION_UNCERTAIN state"
            "........... BLOCKED",
            fg="green",
        )

        concurrency = _concurrent_claim_test(
            temporary_root,
        )
        results.append(
            {
                "case": "concurrent-claim",
                "description": (
                    "Two concurrent single-use approval claims"
                ),
                "outcome": "EXACTLY_ONE_CLAIMED",
                "detail": concurrency,
            }
        )
        click.secho(
            "[ATTACK 12] Concurrent approval claims"
            ".................... CONTAINED",
            fg="green",
        )

        authentic_after = _load_chain(
            project,
            execution_id,
            None,
            False,
        )
        after_checks = _verify_chain(
            authentic_after
        )

        if authentic_checks != after_checks:
            raise AdversarialTestError(
                "Authentic verification result changed "
                "after adversarial testing."
            )

        click.secho(
            "[BASELINE] Authentic chain still verifies........ PASS",
            fg="green",
        )

        created = datetime.now(timezone.utc)
        report_id = (
            f"QTEST-{created:%Y%m%d}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        report_dir = (
            project
            / "evidence"
            / "security-tests"
            / report_id
        )
        report_dir.mkdir(
            parents=True,
            exist_ok=False,
        )
        report_path = report_dir / "report.json"

        report = {
            "schema_version": (
                "quantumd.ai/adversarial-test/v0.1"
            ),
            "report_id": report_id,
            "created_at": created.isoformat(),
            "status": "ALL_ATTACKS_BLOCKED",
            "execution_id": ids["execution_id"],
            "submission_id": ids["submission_id"],
            "approval_id": ids["approval_id"],
            "plan_id": ids["plan_id"],
            "network_calls": {
                "ibm": False,
                "kms": False,
                "secret_manager": False,
            },
            "authentic_evidence_modified": False,
            "baseline_checks": authentic_checks,
            "attacks": results,
            "summary": {
                "mutation_attacks_blocked": len(
                    MUTATION_CASES
                ),
                "replay_attacks_blocked": 2,
                "concurrency_invariant_passed": True,
                "total_tests": len(results),
            },
        }

        _write_pretty(report_path, report)

        click.secho(
            "\n[STATUS] ADVERSARIAL HARDENING PASSED",
            fg="green",
            bold=True,
        )
        print(
            f"Attacks executed:     {len(results)}"
        )
        print(
            "Mutations accepted:   0"
        )
        print(
            "Replay accepted:      0"
        )
        print(
            "Concurrent winners:   1"
        )
        print(
            "Authentic chain:      VERIFIED"
        )
        print(
            f"Report:               {report_path}"
        )

        if keep_sandboxes:
            print(
                f"Sandboxes retained:   {temporary_root}"
            )
        else:
            print(
                "Sandboxes retained:   False"
            )

    except Exception as exc:
        click.secho(
            "\n[STATUS] ADVERSARIAL HARDENING FAILED",
            fg="red",
            bold=True,
        )
        print(
            f"  └─ {type(exc).__name__}: {exc}"
        )
        raise click.exceptions.Exit(1) from exc

    finally:
        if temporary_directory is not None:
            temporary_directory.cleanup()


adversarial_test = adversarial_test_command

