import json
from importlib.resources import files


def test_manifest_schema_is_packaged() -> None:
    schema = files("quantumd.schemas").joinpath(
        "experiment-v0.1.schema.json"
    )

    assert schema.is_file()

    payload = json.loads(
        schema.read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
