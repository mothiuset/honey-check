"""Punto de entrada: `python -m honey_check` y el ejecutable portable."""

import sys

from honey_check.app import main

if __name__ == "__main__":
    sys.exit(main())
