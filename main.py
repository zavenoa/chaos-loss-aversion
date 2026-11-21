"""Chaos Loss Aversion. Windows-only visual alert utility.

Entry point kept at main.py so build_windows.ps1 is unchanged.
Application code lives in the ``cla`` package.
"""
import sys

from cla.ui.app import run

if __name__ == '__main__':
    sys.exit(run())
