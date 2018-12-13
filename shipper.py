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
                    default=5,
                    help='number of old revisions to keep in addition to the current revision')
parser.add_argument('--symlinks',
                    dest='symlinks',
                    action='store',
                    default='{}',
                    help='a JSON hash or filename of symbolic links to be created in the revision directory (default: {} )')
parser.add_argument('--plugin',
                    dest='plugin',
                    action='store',
                    default=os.path.dirname(os.path.realpath(__file__)) + '/plugin.yml',
                    help='file path to the plugin file (default: plugin.yml)')

args = parser.parse_args()


class Deployer():

  deployPath = None
  revisionPath = None

  directories = {
    'revisions': 'revisions',
    'share': 'share',
    'config': 'share/config',
  }

  def __init__(self):
    pass

  def run(self, deployDir, deployCacheDir, revision, revisionsToKeep, symLinks, pluginPath):
    try:

      # -------------------------------------------------------------
      self.dispatchEvent('before:initDirectories', pluginPath)
      print('Creating atomic deployment directories..')
      self.initDirectories(deployDir)
      self.dispatchEvent('after:initDirectories', pluginPath)
      # -------------------------------------------------------------
      self.dispatchEvent('before:createRevisionDir', pluginPath)
      print('Creating new revision directory..')
      self.createRevisionDir(revision)
      self.dispatchEvent('after:createRevisionDir', pluginPath)
      # -------------------------------------------------------------
      self.dispatchEvent('before:copyCacheToRevision', pluginPath)
      self.copyCacheToRevision(deployCacheDir)
      print('Copying deploy-cache to new revision directory..')
      self.dispatchEvent('after:copyCacheToRevision', pluginPath)
      # -------------------------------------------------------------
      self.dispatchEvent('before:createSymlinks', pluginPath)
      print('Creating symlinks within new revision directory..')
      self.createSymlinks(symLinks)
      self.dispatchEvent('after:createSymlinks', pluginPath)
      # -------------------------------------------------------------
      self.dispatchEvent('before:linkCurrentRevision', pluginPath)
      print('Switching over to latest revision')
      self.linkCurrentRevision()
      self.dispatchEvent('after:linkCurrentRevision', pluginPath)
      # -------------------------------------------------------------
      self.dispatchEvent('before:pruneOldRevisions', pluginPath)
      print('Purging old revisions')
      self.purgeOldRevisions(revisionsToKeep)
      self.dispatchEvent('after:pruneOldRevisions', pluginPath)
      # -------------------------------------------------------------

      print('Done.')

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
      print('The deploy directory ' + deployDir + 'is not writable')

    if not os.path.isdir(self.directories['revisions']) is True:
      try:
        os.mkdir(self.directories['revisions'])
      except RuntimeError as e:
        print('Could not create revisions directory: ' + repr(e))

    if not os.path.isdir(self.directories['share']) is True:
      try:
        os.mkdir(self.directories['share'])
      except RuntimeError as e:
        print('Could not create share directory: ' + repr(e))

    if not os.path.isdir(self.directories['config']) is True:
      try:
        os.makedirs(self.directories['config'])
      except RuntimeError as e:
        print('Could not create revisions directory. ' + repr(e))


  def createRevisionDir(self, revision):
    self.revisionPath = os.path.join(self.deployPath, self.directories['revisions'], revision)
    self.revisionPath = self.revisionPath.rstrip("/")

    if os.path.isdir(os.path.realpath(self.revisionPath)) is True:
      self.revisionPath = self.revisionPath + '-' + str(time.time())

    if not os.path.isdir(self.revisionPath) is True:
      try:
        os.mkdir(self.revisionPath)
      except Exception:
        print('Could not create revision directory; ' + self.revisionPath)
        sys.exit(1)
    else:
      print('EMERGENCY ABORT: revision directory already exists. Aborting')
      sys.exit(1)

    if not os.access(self.revisionPath, os.W_OK) is True:
      print('The revision directory ' + self.revisionPath + 'is not writable')


  def copyCacheToRevision(self, deployCacheDir):
    if os.path.isdir(deployCacheDir) is True:
      try:
        print('Copying deploy cache to revision directory')
        copy_tree(deployCacheDir, self.revisionPath)
      except subprocess.CalledProcessError as e:
        print('Could not copy deploy cache to revision directory' + repr(e))


  def createSymlinks(self, rawJsonString):

    if os.path.isfile(self.deployPath + '/' + rawJsonString) is True:
      print('Json is file')
      try:
        with open(rawJsonString, 'r') as fh:
          symLinks = json.load(fh)
      except Exception as e:
        print('Failed reading json data: ' + repr(e))
        return
    else:
      print('Json is string')
      try:
        symLinks = json.loads(rawJsonString)
      except Exception as e:
        print('Failed reading json data: ' + repr(e))
        return

    for (k, v) in symLinks.items():
      t = self.deployPath + '/' + k
      l = self.revisionPath + '/' + v

      # try inside here or in target function? ask Ian
      try:
        self.createSymlink(t, l)
      except Exception as e:
        print('Could not create symlink ' + t + ' -> ' + l + ': ' + repr(e))


  def dispatchEvent(self, eventName, pluginPath):
    try:
      with open(pluginPath, 'r') as ymlfile:
        yml = yaml.load(ymlfile)
    except Exception as e:
      print('Failed opening pugin file: ' + pluginPath + ' ' + repr(e))
      return

    if not eventName in yml:
      return

    for string in yml[eventName]['execute']:
      moduleName = string.split('.')

      functionName = moduleName[-1]
      className = moduleName[-2]
      moduleName = '.'.join(moduleName[:-2])
      try:
        moduleObject = import_module(moduleName)
      except ModuleNotFoundError as e:
        print('No such module was found: ' + moduleName)
        return False

      try:
        classObject = getattr(moduleObject, className)()
        functionObject = getattr(classObject, functionName)
      except AttributeError as e:
        print('AttributeError: ' + repr(e))
        return False

      functionObject()


  def createSymlink(self, target, link):
    if os.path.islink(link):
      os.unlink(link)

    try:
      if os.path.isfile(link) is True:
        print('deleting file')
        os.remove(link)
      if os.path.isdir(link) is True:
        print('removing dir')
        shutil.rmtree(link)
      os.symlink(target,link)
    except Exception as e:
      print('Could not create symlink ' + target + ' -> ' + link + ': ' + repr(e))


  def purgeOldRevisions(self, revisionsToKeep):
    if revisionsToKeep > 0:
      revisionsDir = self.deployPath + '/' + self.directories['revisions']

      rmIndex = revisionsToKeep + 2

      name_list = os.listdir(revisionsDir)
      full_list = [os.path.join(revisionsDir, i)
                   for i in name_list]
      date_sorted = sorted(full_list, key=os.path.getmtime)

      currentDirCount = len(date_sorted)
      loopCount = currentDirCount - rmIndex

      if currentDirCount > rmIndex:
        for v in date_sorted[:loopCount]:
          print('└ ' + v)
          shutil.rmtree(v)


  def linkCurrentRevision(self):
    revisionTarget = self.revisionPath
    currentLink = self.deployPath + '/' + 'current'
    try:
      self.createSymlink(revisionTarget, currentLink)
    except FileNotFoundError as e:
      print(repr(e))

deployer = Deployer()

deployer.run(
  args.deploydir,
  args.deploycachedir,
  args.revision,
  args.revisionstokeep,
  args.symlinks,
  args.plugin
  )
