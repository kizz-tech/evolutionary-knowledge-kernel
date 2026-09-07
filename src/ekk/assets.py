"""Locate exact release resources in editable checkouts and installed wheels."""
from importlib.resources import files
from pathlib import Path


def _directory(package, source_relative, anchor):
    try:
        return Path(files(package).joinpath(anchor)).parent
    except ModuleNotFoundError:
        # Plain source execution before installation uses the canonical files.
        candidate = Path(__file__).resolve().parents[2] / source_relative
        if not candidate.is_dir():
            raise FileNotFoundError('Missing EKK release resources: ' + source_relative)
        return candidate


def schema_directory():
    return _directory('ekk._schemas', 'spec/schemas', 'record.schema.json')


def pack_directory():
    return _directory('ekk._packs', 'packs', 'base')
