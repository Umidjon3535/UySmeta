#!/usr/bin/env python
"""Django boshqaruv buyruqlari: runserver, migrate, test, seed, bot_dev ..."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
