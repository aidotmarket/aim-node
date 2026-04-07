from __future__ import annotations

import click


@click.group()
def main() -> None:
    """AIM node CLI."""


@main.command("version")
def version() -> None:
    """Print the package version."""
    from aim_node import __version__

    click.echo(__version__)
