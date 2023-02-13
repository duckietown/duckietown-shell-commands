import re
from string import Template

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
