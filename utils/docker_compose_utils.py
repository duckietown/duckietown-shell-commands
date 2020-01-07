import os
import re
import yaml
import copy


ENV_VAR_REGEX = '(\$\{([^:\-\?]+)(:?[-\?]?([^\}]*))\})'

def parse_compose_file(filepath, env={}):
    # merge os.environ with the given environment
    _env = copy.copy(os.environ)
    _env.update(env)
    # load yaml file
    yaml_content = _load_yaml(filepath)
    # fix env vars
    yaml_content = _resolve_variables(yaml_content, _env)
    # return yaml
    return yaml_content

def _resolve_variables(obj, env):
    if isinstance(obj, str):
        matches = list(re.finditer(ENV_VAR_REGEX, obj))
        if not matches:
            return obj
        i = 0
        res = ""
        for match in matches:
            if len(match.group(3)):
                env = copy.copy(env)
                env.update({match.group(2): match.group(4)} if len(match.group(4)) else {})
            res += \
                obj[i:match.start(1)] + \
                ('{' + match.group(2) + '}').format(**env)
            i = match.end(1)
        res += obj[i:]
        return res
    if isinstance(obj, list):
        return list(map(lambda e: _resolve_variables(e, env), obj))
    if isinstance(obj, dict):
        return {key: _resolve_variables(value, env) for key, value in obj.items()}
    return obj

def _load_yaml(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError('The file "{filepath}" does not exist.')
    with open(filepath, 'r') as fin:
        return yaml.load(fin.read())
