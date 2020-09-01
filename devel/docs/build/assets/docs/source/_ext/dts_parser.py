import importlib
import os
import sys
import io

from docutils import nodes
# from docutils.parsers.rst import Directive
from sphinx import addnodes
from sphinx.util.docutils import SphinxDirective
from sphinx.util.nodes import nested_parse_with_titles
from docutils.statemachine import StringList

import dt_shell as dts

# def flatten_list(l):
#     output = list()
#     for i in l:
#         if type(i) == list:
#             output.append(flatten_list(i))
#         else:
#             output.append(i)
#     return output


class DTS_Parser(SphinxDirective):

    # this enables content in the directive
    has_content = True

    def print_log(self, msg):
        print("[DTS PARSER] %s" % msg)

    def run(self):
        commands_version = self.content[0]

        self.print_log("Setting up a dts instance...")
        os.environ['DTSHELL_COMMANDS'] = '/commands'
        shell_config = dts.config.get_shell_config_default()
        self.print_log(f"Shell config: {shell_config}")
        # shell_config.duckietown_version = commands_version
        self.commands_info = dts.cli.get_local_commands_info()
        self.print_log(f"Commands info: {self.commands_info}")
        self.shell = dts.cli.DTShell(shell_config, self.commands_info)
        self.print_log("Shell set up.")

        sys.path.append('/')
        self.commands_module = importlib.import_module('commands')

        self.print_log("Going through the commands...")
        entries = list()

        for command, content in sorted(self.shell.commands.items(), key=lambda item: item[0]):
            entries.append(self.parse_a_command(command, content))

        return entries

    def parse_a_command(self, command, content, parents=[]):
        path_to_command = os.path.join(self.commands_info.commands_path, *parents, command)

        class_path_short = ' '.join(parents + [command])
        class_path = '.'.join(parents + [command, 'command', 'DTCommand'])

        node = nodes.section(ids=[f"dts_command_{class_path_short.replace(' ', '_')}"])
        node += nodes.title(class_path_short, class_path_short)
        # if an actual command:

        if os.path.exists(os.path.join(path_to_command, 'command.py')):
            self.print_log(f"Loading command class {class_path}")
            # addnodes.desc_name(text=class_path)

            cmd_class = dts.cli._load_class(class_path)
            self.print_log(f"Help string: {cmd_class.help}")

            node += nodes.paragraph(text=f"Docs for the {class_path_short} command")
            docstring_content = nodes.paragraph()
            docstring = cmd_class.__doc__ if cmd_class.__doc__ else "Warning: No docstring for this command!"
            self.state.nested_parse(StringList(docstring.split('\n'), 'dummy.rst'), 0, docstring_content)
            node += docstring_content

            try:
                cmd_parser = cmd_class.command(self.shell, ['--help'], return_parser=True)
            except Exception as e:
                print(f"ERROR: The parser for command {cmd_class} could not be obtained: {str(e)}!")
                cmd_parser = None

            if cmd_parser is not None:
                print(f"Help for {class_path_short}: {cmd_parser.format_help()}")
                help_block = nodes.literal_block(cmd_parser.format_help(), cmd_parser.format_help())
                help_block['class']=''
                node += help_block

            return node

        # if a parent of a command, parse the children commands
        elif content!=dict():
            new_parents = parents + [command]
            #
            # node = nodes.section(ids=[f"dts_command_{class_path_short.replace(' ','_')}"])
            # node += nodes.title(class_path_short, class_path_short)
            node += nodes.paragraph(text=f"Docs for the subcommands of {class_path_short}")
            print(f"DEBUG: Adding section id=dts_command_{class_path_short.replace(' ','_')} title={class_path_short}")

            for command, content_inner in sorted(content.items(), key=lambda item: item[0]):
                node += self.parse_a_command(command, content_inner, new_parents)

            return node



def setup(app):
    app.add_directive("dtscommands", DTS_Parser)

    return {
        'version': '0.1',
        'parallel_read_safe': False,
        'parallel_write_safe': False,
    }