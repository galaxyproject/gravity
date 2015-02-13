#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

with open('README.rst') as file:
    long_description = file.read()

long_description += '\n\n'
with open('HISTORY.rst') as file:
    long_description += file.read()


setup(
    name = 'gravity',
    version = '0.8.1',
    packages = find_packages(),
    description = 'Manage Galaxy servers',
    long_description = long_description,
    url = 'https://github.com/galaxyproject/gravity',
    author = 'The Galaxy Team',
    author_email = 'team@galaxyproject.org',
    license = 'MIT',
    keywords = 'gravity galaxy',
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
    },
    classifiers = [
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7'
    ]
)
