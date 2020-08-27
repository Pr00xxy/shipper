#!/usr/bin/env python3

# Shipper

from argparse import ArgumentParser
import json
import os
import shutil
import time
from importlib import import_module
import pkg_resources

pkg_resources.require('fabric==2.5')
import fabric
from patchwork import files
from invoke.exceptions import UnexpectedExit

parser = ArgumentParser(description='description')
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
required.add_argument('--source-dir-dir',
                      dest='sourcedir',
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
                      help='a JSON hash or filename of symbolic links to be created in the revision directory (default: {} )')
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


class ShipperError(Exception):
    pass


class Colors(object):
    BLUE = '\x1b[0;34m'
    GREEN = '\x1b[0;32m'
    RED = '\x1b[0;31m'
    ORANGE = '\x1b[0;33m'
    WHITE = '\x1b[0;97m'
    END = '\033[0;0m'


class Log(object):

    @staticmethod
    def error(text: str):
        print(Colors.RED + text + Colors.END)

    @staticmethod
    def info(text: str):
        print(Colors.BLUE + text + Colors.END)

    @staticmethod
    def success(text: str):
        print(Colors.GREEN + text + Colors.END)

    @staticmethod
    def warning(text: str):
        print(Colors.ORANGE + text + Colors.END)

    @staticmethod
    def notice(text: str):
        print(Colors.BLUE + text + Colors.END)

class Shipper(object):
    plugin_instruction = None
    connection = None

    directories = {
        'revisions': 'revisions',
        'share': 'share'
    }

    def __init__(self,
                 plugin_path=None,
                 plugin_json=None,
                 deploy_dir=None,
                 source_dir=None,
                 revision=None,
                 revisions_to_keep=None,
                 symlinks=None
                 ):
        self.plugin_path = plugin_path
        self.plugin_json = plugin_json
        self.deploy_dir = deploy_dir
        self.source_dir = source_dir
        self.revision = revision
        self.revisions_to_keep = revisions_to_keep
        self.symlinks = symlinks

    def _get_connection(self):
        if self.connection is None:
            self.connection = fabric.Connection()

        return self.connection

    def run(self):
        try:

            self.dispatch_event('before:init_directories')
            Log.notice('Creating atomic deployment directories..')
            self.init_directories()
            self.dispatch_event('after:init_directories')

            self.dispatch_event('before:create_revision_dir')
            Log.notice('Creating new revision directory..')
            self.create_revision_dir()
            self.dispatch_event('after:create_revision_dir')

            self.dispatch_event('before:copy_cache_to_revision')
            Log.notice('Copying source-dir to new revision directory..')
            self.copy_cache_to_revision()
            self.dispatch_event('after:copy_cache_to_revision')

            self.dispatch_event('before:create_symlinks')
            Log.notice('Creating symlinks within new revision directory..')
            self.create_symlinks()
            self.dispatch_event('after:create_symlinks')

            self.dispatch_event('before:link_current_revision')
            Log.notice('Switching over to latest revision')
            self.link_current_revision()
            self.dispatch_event('after:link_current_revision')

            self.dispatch_event('before:purge_old_revisions')
            Log.notice('Purging old revisions')
            self.purge_old_revisions()
            self.dispatch_event('after:purge_old_revisions')

            Log.success('Done.')

            result = True
        except ShipperError:
            result = False

        return result

    def _create_directory(self, directory: str):
        with self._get_connection() as c:
            try:
                c.run('mkdir {}'.format(directory))
                Log.success('success')
            except UnexpectedExit as e:
                print(Colors.RED + 'failed' + Colors.END)
                raise ShipperError(
                    Colors.RED + 'failed creating {0} {1}'.format(directory, repr(e)) + Colors.END) from e

    def _dir_exists(self, directory: str):
        with self._get_connection() as c:
            cmd = 'test -d "$(echo {})"'.format(directory)
            c.run(cmd)

    def _link_exists(self, file: str):
        with self._get_connection() as c:
            cmd = 'test -L "$(echo {})"'.format(file)
            c.run(cmd)

    def _test_write_to_dir(self, directory: str):
        with self._get_connection() as c:
            if not c.run('touch {0}/test.file && rm -f {0}/test.file'.format(directory)):
                raise ShipperError(Colors.RED + '[!] directory {0} is not writable'.format(directory) + Colors.END)

            return True

    def init_directories(self):

        dirs_to_create = {
            "revisions directory": self.directories['revisions'],
            "share directory": self.directories['share'],
        }

        if not files.exists(self.deploy_dir):
            raise ShipperError(Colors.ORANGE + '[!] Deployment directory does not exist.' + Colors.END)

        self._test_write_to_dir(self.deploy_dir)

        for name, path in dirs_to_create.items():
            if not files.exists(path):
                print(Colors.ORANGE + '[!] {0} missing. Trying to create... '.format(path) + Colors.END, end='')

            self._create_directory('{0}/{1}'.format(self.deploy_dir, path))

    def create_revision_dir(self):
        self.revision_path = os.path.join(self.deploy_dir, self.directories['revisions'], self.revision)
        self.revision_path = self.revision_path.rstrip("/")

        if self._dir_exists(self.revision_path):
            self.revision_path = self.revision_path + '-' + str(round(time.time()))

        if self._dir_exists(self.revision_path):
            Log.notice('Revision directory already exists.')
        else:
            try:
                self._create_directory(self.revision_path)
                self._test_write_to_dir(self.revision_path)
            except ShipperError as e:
                Log.error('[!] Could not create revision directory: {0}'.format(self.revision_path))
                raise e

    def copy_cache_to_revision(self):

        cache_dir = os.path.join(self.deploy_dir, self.source_dir)

        if self._dir_exists(cache_dir):
            try:
                Log.notice('Copying deploy cache to revision directory')
                with self._get_connection() as c:
                    c.run('cp -r {0}/. {1}/'.format(cache_dir, self.revision_path))
            except UnexpectedExit as e:
                raise ShipperError(
                    Colors.RED + '[!] Could not copy deploy cache to revision directory' + Colors.END) from e

    def create_symlinks(self):

        if not self.symlinks:
            return  # No symlinks file

        if not os.path.isfile(self.symlinks):
            raise ShipperError('Symlinks file does not exists')

        try:
            with open(self.symlinks, 'r') as fh:
                symlink_data = json.load(fh)
        except json.JSONDecodeError as e:
            raise ShipperError(Colors.RED + '[!] Failed reading json data: {0}'.format(repr(e)) + Colors.END) from e

        if symlink_data is None:
            return

        for (k, v) in symlink_data.items():

            source = os.path.join(self.deploy_dir, k)
            target = os.path.join(self.revision_path, v)

            try:
                self.create_symlink(source, target)
            except UnexpectedExit as e:
                Log.error('[!] Could not create symlink {0} -> {1}'.format(source, target))
                raise ShipperError(repr(e)) from e

    def get_plugin_instruction(self):
        if self.plugin_instruction is None:
            try:
                with open(self.plugin_path, 'r') as plugin_file:
                    self.plugin_instruction = json.load(plugin_file)
                    return self.plugin_instruction
            except (ValueError, json.JSONDecodeError) as e:
                raise ShipperError(repr(e)) from e

        return self.plugin_instruction

    def dispatch_event(self, event_name):

        if self.plugin_path is None:
            return

        instruction = self.get_plugin_instruction()

        if event_name in instruction['action']:
            for execute in instruction['action'][event_name]['execute']:

                module_name = execute.split('.')
                function_name = module_name[-1]
                class_name = module_name[-2]
                module_name = '.'.join(module_name[:-2])
                try:
                    module_object = import_module(module_name)
                except ModuleNotFoundError as e:
                    Log.error('[!] No such module was found: {0}'.format(module_name))
                    raise ShipperError() from e

                try:
                    class_object = getattr(module_object, class_name)(self)
                    function_object = getattr(class_object, function_name)
                except AttributeError as e:
                    raise ShipperError() from e

                function_object()

    def create_symlink(self, target, link):

        print(Colors.WHITE + 'Creating symlink for {0} -> {1}'.format(link, target) + Colors.END)

        if self._link_exists(link):
            print(Colors.ORANGE + '[!] Target {0} is symlink already. deleting.. '.format(link) + Colors.END, end='')
            with self._get_connection() as c:
                c.run('unlink {0}'.format(link))
            Log.success('done')

        try:
            if files.exists(link):
                print(Colors.ORANGE + '[!] Target {0} is file already. deleting.. '.format(link) + Colors.END, end='')
                with self._get_connection() as c:
                    c.run('rm -f {0}'.format(link))
                Log.success('done')
            if self._dir_exists(link):
                print(Colors.ORANGE + '[!] Target {0} is directory already. deleting..'.format(link) + Colors.END,
                      end='')
                with self._get_connection() as c:
                    c.run('rm -rf {0}'.format(link))

                Log.success('done')

            with self._get_connection() as c:
                c.run('ln -s {0} {1}'.format(target, link))

        except UnexpectedExit as e:
            Log.error('failed')
            Log.error('[!] Could not create symlink {0} -> {1}'.format(target, link))
            raise ShipperError from e

    def purge_old_revisions(self):
        if self.revisions_to_keep > 0:
            revisions_dir = os.path.join(self.deploy_dir, self.directories['revisions'])
            no_of_revisions = len(revisions_dir)

            date_sorted = sorted([os.path.join(revisions_dir, i)
                                  for i in os.listdir(revisions_dir)],
                                 key=os.path.getmtime
                                 )

            loop_count = no_of_revisions - self.revisions_to_keep

            if no_of_revisions > self.revisions_to_keep:
                for v in date_sorted[:loop_count]:
                    try:
                        print(Colors.WHITE + '└ Deleting {0} '.format(v) + Colors.END, end='')
                        if os.path.isdir(v) is True:
                            shutil.rmtree(v)
                            Log.success('done')
                        else:
                            Log.error('failed')
                            Log.warning('[!] Failed deleting {0}. not a directory'.format(v))
                    except (NotADirectoryError, OSError) as e:
                        Log.warning(repr(e))

    def link_current_revision(self):
        self.create_symlink(self.revision_path, os.path.join(self.deploy_dir, 'current'))


deployer = Shipper(
    plugin_path=args.plugin_file,
    plugin_json=args.plugin_json,
    deploy_dir=args.deploy_dir,
    source_dir=args.sourcedir,
    revision=args.revision,
    revisions_to_keep=int(args.revisionstokeep),
    symlinks=args.symlinks
)

deployer.run()
