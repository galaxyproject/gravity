from setuptools import setup, find_packages

setup(
    name = 'gravity',
    version = '0.8',
    packages = find_packages(),
    description = 'Manage Galaxy servers',
    url = 'https://github.com/galaxyproject/gravity',
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
            'galaxyadm = gravity.cli:galaxyadm',
            'galaxycfg = gravity.cli:galaxycfg'
        ]
    }
)
