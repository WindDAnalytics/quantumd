from __future__ import annotations

import concurrent.futures
from pathlib import Path

import pytest

from quantumd.submission import SubmissionError, write_json


def test_exclusive_consumption_file_is_single_use(
    tmp_path: Path,
) -> None:
    path = tmp_path / "consumption.json"

    write_json(
        path,
        {"status": "CLAIMED", "contender": 1},
        exclusive=True,
    )

    with pytest.raises(SubmissionError):
        write_json(
            path,
            {"status": "CLAIMED", "contender": 2},
            exclusive=True,
        )


def test_two_concurrent_claims_have_one_winner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "consumption.json"

    def claim(contender: int) -> str:
        try:
            write_json(
                path,
                {
                    "status": "CLAIMED",
                    "contender": contender,
                },
                exclusive=True,
            )
        except SubmissionError:
            return "DENIED"
        return "CLAIMED"

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=2
    ) as executor:
        outcomes = list(
            executor.map(claim, (1, 2))
        )

    assert outcomes.count("CLAIMED") == 1
    assert outcomes.count("DENIED") == 1

