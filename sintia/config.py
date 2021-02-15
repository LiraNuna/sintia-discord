from __future__ import annotations

from configparser import ConfigParser
from configparser import SectionProxy

from sintia.util import memoize


@memoize
def get_config():
    config = ConfigParser()
    config.read('config.ini')

    return config


@memoize
def get_config_section(section_name: str) -> SectionProxy:
    config = get_config()
    return config[section_name]
