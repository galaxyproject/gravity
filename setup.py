#!/usr/bin/env python
# -*- coding: utf-8 -*-


from os.path import join
from setuptools import setup, find_packages


with open('README.rst') as file:
    long_description = file.read()

long_description += '\n\n'
with open('HISTORY.rst') as file:
    long_description += file.read()

execfile(join('gravity', '__init__.py'))

setup(
    name = 'gravity',
    version = __version__,
    packages = find_packages(),
    description = 'Command-line utilities to assist in managing Galaxy servers',
    long_description = long_description,
    url = 'https://github.com/galaxyproject/gravity',
    author = 'The Galaxy Team',
    author_email = 'team@galaxyproject.org',
    license = 'MIT',
    keywords = 'gravity galaxy',
    install_requires = [
        'Click',
        'supervisor',
        'setproctitle',
        'virtualenv'
    ],
    entry_points = {
        'console_scripts': [
            'galaxy = gravity.cli:galaxy'
        ]
    },
    classifiers = [
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7'
    ],
    zip_safe = False
)
