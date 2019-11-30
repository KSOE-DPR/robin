#!/usr/bin/env python
from lxml import etree
from time import sleep
import os
import re
import sys
import rosgraph
import rosnode
import yaml

import robin
import srcgen

try:  #python2
    from StringIO import StringIO
except ImportError:  #python3
    from io import StringIO

# DEV = True
# raise SystemExit  #DEV

def print_(msg):
    print(msg)
    sys.stdout.flush()


class Updater:
    DEF_NODE_NAME = 'robin'
    DEF_CATKIN_WS = '~/catkin_ws'

    def __init__(self, paths_file='config/paths.yml', catkin_ws=DEF_CATKIN_WS):
        # load config files
        self.paths = self.load_yaml(paths_file, self.parse_paths)
        self.types_map = self.load_yaml(self.paths['config']['types'])
        self.templates = self.load_yaml(self.paths['config']['templates'])
        # parse src
        self.xml_root = self.get_xml_root(self.paths['config']['xml'])
        self.robins = self.get_robins()
        if 'DEV' in globals() and DEV:
            print_('\n# ROBINS\n{}'.format(self.robins))
            # raise SystemExit  #DEV
        
        print_('\nGenerating source code...')
        self.src_gen = srcgen.SourceGenerator(self.types_map, self.templates, self.xml_root)
        self.source = self.src_gen.get_source(self.robins)
        if 'DEV' in globals() and DEV:
            print_('\n# SOURCE\n{}'.format(self.source))
            # raise SystemExit  #DEV
        
        self.write_source()
        if 'DEV' in globals() and DEV:
            raise SystemExit  #DEV
        self.recompile_robin(catkin_ws)
        self.restart_robin(self.DEF_NODE_NAME, catkin_ws)
        print_('\nUpdate finished.')

    # loads yaml file and parses it with parse()
    @staticmethod
    def load_yaml(file_path, parse=lambda x: x):
        with open(file_path, 'r') as file:
            return parse(yaml.safe_load(file))

    # preprocess paths
    @staticmethod
    def parse_paths(paths):
        # get root folders
        cfg_root = paths['config'].pop('root')
        pkg_root = paths['package'].pop('root')
        # expand config files paths
        for file in paths['config']:
            paths['config'][file] = cfg_root + paths['config'][file]
        # expand source files path
        for file in paths['src_files']:
            paths['src_files'][file] = pkg_root + paths['package'][file] + paths['src_files'][file]
            paths['package'].pop(file)
        # expand package files paths
        for file in paths['package']:
            paths['package'][file] = pkg_root + paths['package'][file]
        return paths

    # loads xml
    @staticmethod
    def get_xml_root(file_path):
        with open(file_path, 'r') as file:
            xml = file.read()
            while xml[:5] != '<?xml': xml = xml[1:]  # fix weird first character
            xml = re.sub('<\?xml version=.*encoding=.*\n', '', xml, count=1)  # remove encoding
            xml = re.sub(' xmlns=".*plcopen.org.*"', '', xml, count=1)  # remove namespace
            return etree.fromstring(xml)

    # parses robins from robin objects in xml
    def get_robins(self):
        robins = []
        robin_objs = self.xml_root.xpath('instances//variable[descendant::derived[@name="Robin"]]/@name')
        for obj_name in robin_objs:
            src = self.xml_root.xpath('instances//addData/data/pou/body/ST/*[contains(text(), "{}();")]/text()'.format(obj_name))  #TODO handle spaces
            # src = self.xml_root.xpath('instances//addData/data/pou/body/ST/node()[contains(text(), "{}();")]/text()'.format(obj_name))  #TODO try
            if len(src) == 0:
                print_("Warning: no source found for robin object '{}'.".format(obj_name))
            elif len(src) > 1:
                raise RuntimeError("Robin object '{}' used in more than one POU.".format(obj_name))
            for line in StringIO(src[0]):
                robins += self.get_robin_from_call(line, obj_name)
        if len(robins) == 0:
            raise RuntimeError('No valid robin objects found.')
        return robins

    # parses robin from robin call
    def get_robin_from_call(self, src, name):
        pat = "^[ ]*{}[ ]*\.[ ]*(read|write)[ ]*\([ ]*'([^ ,]+)'[ ]*,[ ]*([^ ,)]+)[ ]*\)[ ]*;".format(name)
        match = re.search(pat, src)
        if match is None:
            return []
        props = match.group(1, 2, 3)  # type, name, var_name
        if None in props:
            raise RuntimeError("Failed to parse robin call in '{}'.".format(src))
        return [robin.Robin(self.types_map, self.xml_root, *props)]

    # writes source files
    def write_source(self):
        # write generated source to respective files
        for file in self.paths['src_files']:
            with open(self.paths['src_files'][file], 'w') as src_file:
                src_file.write(self.templates[file]['file'].format(self.source[file]))
        # delete and rewrite msg files
        os.system('rm ' + self.paths['package']['msg'] + '*.msg')
        for msg, src in self.source['msgs'].items():
            with open(self.paths['package']['msg'] + msg + '.msg', 'w') as src_file:
                src_file.write(src)
        # update package files
        self.update_cmakelists(self.paths['package']['cmakelists'], self.src_gen.msg_pkgs, self.source['msgs'])
        self.update_package_xml(self.paths['package']['package_xml'], self.src_gen.msg_pkgs, self.source['msgs'])

    # updates CMakeLists.txt
    @staticmethod
    def update_cmakelists(cmakelists_path, msg_pkgs, msgs):
        with open(cmakelists_path, 'r+') as file:
            content = file.read()
            if len(msg_pkgs) > 0:
                # find_package
                new_src = ('find_package(catkin REQUIRED COMPONENTS\n'
                         + '  roscpp\n'
                         + ''.join(['  ' + pkg + '\n' for pkg in msg_pkgs])
                         +('  message_generation\n' if len(msgs) > 0 else '')
                         + ')')
                content = re.sub('find_package\s?\([^)]*roscpp[^)]*\)', new_src, content)
                # generate_messages
                new_src = ('generate_messages(\n'
                         + '  DEPENDENCIES\n'
                         + ''.join(['  ' + pkg + '\n' for pkg in msg_pkgs])
                         + ')')
                content = re.sub('#? ?generate_messages\s?\([^)]*\n[^)]*\)', new_src, content)
                # catkin_package
                new_src = ('\n  CATKIN_DEPENDS roscpp '
                         + ''.join([pkg + ' ' for pkg in msg_pkgs])
                         + 'message_runtime' if len(msgs) > 0 else '')
                content = re.sub('\n#?\s*CATKIN_DEPENDS roscpp.*', new_src, content)
            if len(msgs) > 0:
                # add_message_files
                new_src = ('add_message_files(\n'
                         + '  FILES\n'
                         + ''.join(['  ' + msg + '.msg\n' for msg in msgs])
                         + ')')
                content = re.sub('#? ?add_message_files\s?\([^)]*\)', new_src, content)
            file.seek(0)
            file.write(content)
            file.truncate()

    # updates package.xml
    @staticmethod
    def update_package_xml(package_xml_path, msg_pkgs, msgs):
        with open(package_xml_path, 'r+') as file:
            content = file.read()
            new_src = ('\n  <depend>roscpp</depend>\n'
                     + ''.join(['  <depend>' + pkg + '</depend>\n' for pkg in msg_pkgs])
                     +('  <build_depend>message_generation</build_depend>\n'
                     + '  <exec_depend>message_runtime</exec_depend>\n' if len(msgs) > 0 else '')
                     + '  <exec_depend>python</exec_depend>')
            content = re.sub('\n  <depend>roscpp<\/depend>[\S\s]*<exec_depend>python<\/exec_depend>', new_src, content)
            file.seek(0)
            file.write(content)
            file.truncate()

    # recompiles robin package
    @staticmethod
    def recompile_robin(catkin_ws=DEF_CATKIN_WS):
        print_('\nRecompiling...')
        cmd = '''bash -c "
                    cd {} &&
                    . devel/setup.bash &&
                    build_robin()
                    {{
                        if [ -d .catkin_tools ]; then
                            catkin build robin
                        else
                            catkin_make robin
                        fi
                    }}
                    set -o pipefail
                    build_robin 2>&1 >/dev/null |
                    sed 's/\\x1b\[[0-9;]*[mK]//g'
                "'''.format(catkin_ws)
        if os.system(cmd) != 0:
            raise RuntimeError('Failed to recompile robin package.')

    # restarts robin bridge
    @classmethod
    def restart_robin(cls, node_name=DEF_NODE_NAME, catkin_ws=DEF_CATKIN_WS):
        print_('\nRestarting...')
        node_path = cls.get_node_path(node_name)
        if node_path == '':
            print_('Robin node is not running.')
        elif node_path is not None:
            if rosnode.rosnode_ping(node_name, max_count=3):  # if node alive
                if node_path not in rosnode.kill_nodes([node_path])[0]:  # kill node
                    raise RuntimeError("Failed to kill robin node '{}'.".format(node_path))
            cls.wait_for(lambda: cls.get_node_path(node_name) == '')
            cmd = '''bash -c "
                        cd {} &&
                        . devel/setup.bash &&
                        rosrun robin robin __ns:={} &
                    " > /dev/null 2>&1'''.format(catkin_ws, node_path[:-len('/' + node_name)])
            if os.system(cmd) != 0:
                raise RuntimeError('Failed to rerun robin node.')
            cls.wait_for(lambda: cls.get_node_path(node_name) != '', timeout=10)

        # try to restart codesyscontrol service
        if os.system('sudo -n systemctl restart codesyscontrol > /dev/null 2>&1') != 0:
            print_('\nFailed to restart codesyscontrol. Please do it manually.')

    # searches for node called node_name
    @staticmethod
    def get_node_path(node_name):
        try:
            for node in rosnode.get_node_names():
                if node[-len('/' + node_name):] == '/' + node_name:
                    return node
            return ''
        except rosnode.ROSNodeIOException:
            print_('ROS master is not running.')
            return None

    # waits for a given condition to become true; interval in msec, timeout in sec
    @staticmethod
    def wait_for(condition, interval=100, timeout=5):
        for i in range(0 ,timeout * 1000, interval):
            sleep(interval / 1000.0)
            if condition():
                return
        raise RuntimeError('Operation timed out.')


if __name__ == '__main__':
    # check catkin workspace was passed as argument
    if len(sys.argv) != 2:
        print_('Usage: ./update.py <path_to_catkin_ws>')
        raise SystemExit
    catkin_ws = sys.argv[1] + ('/' if not sys.argv[1].endswith('/') else '')

    # check catkin workspace exists
    if not os.path.isdir(catkin_ws):
        print_("Folder '{}' not found.".format(catkin_ws))
        raise SystemExit

    # run updater
    Updater(catkin_ws=catkin_ws)
