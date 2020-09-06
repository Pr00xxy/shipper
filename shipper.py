#!/usr/bin/env python3

from argparse import ArgumentParser
import os
from importlib import import_module
import pkg_resources
import sys
import time
import fabric
import config
from invoke.exceptions import UnexpectedExit

pkg_resources.require('fabric==2.5')

parser = ArgumentParser(description='description')

required = parser.add_argument_group('required arguments')

required.add_argument('--config',
                      dest='config',
                      action='store',
                      default=None,
                      help='configuration file')

args = parser.parse_args()


class Connection(fabric.Connection):

    def __exit__(self, *exc):
        """
        Override parent function to allow us to use a single connection during the entire runtime
        :param exc:
        :return:
        """
        pass


class ShipperError(Exception):
    """
    Core shipper exception.
    Throwing this exception dispatches the special on:error events
    """
    pass


class Log(object):
    """
    Helper class for outputting pretty colours
    """

    BLUE = '\x1b[0;34m'
    GREEN = '\x1b[0;32m'
    RED = '\x1b[0;31m'
    ORANGE = '\x1b[0;33m'
    WHITE = '\x1b[0;97m'
    END = '\033[0;0m'

    @staticmethod
    def error(text: str):
        print(Log.RED + text + Log.END)

    @staticmethod
    def info(text: str):
        print(Log.BLUE + text + Log.END)

    @staticmethod
    def success(text: str):
        print(Log.GREEN + text + Log.END)

    @staticmethod
    def warn(text: str):
        print(Log.ORANGE + text + Log.END)

    @staticmethod
    def notice(text: str):
        print(Log.BLUE + text + Log.END)


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
    current_revision: str
    connection = None

    def __init__(self, config: str):
        self.cfg = Cfg(config)

    def get_connection(self):
        if self.connection is None:
            self.connection = Connection(
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
            context=self
        )

        try:

            event.dispatch('on:start')

            self.current_revision = self.establish_current_link()

            event.dispatch('before:init_directories')
            Log.notice('Creating atomic deployment directories..')
            self.init_directories()

            event.dispatch('before:create_revision')
            Log.notice('Creating new revision directory..')
            revision_dir = self.create_revision_dir()

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

            Log.success('Deployment Completed.')

        except ShipperError:
            event.dispatch('on:error')
            self.connection.close()
            sys.exit(1)

        sys.exit(0)

    def create_directory(self, directory: str):
        try:
            Log.info('Creating new directory {} ... '.format(directory))
            rc = self.exec('mkdir {}'.format(directory))
            if rc.failed:
                raise ShipperError('Could not create directory {}'.format(directory))
        except UnexpectedExit as e:
            raise ShipperError() from e

    def dir_exists(self, directory: str):
        cmd = 'test -d {0}'.format(directory)
        return self.exec(cmd)

    def file_exists(self, file: str):
        cmd = 'test -f {0}'.format(file)
        return self.exec(cmd)

    def link_exists(self, file: str):
        cmd = 'test -L {0}'.format(file)
        return self.exec(cmd)

    def can_write_to_dirs(self, *dirs: iter):
        cmd = '-a -w'.join(dirs)
        try:
            return self.exec('test -w {}'.format(cmd))
        except UnexpectedExit as e:
            raise ShipperError() from e

    def init_directories(self):

        deploy_dir = self.cfg('config.base_dir')
        dirs_to_create = self.cfg('config.directories').as_dict()

        if not self.can_write_to_dirs(deploy_dir):
            raise ShipperError('[!] Deployment directory does not exist or cannot be written to')

        for name, path in dirs_to_create.items():
            try:
                dir_exists = self.exec('test -d {}'.format(path))
                if not dir_exists:
                    self.create_directory(path)
            except UnexpectedExit as e:
                raise ShipperError() from e

    def create_revision_dir(self):

        revisions_dir = self.cfg('config.directories.revisions')

        revision_path = os.path.join(revisions_dir, self.cfg('config.revision'))

        rev_exists = self.can_write_to_dirs(revision_path)

        if rev_exists:
            revision_path = revision_path + '-' + str(round(time.time()))

        self.create_directory(revision_path)

        return revision_path

    def copy_source_to_revision(self, revision_dir: str):

        source_dir = self.cfg('config.source_dir')

        if self.dir_exists(source_dir):
            try:
                Log.notice('Copying deploy cache to revision directory')
                self.exec('cp -r {0}/. {1}/'.format(source_dir, revision_dir))
            except UnexpectedExit as e:
                raise ShipperError('[!] Could not copy deploy cache to revision directory') from e

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

    def create_symlink(self, source, target):
        """
        :param source: Absolute path to source
        :param target: Absolute path to symlink
        :return:
        """

        Log.info('Creating symlink for {0} -> {1}'.format(source, target))

        if self.link_exists(target):
            Log.warn('[!] Target {0} is symlink already. deleting.. '.format(target))
            self.exec('unlink {0}'.format(target))

        try:
            if self.file_exists(target):
                Log.warn('[!] Target {0} is file already. deleting.. '.format(target))
                self.exec('rm -f {0}'.format(target))
                Log.success('done')
            if self.dir_exists(target):
                Log.warn('[!] Target {0} is directory already. deleting..'.format(target))
                self.exec('rm -rf {0}'.format(target))

            self.exec('ln -s {0} {1}'.format(source, target))

        except UnexpectedExit as e:
            if self.cfg('config.fail_on_symlink_error') is True:
                Log.error('[!] Could not create symlink {0} -> {1}'.format(source, target))
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

    def establish_current_link(self):
        result = self.exec('test -L && readlink {}'.format(self.cfg('config.active_symlink')))

        if result.ok:
            return result.stdout.rstrip('\n')

        return None


class Event(object):

    events_dispatched = []
    event_instructions: dict = None

    last_event: str = None

    def __init__(self, cfg: Cfg, context: Shipper):
        self.context = context
        try:
            self.event_instructions = cfg('events')
        except KeyError:
            self.event_instructions = None

    def get_dispatched_events(self):
        return self.events_dispatched

    def get_last_dispatched_event(self):
        return self.get_dispatched_events()[-1]

    def _register_event_dispatch(self, event_name: str):
        self.events_dispatched.append(event_name)
        self.last_event = event_name

    def dispatch(self, event_name: str):
        self._register_event_dispatch(event_name)

        if self.event_instructions is None:
            return

        if event_name not in self.event_instructions:
            return

        for execute in self.event_instructions[event_name]:

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
                class_object = getattr(module_object, class_name)(self.context)
                function_object = getattr(class_object, function_name)
            except AttributeError as e:
                raise ShipperError() from e

            function_object()


shipper = Shipper(
    config=args.config
)

shipper.run()
