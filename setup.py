#! /usr/bin/env python2.7
# -*- coding: latin-1 -*-

from distutils.core import setup

setup(
    name             = "HomestackDatabases",
    packages         = ['hsdb'],
    version          = '0.0.8',
    description      = 'Homestack Database Library',
    author           = 'Pat Litke',
    author_email     = 'litke.p+gh@arcti.cc',
    url              = 'https://github.com/geudrik/homestack-db-library',
    classifiers      = ['Development Status :: 4 - Beta'],
    install_requires = ['sqlalchemy>=1.1.3', 'argon2>=0.1.10']
)

