#!/usr/bin/env python3

import os
import time
import subprocess
import json
import argparse
import yaml
from distutils.dir_util import copy_tree
from importlib import import_module

parser = argparse.ArgumentParser(description='description')
parser.add_argument('--revision',
                    dest='revision',
                    action='store',
                    default=None,
                    help='(required) accepts a string ID for this revision')
parser.add_argument('--deploy-dir',
                    dest='deploydir',
                    action='store',
                    default=os.path.dirname(os.path.realpath(__file__)),
                    help='Base directory for deployment')
parser.add_argument('--deploy-cache-dir',
                    dest='deploycachedir',
                    action='store',
                    default=None,
                    help='Directory in which the deployed files are initially deploy')
parser.add_argument('--revisions-to-keep',
                    dest='revisionstokeep',
                    action='store',
                    type=int,
                    default=None,
                    help='number of old revisions to keep in addition to the current revision')
parser.add_argument('--symlinks',
                    dest='symlinks',
                    action='store',
                    default=None,
                    help='a JSON hash of symbolic links to be created in the revision directory (default: {} )')

args = parser.parse_args()


class Deployer():

  deployPath = None
  revisionPath = None

  directories = {
    'revisions': 'revisions',
    'shared': 'shared',
    'config': 'shared/config'
  }

  def __init__(self):
    pass


  def run(self, deployDir, deployCacheDir, revision, revisionsToKeep, symLinks, pluginPath):
    try:

      self.initDirectories(deployDir)
      print('Creating atomic deployment directories..')

      self.dispatchEvent('after:initDirectories', pluginPath)

      self.createRevisionDir(revision)
      print('Creating new revision directory..')

      self.copyCacheToRevision(deployCacheDir)
      print('Copying deploy-cache to new revision directory..')

      self.createSymlinks(symLinks)
      print('Creating symlinks within new revision directory..')

      self.linkCurrentRevision()
      print('Switching over to latest revision')

      self.pruneOldRevisions(revisionsToKeep)
      print('Pruning old revisions')

      result = True
    except Exception:
      result = False

    return result


  def initDirectories(self, deployDir):
    if os.path.exists(deployDir) is True:
      self.deployPath = deployDir.rstrip("/")
    else:
      self.deployPath = ''

    if not os.access(deployDir, os.W_OK) is True:
      raise RuntimeError('The deploy directory ' + deployDir + 'is not writable')

    if not os.path.isdir(self.directories['revisions']) is True:
      try:
        os.mkdir(self.directories['revisions'])
      except RuntimeError as e:
        raise RuntimeError('Could not create revisions directory: ' + repr(e))

    if not os.path.isdir(self.directories['shared']) is True:
      try:
        os.mkdir(self.directories['shared'])
      except RuntimeError as e:
        raise RuntimeError('Could not create shared directory: ' + repr(e))

    if not os.path.isdir(self.directories['config']) is True:
      try:
        os.makedirs(self.directories['config'])
      except RuntimeError as e:
        raise RuntimeError('Could not create revisions directory. ' + repr(e))


  def createRevisionDir(self, revision):
    self.revisionPath = os.path.join(self.deployPath, self.directories['revisions'], revision)
    self.revisionPath = self.revisionPath.rstrip("/")

    if os.path.isdir(os.path.realpath(self.revisionPath)):
      self.revisionPath = self.revisionPath + '-' + time.time()

    if not os.path.isdir(self.revisionPath) is True:
      try:
        os.mkdir(self.revisionPath)
      except RuntimeError:
        raise RuntimeError('Could not create revision directory; ' + self.revisionPath)

    if not os.access(self.revisionPath, os.W_OK) is True:
      raise RuntimeError('The revision directory ' + self.revisionPath + 'is not writable')


  def copyCacheToRevision(self, deployCacheDir):
    try:
      if os.path.isdir(deployCacheDir) is True:
        copy_tree(deployCacheDir, self.revisionPath)
    except subprocess.CalledProcessError as e:
       print("Could not copy deploy cache to revision directory" + repr(e))


  def createSymlinks(self, rawJsonString):

    if rawJsonString is None:
      return

    symLinks = json.loads(rawJsonString)

    for (k, v) in symLinks.items():
      print(1)
      t = self.deployPath + "/" + k
      l = self.revisionPath + "/" + v

      try:
        self.createSymlink(t, l)
      except Exception as e:
        raise Exception("Could not create symlink " + t + " -> " + l + ": " + repr(e))


  def dispatchEvent(self, eventName, pluginPath):
    with open('plugin.yml', 'r') as ymlfile:
      yml = yaml.load(ymlfile)

    if not eventName in yml:
      return

    if not 'path' in eventName:
      print('Missing \'path\' parameter in event: ' + eventName )

    path = yml[eventName]['path']

    className = path.split(' ')[1].split('/')[0]
    moduleName = path.split(' ')[0].replace("/", ".")

    plugin = __import__(moduleName)
    try:
      pluginClass = getattr(plugin, className)
    except AttributeError:
      print('Failed retrieving plugin class: ' + className)
      return False

    for functionName in yml[eventName]['execute']:
          try:
              functionObject = getattr(pluginClass, functionName)
              functionObject()
          except AttributeError:
              print('Failed retrieving plugin class function: ' + functionName)
              return False


  def createSymlink(self, target, link):
    if os.path.exists(link):
      subprocess.call('rm -rf ' + link)

    try:
      os.symlink(target,link)
    except Exception as e:
      print("Could not create symlink " + target + " -> " + link + ": " + repr(e))


  def pruneOldRevisions(self, revisionsToKeep):
    if revisionsToKeep > 0:
      revisionsDir = self.deployPath + '/' + self.directories['revisions']

      rmIndex = revisionsToKeep + 2

      try:
        subprocess.check_call("ls -1dtp "+revisionsDir+"/** | tail -n +"+rmIndex+" | tr " + '\'\n\' \'\0\'' + " | xargs -0 rm -rf --", check=True)
      except subprocess.CalledProcessError as e:
        print('Could not prune old revisions ' + repr(e))


  def linkCurrentRevision(self):
    revisionTarget = self.revisionPath
    currentLink = self.deployPath + '/' + 'current'
    try:
      self.createSymlink(revisionTarget, currentLink)
    except Exception as e:
      print('Could not create current symlink: ' + repr(e))

deployer = Deployer()

deployer.run(args.deploydir, args.deploycachedir, args.revision, args.revisionstokeep, args.symlinks, args.plugin)
