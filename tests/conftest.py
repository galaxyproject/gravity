import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

TEST_DIR = Path(os.path.dirname(__file__))


@pytest.fixture(scope='session')
def galaxy_git_dir():
    galaxy_dir = TEST_DIR / 'galaxy.git'
    if not galaxy_dir.exists():
        subprocess.run(['git', 'clone', '--bare', '--depth=1', 'https://github.com/galaxyproject/galaxy'], cwd=TEST_DIR)
    yield galaxy_dir


@pytest.fixture(scope='session')
def galaxy_root_dir(galaxy_git_dir, tmpdir_factory):
    tmpdir = tmpdir_factory.mktemp('galaxy-worktree')
    subprocess.run(['git', 'worktree', 'add', '-d', str(tmpdir)], cwd=str(galaxy_git_dir))
    return tmpdir


@pytest.fixture()
def state_dir():
    directory = tempfile.mkdtemp()
    try:
        yield directory
    finally:
        shutil.rmtree(directory)
