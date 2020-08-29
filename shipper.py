#!/usr/bin/env python3

# Shipper

from argparse import ArgumentParser
import os
import shutil
from importlib import import_module
import pkg_resources
import sys

pkg_resources.require('fabric==2.5')
import fabric
import config
from patchwork import files
from invoke.exceptions import UnexpectedExit

parser = ArgumentParser(description='description')

# parser._action_groups.pop()

required = parser.add_argument_group('required arguments')

required.add_argument('--config',
                      dest='config',
                      action='store',
                      default=None,
                      help='configuration file')

args = parser.parse_args()


class ShipperError(Exception):
    pass


class C(object):
    BLUE = '\x1b[0;34m'
    GREEN = '\x1b[0;32m'
    RED = '\x1b[0;31m'
    ORANGE = '\x1b[0;33m'
    WHITE = '\x1b[0;97m'
    END = '\033[0;0m'


class Log(object):

    @staticmethod
    def error(text: str):
        print(C.RED + text + C.END)

    @staticmethod
    def info(text: str):
        print(C.BLUE + text + C.END)

    @staticmethod
    def success(text: str):
        print(C.GREEN + text + C.END)

    @staticmethod
    def warn(text: str):
        print(C.ORANGE + text + C.END)

    @staticmethod
    def notice(text: str):
        print(C.BLUE + text + C.END)


class Cfg(object):
    _prefix = 'SHIP_'

    def __init__(self, path: str):
        self.cfg = config.ConfigurationSet(
            config.config_from_json(path, read_from_file=True),
            config.config_from_env(prefix=self._prefix)
        )

    def __call__(self, path: str):
        return self.cfg[path]


class Shipper(object):

    tasks_executed = []
    connection = None

    def __init__(self, config: str):
        self.cfg = Cfg(config)

    def _get_connection(self):

        if self.connection is None:
            self.connection = fabric.Connection(

            )

        return self.connection

    def run(self):

        event = Event(
            cfg=self.cfg,
            shipper=self
        )

        try:

            event.dispatch('before:init_directories')
            Log.notice('Creating atomic deployment directories..')
            self.init_directories()

            event.dispatch('before:create_revision_dir')
            Log.notice('Creating new revision directory..')
            revision_dir = self.create_revision_dir()

            event.dispatch('before:copy_cache_to_revision')
            Log.notice('Copying source-dir to new revision directory..')
            self.copy_source_to_revision(revision_dir)

            event.dispatch('before:create_symlinks')
            Log.notice('Creating symlinks within new revision directory..')
            self.create_symlinks(revision_dir)

            event.dispatch('before:link_current_revision')
            Log.notice('Switching over to latest revision')
            self.link_current_revision()

            event.dispatch('before:purge_old_revisions')
            Log.notice('Purging old revisions')
            self.purge_old_revisions()

            event.dispatch('before:completion')
            Log.success('Done.')

        except ShipperError:
            event.dispatch('on:error')
            sys.exit(1)

        sys.exit(0)

    def _create_directory(self, directory: str):
        with self._get_connection() as c:
            try:
                c.run('mkdir {}'.format(directory))
                Log.success('success')
            except UnexpectedExit as e:
                Log.error('failed')
                raise ShipperError(C.RED + 'failed creating {0} {1}'.format(directory, repr(e)) + C.END) from e

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
                raise ShipperError(C.RED + '[!] directory {0} is not writable'.format(directory) + C.END)

            return True

    def init_directories(self):

        deploy_dir = self.cfg('config.base_dir')
        dirs_to_create = self.cfg('config.directories').as_dict()

        if self._dir_exists(deploy_dir):
            raise ShipperError(C.ORANGE + '[!] Deployment directory does not exist.' + C.END)

        self._test_write_to_dir(deploy_dir)

        for name, path in dirs_to_create.items():
            if not files.exists(path):
                print(C.ORANGE + '[!] {0} missing. Trying to create... '.format(path) + C.END, end='')

            self._create_directory('{0}/{1}'.format(deploy_dir, path))

    def create_revision_dir(self):

        revisions_dir = self.cfg('config.directories.revisions')

        revision_path = os.path.join(revisions_dir, self.cfg('config.revision'))

        try:
            self._create_directory(revision_path)
            self._test_write_to_dir(revision_path)
        except ShipperError as e:
            Log.error('[!] Could not create revision directory: {0}'.format(revision_path))
            raise e

        return revisions_dir

    def copy_source_to_revision(self, revision_dir: str):

        source_dir = self.cfg('config.source_dir')

        if self._dir_exists(source_dir):
            try:
                Log.notice('Copying deploy cache to revision directory')
                with self._get_connection() as c:
                    c.run('cp -r {0}/. {1}/'.format(source_dir, revision_dir))
            except UnexpectedExit as e:
                raise ShipperError(
                    '[!] Could not copy deploy cache to revision directory') from e

    def create_symlinks(self, revision_path: str):

        symlink_data = self.cfg('symlinks')

        if symlink_data is None:
            return

        for (k, v) in symlink_data.items():

            source = os.path.join(k)
            target = os.path.join(revision_path, v)

            try:
                self.create_symlink(source, target)
            except UnexpectedExit as e:
                Log.error('[!] Could not create symlink {0} -> {1}'.format(source, target))
                raise ShipperError(repr(e)) from e

    def create_symlink(self, target, link):

        Log.info('Creating symlink for {0} -> {1}'.format(link, target))

        if self._link_exists(link):
            Log.warn('[!] Target {0} is symlink already. deleting.. '.format(link))
            with self._get_connection() as c:
                c.run('unlink {0}'.format(link))
            Log.success('done')

        try:
            if files.exists(link):
                Log.warn('[!] Target {0} is file already. deleting.. '.format(link))
                with self._get_connection() as c:
                    c.run('rm -f {0}'.format(link))
                Log.success('done')
            if self._dir_exists(link):
                Log.warn('[!] Target {0} is directory already. deleting..'.format(link))
                with self._get_connection() as c:
                    c.run('rm -rf {0}'.format(link))

                Log.success('done')

            with self._get_connection() as c:
                c.run('ln -s {0} {1}'.format(target, link))

        except UnexpectedExit as e:
            Log.error('failed')
            Log.error('[!] Could not create symlink {0} -> {1}'.format(target, link))
            raise ShipperError() from e

    def purge_old_revisions(self):

        revisions_to_keep = self.cfg('config.revisions_to_keep')
        revisions_dir = self.cfg('config.directories.revisions')

        if revisions_to_keep > 0:
            no_of_revisions = len(revisions_dir)

            date_sorted = sorted([os.path.join(revisions_dir, i)
                                  for i in os.listdir(revisions_dir)],
                                 key=os.path.getmtime
                                 )

            loop_count = no_of_revisions - revisions_to_keep

            if no_of_revisions > revisions_to_keep:
                for v in date_sorted[:loop_count]:
                    try:
                        Log.info('└ Deleting {0} '.format(v))
                        if os.path.isdir(v):
                            shutil.rmtree(v)
                            Log.success('done')
                        else:
                            Log.error('[!] Failed deleting {0}. not a directory'.format(v))

                    except (NotADirectoryError, OSError) as e:
                        Log.warn(repr(e))

    def link_current_revision(self):
        self.create_symlink(self.revision_path, os.path.join(self.deploy_dir, 'current'))


class Event(object):
    events_dispatched = []
    event_data: dict = None
    shipper = None

    last_event: str = None

    def __init__(self, cfg: Cfg, shipper: Shipper):
        self.shipper = shipper
        self.event_data = cfg('events')

    def _register_event_dispatch(self, event_name: str):
        self.events_dispatched.append(event_name)
        self.last_event = event_name

    def dispatch(self, event_name: str):
        self._register_event_dispatch(event_name)

        if event_name not in self.event_data['action']:
            return

        for execute in self.event_data['action'][event_name]['execute']:

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
                class_object = getattr(module_object, class_name)(self.shipper)
                function_object = getattr(class_object, function_name)
            except AttributeError as e:
                raise ShipperError() from e

            function_object()


shipper = Shipper(
    config=args.config
)

shipper.run()
