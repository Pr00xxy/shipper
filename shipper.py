#!/usr/bin/env python3

import os
import time
import subprocess
import json
import argparse
import shutil
import yaml
import sys
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


class Deployer():
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
            print('Creating atomic deployment directories..')
            self.init_directories()
            self.dispatch_event('after:init_directories')
            # -------------------------------------------------------------
            self.dispatch_event('before:create_revision_dir')
            print('Creating new revision directory..')
            self.create_revision_dir()
            self.dispatch_event('after:create_revision_dir')
            # -------------------------------------------------------------
            self.dispatch_event('before:copy_cache_to_revision')
            self.copy_cache_to_revision()
            print('Copying deploy-cache to new revision directory..')
            self.dispatch_event('after:copy_cache_to_revision')
            # -------------------------------------------------------------
            self.dispatch_event('before:create_symlinks')
            print('Creating symlinks within new revision directory..')
            self.create_symlinks()
            self.dispatch_event('after:create_symlinks')
            # -------------------------------------------------------------
            self.dispatch_event('before:link_current_revision')
            print('Switching over to latest revision')
            self.link_current_revision()
            self.dispatch_event('after:link_current_revision')
            # -------------------------------------------------------------
            self.dispatch_event('before:purge_old_revisions')
            print('Purging old revisions')
            self.purge_old_revisions()
            self.dispatch_event('after:purge_old_revisions')
            # -------------------------------------------------------------

            print('Done.')

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
            raise SystemExit('[!] Deployment directory does not exist.')

        if not os.access(self.deploy_dir, os.W_OK) is True:
            raise SystemExit('[!] The deploy directory {0} is not writable'.format(self.deploy_dir))

        for k, v in dirs_to_create:
            if not os.path.isdir(v):
                print('[!] {0} missing. Trying to create...'.format(v))
                try:
                    os.makedirs(v)
                    print('success')
                except RuntimeError as e:
                    raise SystemExit('[!] Could not create {0} {1}'.format(k, repr(e))) from e

    def create_revision_dir(self):
        self.revision_path = os.path.join(self.deploy_dir, self.directories['revisions'], self.revision)
        self.revision_path = self.revision_path.rstrip("/")

        if os.path.isdir(os.path.realpath(self.revision_path)) is True:
            self.revision_path = self.revision_path + '-' + str(time.time())

        if not os.path.isdir(self.revision_path) is True:
            try:
                os.mkdir(self.revision_path)
            except Exception as e:
                raise SystemExit('[!] Could not create revision directory: {0}'.format(self.revision_path)) from e
        else:
            print('Revision directory already exists.')

        if not os.access(self.revision_path, os.W_OK) is True:
            raise SystemExit('[!] The revision directory {0} is not writable'.format(self.revision_path))

    def copy_cache_to_revision(self):
        if os.path.isdir(self.deploy_cache_dir) is True:
            try:
                print('Copying deploy cache to revision directory')
                copy_tree(self.deploy_cache_dir, self.revision_path)
            except subprocess.CalledProcessError as e:
                raise SystemExit('[!] Could not copy deploy cache to revision directory') from e

    def create_symlinks(self):
        if os.path.isfile(self.symlinks) is True:
            try:
                with open(self.symlinks, 'r') as fh:
                    symlink_data = json.load(fh)
            except Exception as e:
                print('[!] Failed reading json data: {0}'.format(repr(e)))
        else:  # Try loading the json as is if given data is not a file
            try:
                symlink_data = json.loads(self.symlinks)
            except Exception as e:
                print('[!] Failed reading json data: {0}'.format(repr(e)))

        if symlink_data is None:
            return

        for (k, v) in symlink_data.items():
            t = os.path.join(self.deploy_dir, k)
            l = os.path.join(self.revision_path, v)

            try:
                self.create_symlink(t, l)
            except Exception:
                print('[!] Could not create symlink {0} -> {1}'.format(t, l))

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
                except ModuleNotFoundError as e:
                    print('[!] No such module was found: {0}'.format(module_name))
                    return False

                try:
                    class_object = getattr(module_object, class_name)(self)
                    function_object = getattr(class_object, function_name)
                except AttributeError as e:
                    raise SystemExit(repr(e))

                function_object()

    def create_symlink(self, target, link):
        print('Creating symlink for {0} -> {1}'.format(link, target))
        if os.path.islink(link):
            print('[!] Target {0} is symlink already. deleting..'.format(link))
            os.unlink(link)
            print('done')

        try:
            if os.path.isfile(link) is True:
                print('[!] Target {0} is file already. deleting..'.format(link))
                os.remove(link)
            if os.path.isdir(link) is True:
                print('[!] Target {0} is directory already. deleting..'.format(link))
                shutil.rmtree(link)
            os.symlink(target, link)
        except (Exception, FileNotFoundError):
            print('[!] Could not create symlink {0} -> {1}'.format(target, link))

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
                    print('* ' + v)
                    try:
                        if os.path.isdir(v) is True:
                            shutil.rmtree(v)
                        else:
                            print('[!] Failed deleting {0}. not a directory'.format(v))
                    except (NotADirectoryError, OSError) as e:
                        print(repr(e))

    def link_current_revision(self):
        self.create_symlink(self.revision_path,os.path.join(self.deploy_dir, 'current'))


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
