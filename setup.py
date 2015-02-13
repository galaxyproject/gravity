from setuptools import setup, find_packages

setup(
    name = 'galaxyadmin',
    version = '0.7',
    packages = find_packages(),
    description = 'Manage Galaxy servers',
    url = 'https://github.com/galaxyproject/galaxyadmin',
    author = 'The Galaxy Team',
    author_email = 'team@galaxyproject.org',
    license='MIT',

    install_requires = [
        'supervisor',
        'setproctitle',
        'virtualenv'
    ],

    entry_points = {
        'console_scripts': [
            'galaxyadm = galaxyadmin.cli:galaxyadm',
            'galaxycfg = galaxyadmin.cli:galaxycfg'
        ]
    }
)
