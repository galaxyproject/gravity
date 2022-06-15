#!/usr/bin/env python
# -*- coding: utf-8 -*-
import ast
import os
import re

from setuptools import setup, find_packages


with open("README.rst") as file:
    long_description = file.read()

long_description += "\n\n"
with open("HISTORY.rst") as file:
    long_description += file.read()

with open(os.path.join("gravity", "__init__.py")) as f:
    init_contents = f.read()

    def get_var(var_name):
        pattern = re.compile(r"%s\s+=\s+(.*)" % var_name)
        match = pattern.search(init_contents).group(1)
        return str(ast.literal_eval(match))

    version = get_var("__version__")

setup(
    name="gravity",
    version=version,
    packages=find_packages(),
    description="Command-line utilities to assist in managing Galaxy servers",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    url="https://github.com/galaxyproject/gravity",
    author="The Galaxy Team",
    author_email="team@galaxyproject.org",
    license="MIT",
    keywords="gravity galaxy",
    python_requires=">=3.6",
    install_requires=["Click", "supervisor", "pyyaml", "ruamel.yaml", "pydantic", "jsonref"],
    entry_points={"console_scripts": [
        "galaxy = gravity.cli:galaxy",
        "galaxyctl = gravity.cli:galaxyctl",
    ]},
    classifiers=[
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    zip_safe=False,
)
