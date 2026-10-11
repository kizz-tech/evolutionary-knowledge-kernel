"""Private host directories for EKK configuration, runtime state and caches."""
import os
import sys
from pathlib import Path


def config_home():
    if os.environ.get('EKK_CONFIG_HOME'):
        return Path(os.environ['EKK_CONFIG_HOME']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/EKK/config'
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config')) / 'ekk'


def data_home():
    if os.environ.get('EKK_DATA_HOME'):
        return Path(os.environ['EKK_DATA_HOME']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/EKK/runtime'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share')) / 'ekk'


def cache_home():
    if os.environ.get('EKK_CACHE_HOME'):
        return Path(os.environ['EKK_CACHE_HOME']).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Caches/EKK'
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache')) / 'ekk'


def release_home():
    """The installer's release directory beside the data home; `cli/current` names the active release.

    Computed on every call, so a long-lived process follows the environment it is asked in.
    """
    return data_home().expanduser().resolve().parent / 'cli'
