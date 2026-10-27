from pathlib import Path


def test_api_workspace_has_runtime_layout() -> None:
    workspace = Path(__file__).parents[1]
    assert (workspace / "app").is_dir()
    assert (workspace / "pyproject.toml").is_file()
