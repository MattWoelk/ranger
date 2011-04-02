# Copyright (C) 2009, 2010  Roman Zimbelmann <romanz@lavabit.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
from collections import deque
from ranger.api import *
from ranger.core.shared import FileManagerAware
from ranger.ext.lazy_property import lazy_property

class CommandContainer(object):
	def __init__(self):
		self.commands = {}
		self.aliases = {}

	def __getitem__(self, key):
		return self.commands[key]

	def alias(self, new, old):
		if old in self.commands:
			self.commands[new] = self.commands[old]
			self.aliases[new] = old

	def register(self, command):
		classdict = command.__mro__[0].__dict__
		if 'name' in classdict and classdict['name']:
			self.commands[classdict['name']] = command
		else:
			self.commands[command.__name__] = command

	def load_commands_from_module(self, module):
		for var in vars(module).values():
			try:
				if issubclass(var, Command) and var != Command:
					self.register(var)
			except TypeError:
				pass
		if hasattr(module, 'aliases'):
			if hasattr(module.aliases, 'items'):
				for key, val in module.aliases.items():
					self.alias(key, val)

	def get_command(self, name, abbrev=True):
		if abbrev:
			lst = [cls for cmd, cls in self.commands.items() \
					if cls.allow_abbrev and cmd.startswith(name) \
					or cmd == name]
			if len(lst) == 0:
				raise KeyError
			if len(lst) == 1:
				return lst[0]
			if self.commands[name] in lst:
				return self.commands[name]
			raise ValueError("Ambiguous command")
		else:
			try:
				return self.commands[name]
			except KeyError:
				return None

	def command_generator(self, start):
		return (cmd + ' ' for cmd in self.commands if cmd.startswith(start))


class Command(FileManagerAware):
	"""Abstract command class"""
	name = None
	resolve_macros = True
	allow_abbrev = True
	_shifted = 0

	def setargs(self, line, pos=None, n=None):
		self.line = line
		self.args = line.split()
		self.n = n
		if pos is None:
			self.pos = len(line)
		else:
			self.pos = pos
		return self

	def execute(self):
		"""Override this"""

	def tab(self):
		"""Override this"""

	def quick(self):
		"""Override this"""

	# Easy ways to get information
	def arg(self, n):
		"""Returns the nth space separated word"""
		try:
			return self.args[n]
		except IndexError:
			return ""

	def rest(self, n):
		"""Returns everything from and after arg(n)"""
		got_space = False
		word_count = 0
		for i in range(len(self.line)):
			if self.line[i] == " ":
				if not got_space:
					got_space = True
					word_count += 1
			elif got_space:
				got_space = False
				if word_count == n + self._shifted:
					return self.line[i:]
		return ""

	def start(self, n):
		"""Returns everything until (inclusively) arg(n)"""
		return ' '.join(self.args[:n]) + " " # XXX

	def shift(self):
		del self.args[0]
		self._shifted += 1

	def tabinsert(self, word):
		return ''.join([self._tabinsert_left, word, self._tabinsert_right])

	@lazy_property
	def _tabinsert_left(self):
		try:
			return self.line[:self.line[0:self.pos].rindex(' ') + 1]
		except ValueError:
			return ''

	@lazy_property
	def _tabinsert_right(self):
		return self.line[self.pos:]

	# Tab stuff
	# COMPAT: this is still used in old commands.py configs
	def _tab_only_directories(self):
		from os.path import dirname, basename, expanduser, join, isdir

		cwd = self.fm.env.cwd.path

		try:
			rel_dest = self.rest(1)
		except IndexError:
			rel_dest = ''

		# expand the tilde into the user directory
		if rel_dest.startswith('~'):
			rel_dest = expanduser(rel_dest)

		# define some shortcuts
		abs_dest = join(cwd, rel_dest)
		abs_dirname = dirname(abs_dest)
		rel_basename = basename(rel_dest)
		rel_dirname = dirname(rel_dest)

		try:
			# are we at the end of a directory?
			if rel_dest.endswith('/') or rel_dest == '':
				_, dirnames, _ = next(os.walk(abs_dest))

			# are we in the middle of the filename?
			else:
				_, dirnames, _ = next(os.walk(abs_dirname))
				dirnames = [dn for dn in dirnames \
						if dn.startswith(rel_basename)]
		except (OSError, StopIteration):
			# os.walk found nothing
			pass
		else:
			dirnames.sort()

			# no results, return None
			if len(dirnames) == 0:
				return

			# one result. since it must be a directory, append a slash.
			if len(dirnames) == 1:
				return self.start(1) + join(rel_dirname, dirnames[0]) + '/'

			# more than one result. append no slash, so the user can
			# manually type in the slash to advance into that directory
			return (self.start(1) + join(rel_dirname, dirname) \
				for dirname in dirnames)

	def _tab_directory_content(self):
		from os.path import dirname, basename, expanduser, join, isdir

		cwd = self.fm.env.cwd.path

		try:
			rel_dest = self.rest(1)
		except IndexError:
			rel_dest = ''

		# expand the tilde into the user directory
		if rel_dest.startswith('~'):
			rel_dest = expanduser(rel_dest)

		# define some shortcuts
		abs_dest = join(cwd, rel_dest)
		abs_dirname = dirname(abs_dest)
		rel_basename = basename(rel_dest)
		rel_dirname = dirname(rel_dest)

		try:
			# are we at the end of a directory?
			if rel_dest.endswith('/') or rel_dest == '':
				_, dirnames, filenames = next(os.walk(abs_dest))
				names = dirnames + filenames

			# are we in the middle of the filename?
			else:
				_, dirnames, filenames = next(os.walk(abs_dirname))
				names = [name for name in (dirnames + filenames) \
						if name.startswith(rel_basename)]
		except (OSError, StopIteration):
			# os.walk found nothing
			pass
		else:
			names.sort()

			# no results, return None
			if len(names) == 0:
				return

			# one result. since it must be a directory, append a slash.
			if len(names) == 1:
				return self.start(1) + join(rel_dirname, names[0]) + '/'

			# more than one result. append no slash, so the user can
			# manually type in the slash to advance into that directory
			return (self.start(1) + join(rel_dirname, name) for name in names)
