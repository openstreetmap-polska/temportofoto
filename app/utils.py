from functools import lru_cache
from pathlib import Path
import tomllib


@lru_cache
def get_version_from_pyproject_file() -> str:
    pyproject_toml_file = Path(__file__).parent.parent / "pyproject.toml"
    with pyproject_toml_file.open(mode="rb") as fp:
        data = tomllib.load(fp)
        return data["project"]["version"]
