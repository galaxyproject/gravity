import sys
import traceback

import click


DEBUG = False


def debug(message, *args):
    if args:
        message = message % args
    if DEBUG:
        click.echo(message)


def info(message, *args):
    if args:
        message = message % args
    click.echo(click.style(message, bold=True, fg="green"))


def error(message, *args):
    if args:
        message = message % args
    if DEBUG and sys.exc_info()[0] is not None:
        click.echo(traceback.format_exc(), nl=False)
    click.echo(click.style(message, bold=True, fg="red"), err=True)


def warn(message, *args):
    if args:
        message = message % args
    click.echo(click.style(message, fg="red"), err=True)


def exception(message):
    raise click.ClickException(click.style(message, bold=True, fg="red"))
