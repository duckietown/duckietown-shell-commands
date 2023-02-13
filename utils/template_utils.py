import json
import os
import re
from string import Template
from typing import List

from utils.exceptions import InvalidUserInput


class DTTemplate(Template):
    """Updates string.Template to handle .dtproject placeholder format -> <REPLACEMENT_HERE>"""
    delimiter = '<'
    idpattern = r'(?a:[_a-z][_a-z0-9]*)'
    pattern = fr"""
                {delimiter}(?:
                  (?P<escaped>>)                  |   # Escape sequence of two delimiters
                  (?P<named>{idpattern})>         |   # delimiter and a Python identifier
                  {{(?P<braced>{idpattern})}}>    |   # delimiter and a braced identifier
                  (?P<invalid>)                     # Other ill-formed delimiter exprs
                )
                """


class SafeDTTemplate(Template):
    """Updates DTTemplate to only allow safe path string format -> this_is-safe-1"""
    delimiter = '<'
    idpattern = r'(?a:[_a-z][_a-z0-9]*)'
    pattern = fr"""
                {delimiter}(?:
                  (?P<escaped>>)                  |   # Escape sequence of two delimiters
                  (?P<named>{idpattern})>         |   # delimiter and a Python identifier
                  {{(?P<braced>{idpattern})}}>    |   # delimiter and a braced identifier
                  (?P<invalid>)                     # Other ill-formed delimiter exprs
                )
                """

    def substitute(self, *args, **kws):
        if all([re.match("[^A-Z\s]*$", repl) for repl in list(kws.values())]):
            return super(SafeDTTemplate, self).substitute(*args, **kws)
        else:
            raise InvalidUserInput("The input value does not follow the safe path format: `this_1-is-safe`")


def fill_template_file(template_fpath: str, value_map: dict, dest_fpath: str = None):
    """Fill in template file using Duckietown template format and overwrite (optional new file location)"""
    # Open the template as lines
    if not os.path.exists(template_fpath):
        raise FileNotFoundError(template_fpath)
    with open(template_fpath, "rt") as template:
        lines: List[str] = template.readlines()

    # Find all placeholders and fill with DTTemplate
    filled = [DTTemplate(line).safe_substitute(value_map) for line in lines]
    if not dest_fpath:
        dest_fpath = template_fpath
    with open(dest_fpath, "w") as out:
        out.writelines(filled)


def fill_template_json(json_values: dict, user_value_map: dict) -> dict:
    """Fills a dict template loaded from json with updated values using Template format"""
    string_values: str = json.dumps(json_values)
    filled_string: str = Template(string_values).safe_substitute(user_value_map)
    return json.loads(filled_string)
