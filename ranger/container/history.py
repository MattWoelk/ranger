class HistoryEmptyException(Exception):
	pass

class History(object):
	def __init__(self, maxlen = None):
		from collections import deque
		self.history = deque(maxlen = maxlen)
		self.history_forward = deque(maxlen = maxlen)
	
	def add(self, item):
		if len(self.history) == 0 or self.history[-1] != item:
			self.history.append(item)
			self.history_forward.clear()

	def __len__(self):
		return len(self.history)

	def top(self):
		try:
			return self.history[-1]
		except IndexError:
			raise HistoryEmptyException()

	def bottom(self):
		try:
			return self.history[0]
		except IndexError:
			raise HistoryEmptyException()

	def back(self):
		if len(self.history) > 1:
			self.history_forward.append( self.history.pop() )
		return self.top()

	def move(self, n):
		if n > 0:
			return self.forward()
		if n < 0:
			return self.back()

	def __iter__(self):
		return self.history.__iter__()

	def next(self):
		return self.history.next()

	def forward(self):
		if len(self.history_forward) > 0:
			self.history.append( self.history_forward.pop() )
		return self.top()