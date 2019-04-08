#!/usr/bin/env python3

import os
import time
import subprocess
import json
import argparse
import shutil
from distutils.dir_util import copy_tree
from importlib import import_module

parser = argparse.ArgumentParser(description='description')
parser._action_groups.pop()
required = parser.add_argument_group('required arguments')
optional = parser.add_argument_group('optional arguments')

required.add_argument('--revision',
                      dest='revision',
                      action='store',
                      default=None,
                      help='(required) accepts a string ID for this revision')
required.add_argument('--deploy-dir',
                      dest='deploy_dir',
                      action='store',
                      default=os.path.dirname(os.path.realpath(__file__)),
                      help='Base directory for deployment  (default: directory of shipper.py)')
required.add_argument('--deploy-cache-dir',
                      dest='deploycachedir',
                      action='store',
                      default="deploy_cache",
                      help='Directory in which the deployed files are initially deploy')
optional.add_argument('--revisions-to-keep',
                      dest='revisionstokeep',
                      action='store',
                      type=int,
                      default=5,
                      help='number of old revisions to keep in addition to the current revision')
optional.add_argument('--symlinks',
                      dest='symlinks',
                      action='store',
                      default='{}',
                      help='A JSON hash or filename of symbolic links to be created in the revision directory (default: {} )')
optional.add_argument('--plugin-file',
                      dest='plugin_file',
                      action='store',
                      default=None,
                      help='file path to the plugin file')
optional.add_argument('--plugin-json',
                      dest='plugin_json',
                      action='store',
                      default=None,
                      help='json hash to be sent to the plugin')

args = parser.parse_args()


class Colors(object):
    BLUE: str = '\x1b[0;34m'
    GREEN: str = '\x1b[0;32m'
    RED: str = '\x1b[0;31m'
    ORANGE: str = '\x1b[0;33m'
    WHITE = '\x1b[0;97m'
    END: str = '\033[0;0m'


class Deployer(object):
    plugin_instruction = None

    directories = {
        'revisions': 'revisions',
        'share': 'share',
        'config': 'share/config',
    }

    def __init__(self,
                 plugin_path=None,
                 plugin_json=None,
                 deploy_dir=None,
                 deploy_cache_dir=None,
                 revision=None,
                 revisions_to_keep=None,
                 symlinks=None
                 ):
        self.plugin_path = plugin_path
        self.plugin_json = plugin_json
        self.deploy_dir = deploy_dir
        self.deploy_cache_dir = deploy_cache_dir
        self.revision = revision
        self.revisions_to_keep = revisions_to_keep
        self.symlinks = symlinks

    def run(self):
        try:
            # -------------------------------------------------------------
            self.dispatch_event('before:init_directories')
            print(Colors.BLUE + 'Creating atomic deployment directories..' + Colors.END)
            self.init_directories()
            self.dispatch_event('after:init_directories')
            # -------------------------------------------------------------
            self.dispatch_event('before:create_revision_dir')
            print(Colors.BLUE + 'Creating new revision directory..' + Colors.END)
            self.create_revision_dir()
            self.dispatch_event('after:create_revision_dir')
            # -------------------------------------------------------------
            self.dispatch_event('before:copy_cache_to_revision')
            print(Colors.BLUE + 'Copying deploy-cache to new revision directory..' + Colors.END)
            self.copy_cache_to_revision()
            self.dispatch_event('after:copy_cache_to_revision')
            # -------------------------------------------------------------
            self.dispatch_event('before:create_symlinks')
            print(Colors.BLUE + 'Creating symlinks within new revision directory..' + Colors.END)
            self.create_symlinks()
            self.dispatch_event('after:create_symlinks')
            # -------------------------------------------------------------
            self.dispatch_event('before:link_current_revision')
            print(Colors.BLUE + 'Switching over to latest revision' + Colors.END)
            self.link_current_revision()
            self.dispatch_event('after:link_current_revision')
            # -------------------------------------------------------------
            self.dispatch_event('before:purge_old_revisions')
            print(Colors.BLUE + 'Purging old revisions' + Colors.END)
            self.purge_old_revisions()
            self.dispatch_event('after:purge_old_revisions')
            # -------------------------------------------------------------

            print(Colors.GREEN + 'Done.' + Colors.END)

            result = True
        except Exception:
            result = False

        return result

    def init_directories(self):

        dirs_to_create = {
            "revisions directory": self.directories['revisions'],
            "share directory": self.directories['share'],
            "config directory": self.directories['config']
        }

        if not os.path.exists(self.deploy_dir):
            raise SystemExit(Colors.ORANGE + '[!] Deployment directory does not exist.' + Colors.END)

        if not os.access(self.deploy_dir, os.W_OK) is True:
            raise SystemExit(
                Colors.RED + '[!] The deploy directory {0} is not writable'.format(self.deploy_dir) + Colors.END)

        for k, v in dirs_to_create.items():
            if not os.path.isdir(v):
                print(Colors.ORANGE + '[!] {0} missing. Trying to create... '.format(v) + Colors.END, end='')
                try:
                    os.makedirs(v)
                    print(Colors.GREEN + 'success' + Colors.END)
                except RuntimeError as e:
                    print(Colors.RED + 'failed' + Colors.END)
                    raise SystemExit(Colors.RED + 'failed creating {0} {1}'.format(k, repr(e)) + Colors.END) from e

    def create_revision_dir(self):
        self.revision_path = os.path.join(self.deploy_dir, self.directories['revisions'], self.revision)
        self.revision_path = self.revision_path.rstrip("/")

        if os.path.isdir(os.path.realpath(self.revision_path)) is True:
            self.revision_path = self.revision_path + '-' + str(round(time.time()))

        if not os.path.isdir(self.revision_path) is True:
            try:
                os.mkdir(self.revision_path)
            except Exception as e:
                raise SystemExit(Colors.RED + '[!] Could not create revision directory: {0}'.format(
                    self.revision_path) + Colors.END) from e
        else:
            print(Colors.BLUE + 'Revision directory already exists.' + Colors.END)

        if not os.access(self.revision_path, os.W_OK) is True:
            raise SystemExit(
                Colors.RED + '[!] The revision directory {0} is not writable'.format(self.revision_path) + Colors.END)

    def copy_cache_to_revision(self):
        if os.path.isdir(self.deploy_cache_dir) is True:
            try:
                print(Colors.BLUE + 'Copying deploy cache to revision directory' + Colors.END)
                copy_tree(self.deploy_cache_dir, self.revision_path)
            except subprocess.CalledProcessError as e:
                raise SystemExit(
                    Colors.RED + '[!] Could not copy deploy cache to revision directory' + Colors.END) from e

    def create_symlinks(self):

        symlink_data = None

        if os.path.isfile(self.symlinks) is True:
            try:
                with open(self.symlinks, 'r') as fh:
                    symlink_data = json.load(fh)
            except Exception as e:
                print(Colors.RED + '[!] Failed reading json data: {0}'.format(repr(e)) + Colors.END)
        else:  # Try loading the json as is if given data is not a file
            try:
                symlink_data = json.loads(self.symlinks)
            except Exception as e:
                print(Colors.RED + '[!] Failed reading json data: {0}'.format(repr(e)) + Colors.END)

        if symlink_data is None:
            return

        for (k, v) in symlink_data.items():
            target = os.path.join(self.deploy_dir, k)
            link = os.path.join(self.revision_path, v)

            try:
                self.create_symlink(target, link)
            except Exception:
                print(Colors.RED + '[!] Could not create symlink {0} -> {1}'.format(target, link) + Colors.END)

    def get_plugin_instruction(self):
        if self.plugin_instruction is None:
            try:
                with open(self.plugin_path, 'r') as plugin_file:
                    self.plugin_instruction = json.load(plugin_file)
                    return self.plugin_instruction
            except (ValueError, json.JSONDecodeError) as e:
                raise SystemExit(repr(e)) from e

        return self.plugin_instruction

    def dispatch_event(self, event_name):

        instruction = self.get_plugin_instruction()

        if event_name in instruction['action']:
            for execute in instruction['action'][event_name]['execute']:

                module_name = execute['name'].split('.')
                function_name = module_name[-1]
                class_name = module_name[-2]
                module_name = '.'.join(module_name[:-2])
                try:
                    module_object = import_module(module_name)
                except ModuleNotFoundError:
                    print(Colors.RED + '[!] No such module was found: {0}'.format(module_name) + Colors.END)
                    return False

                try:
                    class_object = getattr(module_object, class_name)(self)
                    function_object = getattr(class_object, function_name)
                except AttributeError as e:
                    raise SystemExit(repr(e))

                function_object()

    def create_symlink(self, target, link):

        print(Colors.WHITE + 'Creating symlink for {0} -> {1}'.format(link, target) + Colors.END)
        if os.path.islink(link):
            print(Colors.ORANGE + '[!] Target {0} is symlink already. deleting.. '.format(link) + Colors.END, end='')
            os.unlink(link)
            print(Colors.GREEN + 'done' + Colors.END)

        try:
            if os.path.isfile(link) is True:
                print(Colors.ORANGE + '[!] Target {0} is file already. deleting.. '.format(link) + Colors.END, end='')
                os.remove(link)
                print(Colors.GREEN + 'done' + Colors.END)
            if os.path.isdir(link) is True:
                print(Colors.ORANGE + '[!] Target {0} is directory already. deleting..'.format(link) + Colors.END, end='')
                shutil.rmtree(link)
                print(Colors.GREEN + 'done' + Colors.END)
            os.symlink(target, link)
        except (Exception, FileNotFoundError):
            print(Colors.RED + 'failed' + Colors.END)
            print(Colors.RED + '[!] Could not create symlink {0} -> {1}'.format(target, link) + Colors.END)
            return False

        return True

    def purge_old_revisions(self):
        if self.revisions_to_keep > 0:
            revisions_dir = os.path.join(self.deploy_dir, self.directories['revisions'])

            date_sorted = sorted([os.path.join(revisions_dir, i)
                                  for i in os.listdir(revisions_dir)],
                                 key=os.path.getmtime
                                 )
            curr_dir_count = len(date_sorted)
            loop_count = curr_dir_count - self.revisions_to_keep

            if curr_dir_count > self.revisions_to_keep:
                for v in date_sorted[:loop_count]:
                    try:
                        print(Colors.WHITE + '└ Deleting {0} '.format(v) + Colors.END, end='')
                        if os.path.isdir(v) is True:
                            shutil.rmtree(v)
                            print(Colors.GREEN + 'done' + Colors.END)
                        else:
                            print(Colors.RED + 'failed' + Colors.END)
                            print(Colors.ORANGE + '[!] Failed deleting {0}. not a directory'.format(v) + Colors.END)
                    except (NotADirectoryError, OSError) as e:
                        print(Colors.ORANGE + repr(e) + Colors.END)  # TODO: improve this

    def link_current_revision(self):
        self.create_symlink(self.revision_path, os.path.join(self.deploy_dir, 'current'))


deployer = Deployer(
    plugin_path=args.plugin_file,
    plugin_json=args.plugin_json,
    deploy_dir=args.deploy_dir.rstrip("/"),
    deploy_cache_dir=args.deploycachedir,
    revision=args.revision,
    revisions_to_keep=int(args.revisionstokeep),
    symlinks=args.symlinks
)

deployer.run()
