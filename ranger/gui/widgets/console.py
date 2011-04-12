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

"""
The Console widget implements a vim-like console for entering
commands, searching and executing files.
"""

import curses
import re
import sys
from collections import deque

from . import Widget
from ranger.models.history import History, HistoryEmptyException
from ranger.models.keymap import CommandArgs
from ranger.ext.direction import Direction
from ranger.ext.utfwidth import uwid, uchars, utf_char_width_
import ranger

PY3 = sys.version_info >= (3, )

class Console(Widget):
	visible = False
	last_cursor_mode = None
	history_search_pattern = None
	prompt = ':'
	copy = ''
	tab_deque = None
	original_line = None
	history = None
	override = None
	allow_close = False
	historypath = None

	def __init__(self, win):
		Widget.__init__(self, win)
		self.clear()
		self.history = History(self.fm.settings.max_console_history_size)
		# load history from files
		if not self.fm.arg.clean:
			self.historypath = self.fm.confpath('history')
			try:
				f = open(self.historypath, 'r')
			except:
				pass
			else:
				for line in f:
					self.history.add(line[:-1])
				f.close()

	def destroy(self):
		# save history to files
		if self.fm.clean or not self.fm.settings.save_console_history:
			return
		if self.historypath:
			try:
				f = open(self.historypath, 'w')
			except:
				pass
			else:
				for entry in self.history:
					f.write(entry + '\n')
				f.close()

	def draw(self):
		self.win.erase()
		self.addstr(0, 0, self.prompt)
		if PY3:
			overflow = -self.wid + len(self.prompt) + len(self.line) + 1
		else:
			overflow = -self.wid + len(self.prompt) + uwid(self.line) + 1
		if overflow > 0: 
			#XXX: cut uft-char-wise, consider width
			self.addstr(self.line[overflow:])
		else:
			self.addstr(self.line)

	def finalize(self):
		try:
			if PY3:
				xpos = sum(utf_char_width_(ord(c)) for c in self.line[0:self.pos]) \
					+ len(self.prompt)
			else:
				xpos = uwid(self.line[0:self.pos]) + len(self.prompt)
			self.fm.ui.win.move(self.y, self.x + min(self.wid-1, xpos))
		except:
			pass

	def open(self, string='', prompt=None, position=None):
		if prompt is not None:
			assert isinstance(prompt, str)
			self.prompt = prompt
		elif 'prompt' in self.__dict__:
			del self.prompt

		if self.last_cursor_mode is None:
			try:
				self.last_cursor_mode = curses.curs_set(1)
			except:
				pass
		self.allow_close = False
		self.tab_deque = None
		self.focused = True
		self.visible = True
		self.unicode_buffer = ""
		self.line = string
		self.history_search_pattern = self.line
		self.pos = len(string)
		if position is not None:
			self.pos = min(self.pos, position)
		self.history.fast_forward()
		self.history.add('')
		return True

	def close(self):
		if self.last_cursor_mode is not None:
			try:
				curses.curs_set(self.last_cursor_mode)
			except:
				pass
			self.last_cursor_mode = None
		self.add_to_history()
		self.tab_deque = None
		self.clear()
		self.__class__ = Console
		self.focused = False
		self.visible = False
		if hasattr(self, 'on_close'):
			self.on_close()

	def clear(self):
		self.pos = 0
		self.line = ''

	def press(self, key):
		self.fm.keymanager.use_context('console')
		self.fm.key_append(key)
		kbuf = self.fm.keybuffer
		cmd = kbuf.command

		if kbuf.failure:
			kbuf.clear()
			self.type_key(key)
			return
		elif not cmd:
			return

		if cmd.function:
			try:
				cmd.function(CommandArgs.from_widget(self))
			except Exception as error:
				self.fm.notify(error)
			if kbuf.done:
				kbuf.clear()
		else:
			kbuf.clear()

	def type_key(self, key):
		self.tab_deque = None

		if isinstance(key, int):
			try:
				key = chr(key)
			except ValueError:
				return

		if PY3:
			self.unicode_buffer += key
			try:
				decoded = self.unicode_buffer.encode("latin-1").decode("utf-8")
			except UnicodeDecodeError:
				pass
			else:
				self.unicode_buffer = ""
				if self.pos == len(self.line):
					self.line += decoded
				else:
					pos = self.pos
					self.line = self.line[:pos] + decoded + self.line[pos:]
				self.pos += len(decoded)
		else:
			if self.pos == len(self.line):
				self.line += key
			else:
				self.line = self.line[:self.pos] + key + self.line[self.pos:]
			self.pos += len(key)

		self.on_line_change()

	def history_move(self, n):
		try:
			current = self.history.current()
		except HistoryEmptyException:
			pass
		else:
			if self.line != current and self.line != self.history.top():
				self.history.modify(self.line)
			if self.history_search_pattern:
				self.history.search(self.history_search_pattern, n)
			else:
				self.history.move(n)
			current = self.history.current()
			if self.line != current:
				self.line = self.history.current()
				self.pos = len(self.line)

	def add_to_history(self):
		self.history.fast_forward()
		self.history.modify(self.line, unique=True)

	def move(self, **keywords):
		direction = Direction(keywords)
		if direction.horizontal():
			# Ensure that the pointer is moved utf-char-wise
			if PY3:
				self.pos = direction.move(
						direction=direction.right(),
						minimum=0,
						maximum=len(self.line) + 1,
						current=self.pos)
			else:
				uc = uchars(self.line)
				upos = len(uchars(self.line[:self.pos]))
				newupos = direction.move(
						direction=direction.right(),
						minimum=0,
						maximum=len(uc) + 1,
						current=upos)
				self.pos = len(''.join(uc[:newupos]))

	def delete_rest(self, direction):
		self.tab_deque = None
		if direction > 0:
			self.copy = self.line[self.pos:]
			self.line = self.line[:self.pos]
		else:
			self.copy = self.line[:self.pos]
			self.line = self.line[self.pos:]
			self.pos = 0
		self.on_line_change()

	def paste(self):
		if self.pos == len(self.line):
			self.line += self.copy
		else:
			self.line = self.line[:self.pos] + self.copy + self.line[self.pos:]
		self.pos += len(self.copy)
		self.on_line_change()

	def delete_word(self):
		if self.line:
			self.tab_deque = None
			i = len(self.line) - 2
			while i >= 0 and re.match(r'[\w\d]', self.line[i], re.U):
				i -= 1
			self.copy = self.line[i + 1:]
			self.line = self.line[:i + 1]
			self.pos = len(self.line)
			self.on_line_change()

	def delete(self, mod):
		self.tab_deque = None
		if mod == -1 and self.pos == 0:
			if not self.line:
				self.close()
			return
		# Delete utf-char-wise
		if PY3:
			left_part = self.line[:self.pos + mod]
			self.pos = len(left_part)
			self.line = left_part + self.line[self.pos + 1:]
		else:
			uc = uchars(self.line)
			upos = len(uchars(self.line[:self.pos])) + mod
			left_part = ''.join(uc[:upos])
			self.pos = len(left_part)
			self.line = left_part + ''.join(uc[upos+1:])
		self.on_line_change()

	def execute(self, cmd=None):
		self.allow_close = True
		if cmd is None:
			cmd = self.line
		self.fm.cmd(cmd)

		if self.allow_close:
			self.close()

	def _get_cmd(self):
		try:
			command_class = self._get_cmd_class()
		except KeyError:
			self.fm.notify("Invalid command! Press ? for help.", bad=True)
		except:
			return None
		else:
			return command_class().setargs(self.line)

	def _get_cmd_class(self):
		return self.fm.get_command(self.line.split()[0])

	def _get_tab(self):
		if ' ' in self.line:
			cmd = self._get_cmd()
			if cmd:
				return cmd.tab()
			else:
				return None

		return self.fm.commands.command_generator(self.line)

	def tab(self, n=1):
		if self.tab_deque is None:
			tab_result = self._get_tab()

			if isinstance(tab_result, str):
				self.line = tab_result
				self.pos = len(tab_result)
				self.on_line_change()

			elif tab_result == None:
				pass

			elif hasattr(tab_result, '__iter__'):
				self.tab_deque = deque(tab_result)
				self.tab_deque.appendleft(self.line)

		if self.tab_deque is not None:
			self.tab_deque.rotate(-n)
			self.line = self.tab_deque[0]
			self.pos = len(self.line)
			self.on_line_change()

	def on_line_change(self):
		self.history_search_pattern = self.line
		try:
			cls = self._get_cmd_class()
			if cls is None:
				raise KeyError
		except (KeyError, ValueError, IndexError):
			pass
		else:
			cmd = cls().setargs(self.line)
			if cmd and cmd.quick():
				self.allow_close = True
				try:
					cmd.execute()
				except Exception as error:
					self.fm.notify(error)
				if self.allow_close:
					self.close()
