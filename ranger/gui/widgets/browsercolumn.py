# -*- encoding: utf8 -*-
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

"""The BrowserColumn widget displays the contents of a directory or file."""
import stat
from time import time
import _curses

from . import Widget
from .pager import Pager
from ranger.gui.color import get_color
from curses import color_pair

class BrowserColumn(Pager):
	main_column = False
	display_infostring = False
	scroll_begin = 0
	target = None
	last_redraw_time = -1
	ellipsis = { False: '~', True: '…' }

	old_dir = None
	old_cf = None

	def __init__(self, win, level):
		"""
		win = the curses window object of the BrowserView
		level = what to display?

		level >0 => previews
		level 0 => current file/directory
		level <0 => parent directories
		"""
		Pager.__init__(self, win)
		Widget.__init__(self, win)
		self.level = level

		self.fm.signal_bind('setopt.display_size_in_main_column',
				self.request_redraw, weak=True)

	def request_redraw(self):
		self.need_redraw = True

	def resize(self, y, x, hei, wid):
		Widget.resize(self, y, x, hei, wid)

	def click(self, event):
		"""Handle a MouseEvent"""
		direction = event.mouse_wheel_direction()
		if not (event.pressed(1) or event.pressed(3) or direction):
			return False

		if self.target is None:
			pass

		elif self.target.is_directory:
			if self.target.accessible and self.target.content_loaded:
				index = self.scroll_begin + event.y - self.y

				if direction:
					if self.level == -1:
						self.fm.move_parent(direction)
					else:
						return False
				elif event.pressed(1):
					if not self.main_column:
						self.fm.enter_dir(self.target.path)

					if index < len(self.target):
						self.fm.move(to=index)
				elif event.pressed(3):
					try:
						clicked_file = self.target.files[index]
						if clicked_file.is_directory:
							self.fm.enter_dir(clicked_file.path)
						elif self.level == 0:
							self.fm.tab.cwd.move_to_obj(clicked_file)
							self.fm.cmd("execute")
					except:
						pass

		else:
			if self.level > 0 and not direction:
				self.fm.move(right=0)

		return True

	def has_preview(self):
		if self.target is None:
			return False

		if self.target.is_file:
			if not self.target.has_preview():
				return False

		if self.target.is_directory:
			if self.level > 0 and not self.fm.settings.preview_directories:
				return False

		return True

	def poke(self):
		Widget.poke(self)
		self.target = self.fm.tab.at_level(self.level)

	def draw(self):
		"""Call either _draw_file() or _draw_directory()"""
		if self.target != self.old_dir:
			self.need_redraw = True
			self.old_dir = self.target

		if self.target:  # don't garbage collect this directory please
			self.target.use()

		if self.target and self.target.is_directory \
				and (self.level <= 0 or self.fm.settings.preview_directories):
			if self.target.pointed_obj != self.old_cf:
				self.need_redraw = True
				self.old_cf = self.target.pointed_obj

			if self.target.load_content_if_outdated() \
			or self.target.sort_if_outdated() \
			or self.last_redraw_time < self.target.last_update_time:
				self.need_redraw = True

		if self.need_redraw:
			self.win.erase()
			if self.target is None:
				pass
			elif self.target.is_file:
				Pager.open(self)
				self._draw_file()
			elif self.target.is_directory:
				self._draw_directory()
				Widget.draw(self)
			self.need_redraw = False
			self.last_redraw_time = time()

	def _draw_file(self):
		"""Draw a preview of the file, if the settings allow it"""
		self.win.move(0, 0)
		if not self.target.accessible:
			self.addnstr("not accessible", self.wid)
			Pager.close(self)
			return

		if self.target is None or not self.target.has_preview():
			Pager.close(self)
			return

		try:
			f = self.target.get_preview_source(self.wid, self.hei)
		except:
			raise # XXX
			Pager.close(self)
		else:
			if f is None:
				Pager.close(self)
			else:
				self.set_source(f)
				Pager.draw(self)

	def _draw_directory(self):
		"""Draw the contents of a directory"""

		if self.level > 0 and not self.fm.settings.preview_directories:
			return

		base_color = ['in_browser']

		self.win.move(0, 0)

		if not self.target.content_loaded:
			self.color(base_color)
			self.addnstr("...", self.wid)
			self.color_reset()
			return

		if self.main_column:
			base_color.append('main_column')

		if not self.target.accessible:
			self.color(base_color, 'error')
			self.addnstr("not accessible", self.wid)
			self.color_reset()
			return

		if self.target.empty():
			self.color(base_color, 'empty')
			self.addnstr("empty", self.wid)
			self.color_reset()
			return

		self._set_scroll_begin()

		copied = [f.path for f in self.fm.copy]
		ellipsis = self.ellipsis[self.fm.settings.unicode_ellipsis]

		selected_i = self.target.pointer
		for line in range(self.hei):
			try:
				drawn = self.target.files[line + self.scroll_begin]
			except IndexError:
				break

			data = [[drawn.basename, -1, -1, 0]]
			self.fm.signal_emit('color.file', data=data,
					target=self.target, file=drawn, column=self)

			try:
				self.win.move(line, 0)
				for item in data:
					self.addstr(item[0],
							color_pair(get_color(item[1], item[2])) | item[3])
			except _curses.error:
				pass

			self.color_reset()

	def _get_scroll_begin(self):
		"""Determines scroll_begin (the position of the first displayed file)"""
		offset = self.fm.settings.scroll_offset
		dirsize = len(self.target)
		winsize = self.hei
		halfwinsize = winsize // 2
		index = self.target.pointer or 0
		original = self.target.scroll_begin
		projected = index - original

		upper_limit = winsize - 1 - offset
		lower_limit = offset

		if original < 0:
			return 0

		if dirsize < winsize:
			return 0

		if halfwinsize < offset:
			return min( dirsize - winsize, max( 0, index - halfwinsize ))

		if original > dirsize - winsize:
			self.target.scroll_begin = dirsize - winsize
			return self._get_scroll_begin()

		if projected < upper_limit and projected > lower_limit:
			return original

		if projected > upper_limit:
			return min( dirsize - winsize,
					original + (projected - upper_limit))

		if projected < upper_limit:
			return max( 0,
					original - (lower_limit - projected))

		return original

	def _set_scroll_begin(self):
		"""Updates the scroll_begin value"""
		self.scroll_begin = self._get_scroll_begin()
		self.target.scroll_begin = self.scroll_begin

	def scroll(self, n):
		"""scroll down by n lines"""
		self.need_redraw = True
		self.target.move(down=n)
		self.target.scroll_begin += 3 * n

	def __str__(self):
		return self.__class__.__name__ + ' at level ' + str(self.level)
