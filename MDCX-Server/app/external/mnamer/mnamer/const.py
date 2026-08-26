"""Shared constant definitions."""

import datetime as dt
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from platform import platform, python_version
from sys import argv, gettrace, version_info

VERSION: str

try:
    from mnamer.__version__ import (
        __version__ as VERSION,  # type: ignore  # pyright: ignore
    )
except ModuleNotFoundError:
    from setuptools_scm import get_version  # type: ignore

    VERSION = get_version(root="..", relative_to=__file__, local_scheme="dirty-tag")  # pyright: ignore
try:
    appdirs_version = pkg_version("appdirs")
except PackageNotFoundError:
    appdirs_version = "N/A"

try:
    from appdirs import user_cache_dir

    cache_dir = user_cache_dir()
except ModuleNotFoundError:
    cache_dir = "N/A"

try:
    guessit_version = pkg_version("guessit")
except PackageNotFoundError:
    guessit_version = "N/A"

try:
    requests_version = pkg_version("requests")
except PackageNotFoundError:
    requests_version = "N/A"

try:
    requests_cache_version = pkg_version("requests_cache")
except PackageNotFoundError:
    requests_cache_version = "N/A"

try:
    teletype_version = pkg_version("teletype")
except PackageNotFoundError:
    teletype_version = "N/A"


CACHE_PATH = Path(
    cache_dir, f"mnamer-py{version_info.major}.{version_info.minor}.sqlite"
).absolute()

CURRENT_YEAR = dt.datetime.now().year
DEPRECATED = {"no_replace", "replacements"}
IS_DEBUG = gettrace() is not None
SUBTITLE_CONTAINERS = [".srt", ".idx", ".sub"]

SYSTEM = {
    "date": dt.date.today(),
    "platform": platform(),
    "arguments": argv[1:],
    "cache location": CACHE_PATH,
    "python version": python_version(),
    "mnamer version": VERSION,
    "appdirs version": appdirs_version,
    "guessit version": guessit_version,
    "requests version": requests_version,
    "requests cache version": requests_cache_version,
    "teletype version": teletype_version,
}

USAGE = "USAGE: mnamer [preferences] [directives] target [targets ...]"
