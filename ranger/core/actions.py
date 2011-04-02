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
import re
import shutil
import string
from inspect import cleandoc
from os.path import join, isdir, realpath
from os import link, symlink, getcwd
from time import time

from ranger.core import *

import ranger
from ranger.ext.direction import Direction
from ranger.core.info import Info
from ranger.ext.relative_symlink import relative_symlink
from ranger.ext.shell_escape import shell_quote
from ranger import fsobject
from ranger.core.shared import FileManagerAware, EnvironmentAware, \
		SettingsAware
from ranger.fsobject import File
from ranger.core.loader import CommandLoader

class Actions(FileManagerAware, EnvironmentAware, SettingsAware):
	search_method = 'ctime'
	search_forward = False
	input_blocked = False
	input_blocked_until = 0
	visual = None
	_visual_start = None
	_visual_start_pos = None
	_previous_selection = None

	# --------------------------
	# -- Basic Commands
	# --------------------------

	def exit(self):
		"""Exit the program"""
		raise SystemExit()

	def err(self, *args):
		if self.debug and isinstance(args[0], Exception):
			raise
		elif self.ui_runs:
			self.ui.notify(*args, bad=True)
			self.log.append(str(args))
		else:
			Info.err(self, *args)

	def write(self, string):
		if self.ui_runs:
			self.ui.notify(string)
			self.log.append(str(string))
		else:
			Info.write(self, string)

	def reset(self):
		"""Reset the filemanager, clearing the directory buffer"""
		old_path = self.env.cwd.path
		self.previews = {}
		self.env.garbage_collect(-1)
		self.fm.visual = None
		self.enter_dir(old_path)

	def visual_start(self, reverse=False):
		"""Start the visual mode"""
		self.visual = reverse
		self._visual_start = self.env.cwd.pointed_obj
		self._visual_start_pos = self.env.cwd.pointer
		self._previous_selection = set(self.env.cwd.marked_items)
		self.mark(val=reverse, movedown=False)

	def visual_end(self):
		self.visual = None

	def reload_cwd(self):
		try:
			cwd = self.env.cwd
		except:
			pass
		cwd.unload()
		cwd.load_content()

	def notify(self, text, duration=4, bad=False):
		if isinstance(text, Exception):
			if ranger.info.debug:
				raise
			bad = True
		text = str(text)
		self.log.appendleft(text)
		if hasattr(self.ui, 'notify'):
			self.ui.notify(text, duration=duration, bad=bad)

	def redraw_window(self):
		"""Redraw the window"""
		self.ui.redraw_window()

	def open_console(self, string='', prompt=None, position=None):
		"""Open the console if the current UI supports that"""
		if hasattr(self.ui, 'open_console'):
			self.ui.open_console(string, prompt=prompt, position=position)

	def execute_console(self, string=''):
		"""Execute a command for the console"""
		self.open_console(string=string)
		self.ui.console.line = string
		self.ui.console.execute()

	def display_in_pager(self, string):
		from subprocess import Popen, PIPE
		from ranger.ext.waitpid_no_intr import waitpid_no_intr
		import math
		self.ui.suspend()
		p = Popen(self.macros['pager'], shell=True, stdin=PIPE)
		bytes = 1024
		py3 = self.fm.py3
		for i in range(int(math.ceil(len(string) / float(bytes)))):
			if py3:
				p.stdin.write(string[i*bytes:i*bytes+bytes].encode('utf-8'))
			else:
				p.stdin.write(string[i*bytes:i*bytes+bytes])
		p.stdin.close()
		waitpid_no_intr(p.pid)
		self.ui.initialize()


	# --------------------------
	# -- Moving Around
	# --------------------------

	def move(self, narg=None, **kw):
		"""
		A universal movement method.

		Accepts these parameters:
		(int) down, (int) up, (int) left, (int) right, (int) to,
		(bool) absolute, (bool) relative, (bool) pages,
		(bool) percentage

		to=X is translated to down=X, absolute=True

		Example:
		self.move(down=4, pages=True)  # moves down by 4 pages.
		self.move(to=2, pages=True)  # moves to page 2.
		self.move(to=1, percentage=True)  # moves to 80%
		"""
		cwd = self.env.cwd
		direction = Direction(kw)
		if 'left' in direction or direction.left() > 0:
			steps = direction.left()
			if narg is not None:
				steps *= narg
			try:
				directory = os.path.join(*(['..'] * steps))
			except:
				return
			self.fm.visual = None
			self.env.enter_dir(directory)
		if cwd and cwd.accessible and cwd.content_loaded:
			if 'right' in direction:
				mode = 0
				if narg is not None:
					mode = narg
				cf = self.env.cf
				selection = self.env.get_selection()
				self.fm.visual = None
				if not self.env.enter_dir(cf) and selection:
					pass
			elif direction.vertical():
				oldpos = cwd.pointer
				newpos = direction.move(
						direction=direction.down(),
						override=narg,
						maximum=len(cwd),
						current=cwd.pointer,
						pagesize=self.ui.browser.hei)
				cwd.move(to=newpos)
				if self.visual is not None:
					try:
						startpos = cwd.index(self._visual_start)
					except:
						self._visual_start = None
						startpos = min(self._visual_start_pos, len(cwd))
					new_selection = set(cwd.files[min(startpos, newpos):\
							max(startpos, newpos) + 1])
					old_selection = self._previous_selection
					cur_selection = set(cwd.marked_items)
					if self.visual:
						for f in new_selection - cur_selection:
							cwd.mark_item(f, True)
						for f in cur_selection - old_selection - new_selection:
							cwd.mark_item(f, False)
					else:
						for f in old_selection - cur_selection - new_selection:
							cwd.mark_item(f, True)
						for f in new_selection - cur_selection:
							cwd.mark_item(f, False)

	def move_parent(self, n):
		parent = self.env.at_level(-1)
		if parent.pointer + n < 0:
			n = 0 - parent.pointer
		try:
			self.fm.visual = None
			self.env.enter_dir(parent.files[parent.pointer+n])
		except IndexError:
			pass

	def history_go(self, relative):
		"""Move back and forth in the history"""
		self.env.history_go(relative)

	def scroll(self, relative):
		"""Scroll down by <relative> lines"""
		if hasattr(self.ui, 'scroll'):
			self.ui.scroll(relative)
			self.env.cf = self.env.cwd.pointed_obj

	def enter_dir(self, path, remember=False, history=True):
		"""Enter the directory at the given path"""
		if remember:
			self.fm.visual = None
			cwd = self.env.cwd
			result = self.env.enter_dir(path, history=history)
			self.bookmarks.remember(cwd)
			return result
		return self.env.enter_dir(path, history=history)

	def cd(self, path, remember=True):
		"""enter the directory at the given path, remember=True"""
		self.fm.visual = None
		self.enter_dir(path, remember=remember)

	def traverse(self):
		cf = self.env.cf
		cwd = self.env.cwd
		if cf is not None and cf.is_directory:
			self.fm.visual = None
			self.enter_dir(cf.path)
		elif cwd.pointer >= len(cwd) - 1:
			while True:
				self.move(left=1)
				cwd = self.env.cwd
				if cwd.pointer < len(cwd) - 1:
					break
				if cwd.path == '/':
					break
			self.move(down=1)
			self.traverse()
		else:
			self.move(down=1)
			self.traverse()

	# --------------------------
	# -- Shortcuts / Wrappers
	# --------------------------

	def execute_command(self, cmd, **kw):
		return self.run(cmd, **kw)

	def edit_file(self, path=None):
		"""Opens the current file with %editor"""
		if path is None:
			path = self.env.cf.path
		self.execute_command("%s %s" % (self.macros['editor'],
			shell_quote(path)))

	def hint(self, text):
		self.ui.hint(text)

	def toggle_boolean_option(self, string):
		"""Toggle a boolean option named <string>"""
		if isinstance(self.env.settings[string], bool):
			self.env.settings[string] ^= True

	def set_option(self, optname, value):
		"""Set the value of an option named <optname>"""
		self.env.settings[optname] = value

	def sort(self, func=None, reverse=None):
		if reverse is not None:
			self.env.settings['sort_reverse'] = bool(reverse)

		if func is not None:
			self.env.settings['sort'] = str(func)

	def set_filter(self, fltr):
		try:
			self.env.cwd.filter = fltr
		except:
			pass

	def mark(self, all=False, toggle=False, val=None, movedown=None, narg=1):
		"""
		A wrapper for the directory.mark_xyz functions.

		Arguments:
		all - change all files of the current directory at once?
		toggle - toggle the marked-status?
		val - mark or unmark?
		"""

		if self.env.cwd is None:
			return

		cwd = self.env.cwd

		if not cwd.accessible:
			return

		if movedown is None:
			movedown = not all

		if val is None and toggle is False:
			return

		if all:
			if toggle:
				cwd.toggle_all_marks()
			else:
				cwd.mark_all(val)
		else:
			for i in range(cwd.pointer, min(cwd.pointer + narg, len(cwd))):
				item = cwd.files[i]
				if item is not None:
					if toggle:
						cwd.toggle_mark(item)
					else:
						cwd.mark_item(item, val)

		if movedown:
			self.move(down=narg)

		if hasattr(self.ui, 'redraw_main_column'):
			self.ui.redraw_main_column()
		if hasattr(self.ui, 'status'):
			self.ui.status.need_redraw = True

	def mark_in_direction(self, val=True, dirarg=None):
		cwd = self.env.cwd
		direction = Direction(dirarg)
		pos, selected = direction.select(lst=cwd.files, current=cwd.pointer,
				pagesize=self.env.termsize[0])
		cwd.pointer = pos
		cwd.correct_pointer()
		for item in selected:
			cwd.mark_item(item, val)

	def block_input(self, sec=0):
		self.input_blocked = sec != 0
		self.input_blocked_until = time() + sec

	def input_is_blocked(self):
		if self.input_blocked and time() > self.input_blocked_until:
			self.input_blocked = False
		return self.input_blocked

	# --------------------------
	# -- Searching
	# --------------------------

	def search_file(self, text, offset=1, regexp=True):
		if isinstance(text, str) and regexp:
			try:
				text = re.compile(text, re.L | re.U | re.I)
			except:
				return False
		self.env.last_search = text
		self.search(order='search', offset=offset)

	def search(self, order=None, offset=1, forward=True):
		original_order = order
		if self.search_forward:
			direction = bool(forward)
		else:
			direction = not bool(forward)

		if order is None:
			order = self.search_method
		else:
			self.set_search_method(order=order)

		if order in ('search', 'tag'):
			if order == 'search':
				arg = self.env.last_search
				if arg is None:
					return False
				if hasattr(arg, 'search'):
					fnc = lambda x: arg.search(x.basename)
				else:
					fnc = lambda x: arg in x.basename
			elif order == 'tag':
				fnc = lambda x: x.realpath in self.tags

			return self.env.cwd.search_fnc(fnc=fnc, offset=offset, forward=forward)

		elif order in ('size', 'mimetype', 'ctime'):
			cwd = self.env.cwd
			if original_order is not None or not cwd.cycle_list:
				lst = list(cwd.files)
				if order == 'size':
					fnc = lambda item: -item.size
				elif order == 'mimetype':
					fnc = lambda item: item.mimetype
				elif order == 'ctime':
					fnc = lambda item: -int(item.stat and item.stat.st_ctime)
				lst.sort(key=fnc)
				cwd.set_cycle_list(lst)
				return cwd.cycle(forward=None)

			return cwd.cycle(forward=forward)

	def set_search_method(self, order, forward=True):
		if order in ('search', 'tag', 'size', 'mimetype', 'ctime'):
			self.search_method = order
			self.search_forward = forward

	# --------------------------
	# -- Tags
	# --------------------------
	# Tags are saved in ~/.config/ranger/tagged and simply mark if a
	# file is important to you in any context.

	def tag_toggle(self, paths=None, value=None, movedown=None):
		if not self.tags:
			return
		if paths is None:
			tags = tuple(x.realpath for x in self.env.get_selection())
		else:
			tags = [realpath(path) for path in paths]
		if value is True:
			self.tags.add(*tags)
		elif value is False:
			self.tags.remove(*tags)
		else:
			self.tags.toggle(*tags)

		if movedown is None:
			movedown = len(tags) == 1 and paths is None
		if movedown:
			self.move(down=1)

		if hasattr(self.ui, 'redraw_main_column'):
			self.ui.redraw_main_column()

	def tag_remove(self, paths=None, movedown=None):
		self.tag_toggle(paths=paths, value=False, movedown=movedown)

	def tag_add(self, paths=None, movedown=None):
		self.tag_toggle(paths=paths, value=True, movedown=movedown)

	# --------------------------
	# -- Bookmarks
	# --------------------------
	# Using ranger.container.bookmarks.

	def enter_bookmark(self, key):
		"""Enter the bookmark with the name <key>"""
		try:
			self.bookmarks.update_if_outdated()
			destination = self.bookmarks[key]
			cwd = self.env.cwd
			if destination.path != cwd.path:
				self.bookmarks.enter(key)
				self.bookmarks.remember(cwd)
		except KeyError:
			pass

	def set_bookmark(self, key):
		"""Set the bookmark with the name <key> to the current directory"""
		self.bookmarks.update_if_outdated()
		self.bookmarks[key] = self.env.cwd

	def unset_bookmark(self, key):
		"""Delete the bookmark with the name <key>"""
		self.bookmarks.update_if_outdated()
		self.bookmarks.delete(key)

	# --------------------------
	# -- Pager
	# --------------------------
	# These commands open the built-in pager and set specific sources.

	def display_command_help(self, console_widget):
		if not hasattr(self.ui, 'open_pager'):
			return

		try:
			command = console_widget._get_cmd_class()
		except:
			self.notify("Feature not available!", bad=True)
			return

		if not command:
			self.notify("Command not found!", bad=True)
			return

		if not command.__doc__:
			self.notify("Command has no docstring. Try using python without -OO",
					bad=True)
			return

		pager = self.ui.open_pager()
		lines = cleandoc(command.__doc__).split('\n')
		pager.set_source(lines)

	def display_log(self):
		if not hasattr(self.ui, 'open_pager'):
			return

		pager = self.ui.open_pager()
		if self.log:
			pager.set_source(["Message Log:"] + list(self.log))
		else:
			pager.set_source(["Message Log:", "No messages!"])

	def display_file(self):
		if not hasattr(self.ui, 'open_embedded_pager'):
			return
		if not self.env.cf or not self.env.cf.is_file:
			return

		pager = self.ui.open_embedded_pager()
		pager.set_source(self.env.cf.get_preview_source(pager.wid, pager.hei))

	# --------------------------
	# -- Previews
	# --------------------------
	def update_preview(self, path):
		try:
			del self.previews[path]
			self.ui.need_redraw = True
		except:
			return False

	def get_preview(self, path, width, height):
		if self.settings.preview_script and self.settings.use_preview_script:
			# self.previews is a 2 dimensional dict:
			# self.previews['/tmp/foo.jpg'][(80, 24)] = "the content..."
			# self.previews['/tmp/foo.jpg']['loading'] = False
			# A -1 in tuples means "any"; (80, -1) = wid. of 80 and any hei.
			# The key 'foundpreview' is added later. Values in (True, False)
			try:
				data = self.previews[path]
			except:
				data = self.previews[path] = {'loading': False}
			else:
				if data['loading']:
					return None

			found = data.get((-1, -1), data.get((width, -1),
				data.get((-1, height), data.get((width, height), False))))
			if found == False:
				data['loading'] = True
				loadable = CommandLoader(args=[self.settings.preview_script,
					path, str(width), str(height)], read=True,
					silent=True, descr="Getting preview of %s" % path)
				def on_after(signal):
					exit = signal.process.poll()
					content = signal.loader.stdout_buffer
					data['foundpreview'] = True
					if exit == 0:
						data[(width, height)] = content
					elif exit == 3:
						data[(-1, height)] = content
					elif exit == 4:
						data[(width, -1)] = content
					elif exit == 5:
						data[(-1, -1)] = content
					elif exit == 1:
						data[(-1, -1)] = None
						data['foundpreview'] = False
					elif exit == 2:
						data[(-1, -1)] = open(path, 'r').read(1024 * 32)
					else:
						data[(-1, -1)] = None
					if self.env.cf.realpath == path:
						self.ui.browser.need_redraw = True
					data['loading'] = False
					pager = self.ui.browser.pager
					if self.env.cf and self.env.cf.is_file:
						pager.set_source(self.env.cf.get_preview_source(
							pager.wid, pager.hei))
				def on_destroy(signal):
					try:
						del self.previews[path]
					except:
						pass
				loadable.signal_bind('after', on_after)
				loadable.signal_bind('destroy', on_destroy)
				self.loader.add(loadable)
				return None
			else:
				return found
		else:
			try:
				return open(path, 'r')
			except:
				return None

	# --------------------------
	# -- Tabs
	# --------------------------
	# This implementation of tabs is very simple and keeps track of
	# directory paths only.

	def tab_open(self, name, path=None):
		do_emit_signal = name != self.current_tab
		self.current_tab = name
		if path or (name in self.tabs):
			self.fm.visual = None
			self.enter_dir(path or self.tabs[name])
		else:
			self._update_current_tab()
		if do_emit_signal:
			self.signal_emit('tab.change')

	def tab_close(self, name=None):
		if name is None:
			name = self.current_tab
		if name == self.current_tab:
			direction = -1 if name == self._get_tab_list()[-1] else 1
			previous = self.current_tab
			self.tab_move(direction)
			if previous == self.current_tab:
				return  # can't close last tab
		if name in self.tabs:
			del self.tabs[name]

	def tab_move(self, offset):
		assert isinstance(offset, int)
		tablist = self._get_tab_list()
		current_index = tablist.index(self.current_tab)
		newtab = tablist[(current_index + offset) % len(tablist)]
		if newtab != self.current_tab:
			self.tab_open(newtab)

	def tab_new(self, path=None):
		for i in range(1, 10):
			if not i in self.tabs:
				self.tab_open(i, path)
				break

	def _get_tab_list(self):
		assert len(self.tabs) > 0, "There must be >=1 tabs at all times"
		return sorted(self.tabs)

	def _update_current_tab(self):
		self.tabs[self.current_tab] = self.env.cwd.path

	# --------------------------
	# -- File System Operations
	# --------------------------

	def uncut(self):
		self.env.copy = set()
		self.env.cut = False
		self.ui.browser.main_column.request_redraw()

	def copy(self, mode='set', narg=None, dirarg=None):
		"""Copy the selected items.  Modes are: 'set', 'add', 'remove'."""
		assert mode in ('set', 'add', 'remove')
		cwd = self.env.cwd
		if not narg and not dirarg:
			selected = (f for f in self.env.get_selection() if f in cwd.files)
		else:
			if not dirarg and narg:
				direction = Direction(down=1)
				offset = 0
			else:
				direction = Direction(dirarg)
				offset = 1
			pos, selected = direction.select(
					override=narg, lst=cwd.files, current=cwd.pointer,
					pagesize=self.env.termsize[0], offset=offset)
			cwd.pointer = pos
			cwd.correct_pointer()
		if mode == 'set':
			self.env.copy = set(selected)
		elif mode == 'add':
			self.env.copy.update(set(selected))
		elif mode == 'remove':
			self.env.copy.difference_update(set(selected))
		self.env.cut = False
		self.ui.browser.main_column.request_redraw()

	def cut(self, mode='set', narg=None, dirarg=None):
		self.copy(mode=mode, narg=narg, dirarg=dirarg)
		self.env.cut = True
		self.ui.browser.main_column.request_redraw()

	def paste_symlink(self, relative=False):
		copied_files = self.env.copy
		for f in copied_files:
			try:
				if relative:
					relative_symlink(f.path, join(getcwd(), f.basename))
				else:
					symlink(f.path, join(getcwd(), f.basename))
			except Exception as x:
				self.notify(x)

	def paste_hardlink(self):
		for f in self.env.copy:
			try:
				link(f.path, join(getcwd(), f.basename))
			except Exception as x:
				self.notify(x)

	def paste(self, overwrite=False):
		"""Paste the selected items into the current directory"""
		copied_files = tuple(self.env.copy)

		if not copied_files:
			return

		def refresh(_):
			cwd = self.env.get_directory(original_path)
			cwd.load_content()

		cwd = self.env.cwd
		original_path = cwd.path
		one_file = copied_files[0]
		if overwrite:
			cp_flags = ['-af', '--']
			mv_flags = ['-f', '--']
		else:
			cp_flags = ['--backup=numbered', '-a', '--']
			mv_flags = ['--backup=numbered', '--']

		if self.env.cut:
			self.env.copy.clear()
			self.env.cut = False
			if len(copied_files) == 1:
				descr = "moving: " + one_file.path
			else:
				descr = "moving files from: " + one_file.dirname
			obj = CommandLoader(args=['mv'] + mv_flags \
					+ [f.path for f in copied_files] \
					+ [cwd.path], descr=descr)
		else:
			if len(copied_files) == 1:
				descr = "copying: " + one_file.path
			else:
				descr = "copying files from: " + one_file.dirname
			if not overwrite and len(copied_files) == 1 \
					and one_file.dirname == cwd.path:
				# Special case: yypp
				# copying a file onto itself -> create a backup
				obj = CommandLoader(args=['cp', '-f'] + cp_flags \
						+ [one_file.path, one_file.path], descr=descr)
			else:
				obj = CommandLoader(args=['cp'] + cp_flags \
						+ [f.path for f in copied_files] \
						+ [cwd.path], descr=descr)

		obj.signal_bind('after', refresh)
		self.loader.add(obj)

	def delete(self):
		self.notify("Deleting!")
		selected = self.env.get_selection()
		self.env.copy -= set(selected)
		if selected:
			for f in selected:
				if isdir(f.path) and not os.path.islink(f.path):
					try:
						shutil.rmtree(f.path)
					except OSError as err:
						self.notify(err)
				else:
					try:
						os.remove(f.path)
					except OSError as err:
						self.notify(err)
		self.env.ensure_correct_pointer()

	def mkdir(self, name):
		try:
			os.mkdir(os.path.join(self.env.cwd.path, name))
		except OSError as err:
			self.notify(err)

	def rename(self, src, dest):
		if hasattr(src, 'path'):
			src = src.path

		try:
			os.rename(src, dest)
		except OSError as err:
			self.notify(err)
