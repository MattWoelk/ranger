# Copyright (C) 2009, 2010, 2011  Roman Zimbelmann <romanz@lavabit.com>
# This software is distributed under the terms of the GNU GPL version 3.

import os
import sys
from os.path import abspath, normpath, join, expanduser, isdir

from ranger.container.history import History
from ranger.core.shared import FileManagerAware, SettingsAware
from ranger.ext.signals import SignalDispatcher

class Tab(FileManagerAware, SettingsAware):
	def __init__(self, path):
		self.thisdir = None  # Current Working Directory
		self._thisfile = None  # Current File
		self.history = History(self.settings.max_history_size, unique=False)
		self.last_search = None
		self.pointer = 0
		self.path = abspath(expanduser(path))
		self.pathway = ()
		# NOTE: in the line below, weak=True works only in python3.  In python2,
		# weak references are not equal to the original object when tested with
		# "==", and this breaks _set_thisfile_from_signal and _on_tab_change.
		self.fm.signal_bind('move', self._set_thisfile_from_signal, priority=0.1,
				weak=(sys.version > '3'))
		self.fm.signal_bind('tab.change', self._on_tab_change,
				weak=(sys.version > '3'))

	def _set_thisfile_from_signal(self, signal):
		if self == signal.tab:
			self._thisfile = signal.new
			if self == self.fm.thistab:
				self.pointer = self.thisdir.pointer

	def _on_tab_change(self, signal):
		if self == signal.new and self.thisdir:
			# restore the pointer whenever this tab is reopened
			self.thisdir.pointer = self.pointer
			self.thisdir.correct_pointer()

	def _set_thisfile(self, value):
		if value is not self._thisfile:
			previous = self._thisfile
			self.fm.signal_emit('move', previous=previous, new=value, tab=self)

	def _get_thisfile(self):
		return self._thisfile

	thisfile = property(_get_thisfile, _set_thisfile)

	def at_level(self, level):
		"""
		Returns the FileSystemObject at the given level.
		level >0 => previews
		level 0 => current file/directory
		level <0 => parent directories
		"""
		if level <= 0:
			try:
				return self.pathway[level - 1]
			except IndexError:
				return None
		else:
			directory = self.thisfile
			for i in range(level - 1):
				if directory is None:
					return None
				if directory.is_directory:
					directory = directory.pointed_obj
				else:
					return None
			try:
				return self.fm.directories[directory.path]
			except AttributeError:
				return None
			except KeyError:
				return directory

	def get_selection(self):
		if self.thisdir:
			return self.thisdir.get_selection()
		return set()

	def assign_cursor_positions_for_subdirs(self):
		"""Assign correct cursor positions for subdirectories"""
		last_path = None
		for path in reversed(self.pathway):
			if last_path is None:
				last_path = path
				continue

			path.move_to_obj(last_path)
			last_path = path

	def ensure_correct_pointer(self):
		if self.thisdir:
			self.thisdir.correct_pointer()

	def history_go(self, relative):
		"""Move relative in history"""
		if self.history:
			self.history.move(relative).go(history=False)

	def inherit_history(self, other_history):
		self.history.rebase(other_history)

	def enter_dir(self, path, history = True):
		"""Enter given path"""
		# TODO: Ensure that there is always a self.thisdir
		if path is None: return
		path = str(path)

		previous = self.thisdir

		# get the absolute path
		path = normpath(join(self.path, expanduser(path)))

		if not isdir(path):
			return False
		new_thisdir = self.fm.get_directory(path)

		try:
			os.chdir(path)
		except:
			return True
		self.path = path
		self.thisdir = new_thisdir

		self.thisdir.load_content_if_outdated()

		# build the pathway, a tuple of directory objects which lie
		# on the path to the current directory.
		if path == '/':
			self.pathway = (self.fm.get_directory('/'), )
		else:
			pathway = []
			currentpath = '/'
			for dir in path.split('/'):
				currentpath = join(currentpath, dir)
				pathway.append(self.fm.get_directory(currentpath))
			self.pathway = tuple(pathway)

		self.assign_cursor_positions_for_subdirs()

		# set the current file.
		self.thisdir.sort_directories_first = self.fm.settings.sort_directories_first
		self.thisdir.sort_reverse = self.fm.settings.sort_reverse
		self.thisdir.sort_if_outdated()
		self._thisfile = self.thisdir.pointed_obj

		if history:
			self.history.add(new_thisdir)

		self.fm.signal_emit('cd', previous=previous, new=self.thisdir)

		return True

	def __repr__(self):
		return "<Tab '%s'>" % self.thisdir
