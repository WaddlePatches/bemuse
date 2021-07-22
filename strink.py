#!/usr/bin/env python3

# Thank you, PEP-3101

import collections
import functools
import io
import re
import string
import unicodedata

_DEBUG = False

def unaccent(text):
	"""Translate accented characters to their non-accented equivalents"""
	@functools.cache
	def unaccent_c(char):
		if char in string.printable:
			return char
		elif unicodedata.combining(char):
			return None
		else:
			return unicodedata.normalize("NFKD", char)[0]

	return "".join( (c for c in (unaccent_c(char) for char in text) if c is not None) )

class StrinkError(ValueError):
	_Format = string.Formatter().format
	def __init__(self, /, *args, **kwargs):
		self._msg = args[0]
	def __str__(self):
		return self._Format(self._msg, self=self)

class StrinkTokenError(StrinkError):
	_msg = "unexpected token {self.tok!r}"
	def __init__(self, tok=None):
		if tok is not None:
			self.tok = tok
class StrinkIdentError(StrinkTokenError):
	_msg = "invalid identifier {self.tok!r}"
class StrinkBalanceError(StrinkTokenError): pass
class StrinkUnmatchedError(StrinkBalanceError):
	_msg = "unmatched }"
class StrinkShortError(StrinkBalanceError):
	_msg = "expected }"

class Strink(string.Formatter):
	"""This Formatter syntax is the same as str.format(), with the following exceptions:
		* "{}" evaluates to an empty string
		* there is an if/else operator '?#':
			* e.g.: "{tag?then_clause#else_clause}"
			* The condition only tests if the named tag is present. Other types of condition are not supported
			* then_clause and else_clause also get evaluated as format strings
			* Inside the then_clause and else_clause, # can be escaped with ##
			* An empty token "{}" can be used to separate escaped #s from the else operator
		* right-align (>) is default, not sign-align (=)
		* the 'u' conversion option is added, which passes the string through unaccent() first
		* the 'w' conversion option unaccents, and trims non-Windows-filename characters

	e.g.:   {tracknnumber:02?{tracknumber}#00}
			If {tracknumber} is present in mapping, then it will zero-fill pad to two digits
			Otherwise, 00 will be substituted
		{composer!u?{composer}#{artist}}
			If {composer} is present and set, then sub in unaccent({composer})
			Otherwise, sub in unaccent({artist})"""

	class Conditional:
		def __init__(self, test, /):
			self.test = test
			self.thenClause = []
			self.elseClause = []
			self.clause = "then"

		def __repr__(self):
			return f"Conditional<if ({self.test}) then [[" + "; ".join(map(repr, self.thenClause)) + "]] else [[" + "; ".join(map(repr, self.elseClause)) + "]]>"

		def isdigit(self):
			return False

		def addClause(self, what):
			if self.clause == "then":
				self.thenClause.append(what)
			elif self.clause == "else":
				self.elseClause.append(what)

	def convert_field(self, val, conv):
		if val is not None and not len(val):
			return ""

		if conv == "u":
			if isinstance(val, str):
				return unaccent(val)
			else:
				return val
		elif conv == "w":
			if isinstance(val, str):
				return re.sub(r'[<>:"/\|?*]', "", unaccent(val))
			else:
				return val
		else:
			return super().convert_field(val, conv)

	def format_field(self, val, formspec):
		"""Default to > align instead of = align"""
		if val is None:
			return ""

		if not formspec:
			return str(val)
		r = re.match("^(?:(.(?=[<>=^]))?([<>=^])?)?([+\- ])?(#)?(0)?(\d+)?([_,])?(\.\d+)?([bcdeEfFgGnosxX%])?$", formspec)
		if not r:
			raise ValueError(f"invalid format specifier {formspec!r}")
		
		fill, align, sign, alt, zf, width, group, prec, vtype = r.groups()
		if not align and width:
			align = ">"

		return super().format_field(val, "".join(filter(bool, (fill, align, sign, alt, zf, width, group, prec, vtype))))
	
	def get_field(self, fieldDesc, args, kwargs):
		if fieldDesc.isdigit() or fieldDesc == "":
			return ("", None)
		if isinstance(fieldDesc, type(self).Conditional):
			if fieldDesc.test in kwargs:
				toks = fieldDesc.thenClause
				# Special case for {foo?} to return {foo} (if it is present)
				if not len(toks):
					return (kwargs[fieldDesc.test], fieldDesc)
			else:
				toks = fieldDesc.elseClause
				if not len(toks) and not len(fieldDesc.thenClause):
					return (None, fieldDesc)
			return ("".join( (lit + self.format_field(self.convert_field(self.get_field(field, args, kwargs)[0], conv), spec) for lit, field, spec, conv in toks) ), fieldDesc)
		else:
			return super().get_field(fieldDesc, args, kwargs)

	def parse(self, form):
		_DEBUG and print(f"START PARSE: {form!r}")
		# if form == "":
		#	yield ("", "", "", None)

		ident = r"(?:[a-zA-Z_][a-zA-Z0-9_]*)"
		# {{, }} and ## are always literal. {. and .} are always syntactical. Tokenise { and } last
		tokrx = r"({{|}}|##|{\.|\.}|[{}])"
		tokiter = collections.deque(filter(bool, re.split(tokrx, form)))
		lit = field = spec = conv = None
		stack = []

		while len(tokiter):
			tok = tokiter.popleft()
			if tok in ("{{", "##", "}}"):
				lit = tok[0] if not lit else lit + tok[0]
			elif tok in ("{", "{."):
				# Next token must be field or }
				try:
					tok = tokiter.popleft()
				except IndexError:
					raise StrinkShortError()
				if tok in ("}", ".}"):
					continue
				_DEBUG and print (f"after {{ TOK : {tok!r}")
				#                  field        conv              spec      cond
				fldrx = re.split(f"({ident})(?:!([a-zA-Z]))?(?::([^\?]+))?(\?.*)?", tok, 1)
				_DEBUG and print ("REGEX: [%s]" % ",".join(map(repr, fldrx )))
				if len(fldrx) == 1:
					raise StrinkIdentError(tok)
				pre, field, conv, spec, cond, post = fldrx
				if pre:
					raise StrinkIdentError(pre)
				if post:
					raise StrinkTokenError(post)
				_DEBUG and print(f"CONV : {conv!r}")


				if cond:
					field = type(self).Conditional(field)		# cond
					parsed = (lit or "", field or "", spec or "", conv or None)	#cond
					if len(stack):
						stack[-1][1].addClause(parsed)	#cond and len(stack)
					stack.append(parsed)	#cond
					lit = field = spec = conv = None	#cond

					if cond:
						tokiter.extendleft(reversed(cond[1:].partition("#")))	#cond
				else:
					tok = tokiter.popleft()	#notcond
					if tok in ("}", "."):
						parsed = (lit or "", field or "", spec or "", conv or None) #notcond and }
						if len(stack):
							stack[-1][1].addClause(parsed) #notcond and } and len(stack)
						else:
							yield parsed # notcond and } and len(stack)
						lit = field = spec = conv = None	#notcond and }
					else:
						raise StrinkTokenError(tok)

			elif tok == "#":
				if not len(stack) or stack[-1][1].clause == "else":
					raise StrinkTokenError(tok)
				stack[-1][1].addClause( (lit or "", field or "", spec or "", conv or None) )
				stack[-1][1].clause = "else"
				lit = field = spec = conv = None
			elif len(stack) and "#" in tok:
				tokiter.extendleft(reversed(tok.partition("#")))
			elif tok in ("}", ".}"):
				parsed = (lit or "", field or "", spec or "", conv or None)
				if len(stack):
					pop = stack.pop()
					if lit or field:
						pop[1].addClause(parsed)
					if not len(stack):
						yield pop
				else:
					if field is None:
						raise StrinkUnmatchedError()
					if lit or field:
						yield parsed
				lit = field = spec = conv = None
			else:
				lit = tok if not lit else lit + tok
		if len(stack):
			raise StrinkShortError()
		_DEBUG and print(f"LIT: {lit!r}")
		if lit:
			yield (lit or "", "", "", None)
		# _DEBUG and print("No more tokens")
