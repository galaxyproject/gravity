from gravity import (
    config_manager,
    process_manager,
)


def test_register(galaxy_root_dir, state_dir):
    config = galaxy_root_dir / 'config' / 'galaxy.yml.sample'
    with config_manager.config_manager(state_dir=state_dir) as cm:
        cm.add([str(config)])


def test_update(galaxy_root_dir, state_dir):
    config = galaxy_root_dir / 'config' / 'galaxy.yml.sample'
    with config_manager.config_manager(state_dir=state_dir) as cm:
        cm.add([str(config)])
    with process_manager.process_manager(state_dir=state_dir) as pm:
        pm.update()


def test_deregister(galaxy_root_dir, state_dir):
    config = galaxy_root_dir / 'config' / 'galaxy.yml.sample'
    test_register(galaxy_root_dir, state_dir)
    with config_manager.config_manager(state_dir=state_dir) as cm:
        cm.remove([str(config)])
