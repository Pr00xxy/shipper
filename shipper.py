#!/usr/bin/env python3

from argparse import ArgumentParser
import os
from importlib import import_module
import pkg_resources
import sys
import time
pkg_resources.require('fabric==2.5')
import fabric
import config
from invoke.exceptions import UnexpectedExit

parser = ArgumentParser(description='description')

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

    def get_connection(self):
        if not self.connection:
            return fabric.Connection(
                host=self.cfg('config.target.host'),
                user=self.cfg('config.target.user')
            )

        return self.connection

    def exec(self, cmd: str):
        with self.get_connection() as c:
            return c.run(cmd, warn=True)

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
            self.link_current_revision(revision_dir)

            event.dispatch('before:purge_old_revisions')
            Log.notice('Purging old revisions')
            self.purge_old_revisions()

            event.dispatch('before:completion')
            Log.success('Done.')

        except ShipperError:
            event.dispatch('on:error')
            sys.exit(1)

        sys.exit(0)

    def create_directory(self, directory: str):
        try:
            print(C.ORANGE + 'Creating new directory {} ... '.format(directory) + C.END, end='')
            rc = self.exec('mkdir {}'.format(directory))
            if not rc:
                Log.error('failed')
                raise ShipperError('Could not create directory {}'.format(directory))
            Log.success('success')
        except UnexpectedExit as e:
            raise ShipperError() from e

    def dir_exists(self, directory: str):
        cmd = 'test -d {0}'.format(directory)
        self.exec(cmd)

    def file_exists(self, file: str):
        cmd = 'test -f {0}'.format(file)
        self.exec(cmd)

    def link_exists(self, file: str):
        cmd = 'test -L {0}'.format(file)
        self.exec(cmd)

    def test_write_to_dir(self, directory: str):
        try:
            has_w_access = self.exec('touch {0}/test.file && rm -f {0}/test.file'.format(directory))
            if not has_w_access:
                raise ShipperError(C.RED + '[!] directory {0} is not writable'.format(directory) + C.END)
        except UnexpectedExit as e:
            raise ShipperError() from e

        return True

    def init_directories(self):

        deploy_dir = self.cfg('config.base_dir')
        dirs_to_create = self.cfg('config.directories').as_dict()

        if self.dir_exists(deploy_dir):
            raise ShipperError(C.ORANGE + '[!] Deployment directory does not exist.' + C.END)

        self.test_write_to_dir(deploy_dir)

        for name, path in dirs_to_create.items():
            try:
                dir_exists = self.exec('test -d {}'.format(path))
                if not dir_exists:
                    print(C.ORANGE + '[!] {0} missing. Trying to create... '.format(path) + C.END, end='')
                    self.create_directory(path)
            except UnexpectedExit as e:
                raise ShipperError() from e

    def create_revision_dir(self):

        revisions_dir = self.cfg('config.directories.revisions')

        revision_path = os.path.join(revisions_dir, self.cfg('config.revision'))

        try:
            rev_exists = self.exec('test -d {}'.format(revision_path))
            if rev_exists:
                revision_path = revision_path + '-' + str(round(time.time()))

            self.create_directory(revision_path)
            self.test_write_to_dir(revision_path)
        except ShipperError as e:
            Log.error('[!] Could not create revision directory: {0}'.format(revision_path))
            raise e

        return revision_path

    def copy_source_to_revision(self, revision_dir: str):

        source_dir = self.cfg('config.source_dir')

        if self.dir_exists(source_dir):
            try:
                Log.notice('Copying deploy cache to revision directory')
                self.exec('cp -r {0}/. {1}/'.format(source_dir, revision_dir))
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

        if self.link_exists(link):
            Log.warn('[!] Target {0} is symlink already. deleting.. '.format(link))
            self.exec('unlink {0}'.format(link))
            Log.success('done')

        try:
            if self.file_exists(link):
                Log.warn('[!] Target {0} is file already. deleting.. '.format(link))
                self.exec('rm -f {0}'.format(link))
                Log.success('done')
            if self.dir_exists(link):
                Log.warn('[!] Target {0} is directory already. deleting..'.format(link))
                self.exec('rm -rf {0}'.format(link))

                Log.success('done')

            self.exec('ln -s {0} {1}'.format(target, link))

        except UnexpectedExit as e:
            if self.cfg('config.fail_on_symlink_error') is True:
                Log.error('[!] Could not create symlink {0} -> {1}'.format(target, link))
                raise ShipperError() from e

    def purge_old_revisions(self):
        # @todo implement this
        pass

    def link_current_revision(self, revision_path: str):
        active_symlink = self.cfg('config.active_symlink')
        try:
            self.exec('ln -snf {0} {1}'.format(revision_path, active_symlink))
        except UnexpectedExit as e:
            raise ShipperError() from e


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

        if event_name not in self.event_data:
            return

        for execute in self.event_data[event_name]:

            module_parts = execute.split('.')

            function_name = module_parts[-1]
            class_name = module_parts[-2]

            module_name = '.'.join(module_parts[:-2])

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
