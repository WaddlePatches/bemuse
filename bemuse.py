#!/usr/bin/env python3

import enum
import json
import logging
import pathlib

import strink

__version__ = "1.0.1"

class UpperDict(dict):
	class _Sentinel(enum.Enum):
		NOTSPECIFIED = 1

	def __getitem__(self, k):
		if hasattr(k, "upper"):
			k = k.upper()
		return super().__getitem__(k)
	
	def __setitem__(self, k, v):
		if hasattr(k, "upper"):
			k = k.upper()
		return super().__setitem__(k, v)
	
	def __delitem__(self, k):
		if hasattr(k, "upper"):
			k = k.upper()
		super().__delitem__(k)
	
	def __contains__(self, k):
		if hasattr(k, "upper"):
			k = k.upper()
		return super().__contains__(k)
	
	def __str__(self):
		return "{" + ", ".join(f"{k!r}: {v!r}" for k, v in self.items()) + "}"
	
	def __repr__(self):
		return str(self)
	
	def get(self, k, d=_Sentinel.NOTSPECIFIED):
		if d is self._Sentinel.NOTSPECIFIED:
			return self[k]
		else:
			return self[k] if k in self else d
	
	def keys(self):
		for k in super().keys():
			if hasattr(k, "upper"):
				yield k.upper()
			else:
				yield k
	
	def items(self):
		for k, v in zip(self.keys(), self.values()):
			yield k, v
	
	def pop(self, k, d=_Sentinel.NOTSPECIFIED):
		if hasattr(k, "upper"):
			k = k.upper()
		if k not in self and d is self._Sentinel.NOTSPECIFIED:
			raise KeyError(k)
		else:
			return super().pop(k, d)
		
	
class Probe:
	"""self.filename : str
	self.path        : pathlib.Path
	self.tags        : UpperDict() -- parsed ffprobe output
	"""
	def __getattr__(self, name):
		if not hasattr(super(), name):
			return None
		else:
			return super().__getattr__(name)
	
	def __init__(self):
		# TODO: Migrate self.stream_* variables to extract from _stream_data instead
		self._stream_data = []
		self.stream_tags = set()
		self.stream_codecs = {}
		self.path = None
		self.tags = UpperDict()

	@classmethod
	def fromPath(self, path):
		import subprocess
		ran = subprocess.run([
				"ffprobe",
				"-of", "json",
				"-loglevel", "0",
				"-count_frames",            # if nb_read_frames == 1, then image
				"-read_intervals", "%+#3",  # limit the number of packets read
				"-show_entries", "format:stream",
				path],
			capture_output=True, check=True)
		j = json.loads(ran.stdout.decode("utf-8"))
		jtags = []

		new = self()
		# .opus files have metadata tags in stream_tags
		new._stream_data = j["streams"]
		for s in j["streams"]:
			if not s["disposition"]["attached_pic"]:
				if "tags" in s:
					jtags.append(s["tags"])
					new.stream_tags.update(s["tags"].keys())
				new.stream_codecs[s["index"]] = (s.get("codec_type", None), s.get("codec_name", None))
		# .mp3 and .flac files have metadata tags in format_tags
		if "tags" in j["format"] and len(j["format"]["tags"]):
			jtags.append(j["format"]["tags"])
		for k, v in j["format"].items():
			if k != "tags":
				setattr(new, k, v)
			if k == "filename":
				new.path = pathlib.Path(v)

		for section in jtags:
			for tag, content in section.items():
				new.tags[tag] = content
				try:
					if tag.casefold() == "composer".casefold():
						new.tags["composerfirstnames"], new.tags["composerlastname"] = content.rsplit(" ", 1)
						new.tags["composerinitials"] = "".join( (n[0] for n in new.tags["composerfirstnames"].split(" ")) )
				except ValueError:
					pass
				if tag.casefold() in ("album_artist", "artist"):
					new.tags[f"{tag}_the"] = ", ".join(filter(bool, reversed(re.match("(?:(the)\s+)?(.*)", content, re.I).groups())))
				if tag.casefold() in map(str.casefold, ("disc", "track")):
					if hasattr(content, "isdigit") and not content.isdigit():
						try:
							num, tot = content.split("/", 1)
						except ValueError:
							pass
						else:
							new.tags[tag] = num
							new.tags[f"{tag}total"] = tot
			#if hasattr(new, "tags") and new.tags is not None:
			#	new.tags["ext"] = new.path.suffix
		# if new.format_name.startswith("image"):
		#	new.tags["format_is_image"] = True
		return new
	
	def streams(self):
		return {s["index"]: s for s in self._stream_data if not s.get("disposition", {}).get("attached_pic", False)}

	def is_image(self):
		sts = self.streams()
		return len(sts) and all(map(lambda s: s["codec_type"] == "video" and s["nb_read_frames"] == "1", sts.values()))
	
	def writeMeta(self, newTags, /, newPath=None, codec={}, dryRun=False):
		import tempfile

		def meta_args():
			for k, v in newTags.items():
				met = "%s=%s" % (k, "" if v is None else v)
				if k in self.stream_tags:
					# Make sure ffmpeg overwrites existing tags
					yield f"-metadata:s:m:{k}"
					yield met
				else:
					yield f"-metadata"
					yield met

		def codec_args(codec_map):
			for k, v in filter(lambda kv: kv[0] is not None, codec_map):
				yield f"{k}"
				yield str(v)

		def stream_codec_map():
			codec_name_map = {}
			codec_type_map = {}
			for codec_type, codec_name in filter(lambda k:str.startswith(k[0], "codec"), codec.items()):
				names = codec_name.casefold().rsplit("!", 1)
				if len(names) == 1:
					codec_name_map[names[0]] = (codec_type, names[0])
				else:
					codec_name_map[names[1]] = (codec_type, names[0])

				ctype = codec_type.split(":", 1)
				if len(ctype) == 1:
					codec_type_map[None] = names[0]
				else:
					codec_type_map[ctype[1][0]] = names[0]

			if None in codec_type_map:
				yield (f"-codec", codec_type_map[None])
			else:
				yield (None, None)

			for index, stream in self.stream_codecs.items():
				ctype, cname = stream
				if cname.casefold() in codec_name_map:
					#yield "-%s:%d" % (codec_name_map[stream.casefold()][0], index)
					#yield "copy"
					yield ("-%s:%d" % (codec_name_map[cname.casefold()][0], index), "copy")
				elif ctype[0] in codec_type_map:
					yield ("-codec:%s:%d" % (ctype[0], index), codec_type_map[ctype[0]])
				elif None in codec_type_map and cname.casefold() in codec_name_map:
					yield ("-codec:{index}", "copy")

		log = logging.getLogger("Probe.writeMeta")
		newTags = UpperDict(newTags)
		
		codec_map = [(k, v) for k, v in stream_codec_map()]

		tmp = None
		if not newTags and all(map(lambda v:v[1]=="copy", codec_map[1:])):
			if not newPath or (newPath.exists() and self.path.samefile(newPath)):
				return (None, None)
			else:
				if not dryRun:
					newPath.parent.exists() or log.debug(f"mkdir {npath.parent!a}")
					newPath.parent.mkdir(parents=True, exist_ok=True)
				return (self.path, "replace")
					# self.path.replace(newPath)
		elif not dryRun:
			newPath = pathlib.Path(newPath)
			if not newPath or (newPath.exists() and self.path.samefile(newPath)):
				tmp = tempfile.NamedTemporaryFile(prefix="bemuse_", delete=False, suffix=newPath.suffix) ; tmp.close()
				newPath = pathlib.Path(tmp.name)
			else:
				newPath.parent.mkdir(parents=True, exist_ok=True)

		ffargs = ["ffmpeg", "-i", self.filename, *meta_args(), *codec_args(codec_map), "-loglevel", "0", "-y", "-nostdin", str(newPath)]
		if dryRun:
			print(ffargs)
		else:
			log.debug(str(ffargs))
			ran = subprocess.run(ffargs, check=True)

		if tmp:
			return (newPath, "tmpcode")
		else:
			return (newPath, "transcode")

def replaygain(tracklist):
	import collections
	import subprocess
	import re

	files = tuple(tracklist)

	if files:
		loudgainargs = ["loudgain", "-a", "-O", *(t.filename for t in files)]
		ran = subprocess.run(loudgainargs, capture_output=True, text=True)

		if ran.returncode:
			raise subprocess.SubprocessError(ran.stderr.rstrip().rsplit("\n",1)[-1])
		lines = ran.stdout.strip().split("\n")
		if len(lines):
			# File	Loudness	Range	True_Peak	True_Peak_dBTP	Reference	Will_clip	Clip_prevent	Gain	New_Peak	New_Peak_dBTP
			head = lines[0].strip().split("\t")
			# de-capitalise the first character of the field names
			Fields = collections.namedtuple("ReplayGain", ( ("".join(t.lower() if i % 2 else t for i, t in enumerate(v)) for v in (re.split("(?<![A-Za-z])([A-Z])", field) for field in lines[0].strip().split("\t")) ) )  )
			# Skip header and album line
			for track, line in zip(files, lines[1:-1]):
				yield (track, Fields(*line.strip().split("\t")))
			# Yield album line with filename = None
			yield (None, Fields(None, *lines[-1].strip().split("\t")[1:]))

if __name__ == "__main__":
	import argparse
	import collections
	import configparser
	import os
	import re
	import subprocess
	import sys

	cwd = pathlib.Path.cwd()
	parg = argparse.ArgumentParser(description="Unify music files")
	parg.add_argument("paths", nargs="*", help="where the files to scan are", type=pathlib.Path, default=[])
	parg.add_argument("-A", "--album-art", help="move albumart to same directory as media files (does not overwrite)", action="store_true")
	parg.add_argument("-c", "--config", action="store", default=pathlib.Path("~/.config/bemuse.cfg").expanduser())
	parg.add_argument("-d", "--dest", help="where to put the files", metavar="DIRECTORY", type=pathlib.Path, action="store", default=os.curdir)
	parg.add_argument("-D", "--from-file", help="load in media file locations from file (can be specified multiple times)", metavar="FILE", type=pathlib.Path, action="append", default=[])
	parg.add_argument("-E", "--adjust-metadata", help="apply metadata rules from the config file", action="store_true")
	parg.add_argument("-G", "--replaygain", help="write ReplayGain tags (requires loudgain tool)", action="store_true")
	parg.add_argument("-f", "--format", help="a Python-like format string to generate the new path", action="store")
	parg.add_argument("-K", "--remove", help="delete the original file once finished", action="store_true")
	parg.add_argument("-L", "--list", help="print each file as per the given format and exit", action="store_true")
	parg.add_argument("-m", "--match", help="only scan files with names that match the given regex", action="store", metavar="REGEX", type=re.compile, default=None)
	parg.add_argument("-n", "--dry-run", help="print moves, renames, or transcodes without executing them", action="store_true")
	parg.add_argument("-P", "--preset", help="select a named format string from the config file", action="store")
	parg.add_argument("-R", "--rename", help="rename or move the files according to the given format (*overwrites files*)", action="store_true")
	parg.add_argument("-T", "--transcode", help="convert files using codec, where options are given in config file (*overwrites files*)", metavar="CODEC", action="store")
	parg.add_argument("-v", "--verbose", help="increase verbosity level (can be specified multiple times)", action="count")
	parg.add_argument("--version", action="version", version="%(prog)s " + __version__)
	args = parg.parse_args()

	if args.verbose is None:
		logging.basicConfig(level=logging.WARNING)
	# Regular output for args.verbose == 1
	elif args.verbose == 2:
		logging.basicConfig(level=logging.INFO)
	elif args.verbose >= 3:
		logging.basicConfig(level=logging.DEBUG)
	
	log = logging.getLogger(str(pathlib.Path(__file__).stem))
	log.debug("loglevel set to debug")

	if not(any((args.adjust_metadata, args.replaygain, args.list, args.rename, args.transcode, args.album_art))):
		log.error("nothing to do: no mode selected")
		sys.exit(1)

	formak = strink.Strink()

	class FoundItException(Exception): pass

	def new_path(form, tags, suffix=""):
		return args.dest / pathlib.Path(formak.vformat(args.format, [], tags) + suffix)

	def select_file(path):
		return (not args.match) or (args.match.search(path) is not None)

	## TODO: move this to Probe class
	def scan_paths(paths):

		for path in paths:
			limg = set()
			allimg = set()
			if path.is_dir():
				subs = [path]
				shmeta = UpperDict()
				while len(subs):
					left = subs.pop()
					log.info(f"Probing {str(left)!r}")
					here = set()
					for im in tuple(limg):
						if not left.is_relative_to(im.path.parent):
							limg.remove(im)
					firstImg = True

					for ent in left.iterdir():
						if ent.is_dir():
							subs.append(ent)
						else:
							try:
								meta = Probe.fromPath(ent)
							except subprocess.CalledProcessError as err:
								continue
							if meta is None:
								continue
							if "title" not in meta.tags or not meta.tags["title"]:
								meta.tags["title"] = meta.path.stem
							#if meta.format_name.startswith("image"):
							if meta.is_image():
								if firstImg:
									shmeta = UpperDict()
									limg = set()
									firstImg = False
								limg.add(meta)
							else:
								here.add(meta)
								if select_file(meta.path.name):
									yield meta
					## Find shared metadata ##
					for meta in here:
						if meta.tags is None:
							log.debug(f"PATH {str(meta.path)!r}")
						for k, v in meta.tags.items():
							if k in shmeta:
								# Use FoundItException as a sentinel
								if shmeta[k] != v and shmeta[k] is not FoundItException:
									shmeta[k] = FoundItException
							else:
								shmeta[k] = v
					for k, v in tuple(shmeta.items()):
						if v is FoundItException:
							shmeta.pop(k, None)
					## Apply shared metadata to images ##
					for im in tuple(limg):
						if len(shmeta):
							im.tags.update(shmeta)
						im.tags["title"] = im.path.stem
						im.tags.pop("track", None)
						if select_file(im.path.name):
							allimg.add(im)
				for im in allimg:
					yield im
			else:
				try:
					meta = Probe.fromPath(path)
				except subprocess.CalledProcessError:
					log.error("%r not a media file" % str(path))
				else:
					if select_file(meta.path.name):
						yield meta

	conf = configparser.ConfigParser(interpolation=None, delimiters="=", inline_comment_prefixes=None)
	if args.config:
		conf.read(args.config)
		if not args.format:
			if args.preset:
				preset = args.preset
			else:
				preset = conf["Format"]["default"]
				if preset.casefold() == "default".casefold():
					raise ValueError("default format selects itself in config file")
			for k, v in conf["Format"].items():
				if k.casefold() == preset.casefold():
					args.format = v
					break
			if args.preset and not args.format:
				log.error("preset not found in config file")
				sys.exit(1)
			
	conf.setdefault("Metadata", {})

	codec = collections.OrderedDict()
	file_suffix = None
	if args.transcode:
		codec_name = f"Transcode:{args.transcode}"
		if codec_name in conf.sections():
			# Don't want to screw with the config but need to extract formatted data
			codec = collections.OrderedDict(conf[codec_name])
			file_suffix = codec.pop("file_suffix", None)
		else:
			log.error("codec not specified in config file")
			sys.exit(1)

	if not (args.format or args.adjust_metadata):
		log.error("no formatter specified, don't know what to do")
		sys.exit(1)
	
	for lfile in args.from_file:
		if lfile == "-":
			args.paths.extend(map(pathlib.Path, map(str.strip, sys.stdin.readlines())))
		else:
			with lfile.open() as lfd:
				args.paths.extend(map(pathlib.Path, map(str.strip, lfd.readlines())))

	not (args.paths or args.from_file) and args.paths.append(pathlib.Path(os.curdir))
	if not args.paths:
		log.error("no paths to scan")
		sys.exit(1)

	## Pass 1: collect files and metadata ##
	album = {}
	for probe in scan_paths(args.paths):
		log.debug(f"Probed {probe.filename!r}")
		if probe.tags:
			if "album" in probe.tags:
				album.setdefault(probe.tags["album"], [])
				album[probe.tags["album"]].append(probe)
			else:
				log.warning(f"{probe.filename!r} has no album tag")
				album.setdefault(None, [])
				album[None].append(probe)

	## Pass 2: adjust metadata, move (or list) file ##
	check_dirs = set()
	for alb in album.keys():
		tracks = album[alb]
		rgain = {}

		if args.replaygain and not args.list:
			log.info(f"Calculating ReplayGain for album {alb!r}")
			rgain.update(
				replaygain(filter(lambda t:
						select_file(t.path.name) and
						any(c[0] == "audio" for c in t.stream_codecs.values()),
					tracks)
				)
			)

		ndiscs = set()
		for t in tracks:
			ndiscs.add(t.tags.get("disc", None))
		ndiscs.discard(None)

		for t in tracks:
			if len(ndiscs) > 1:
				if "disc" in t.tags:
					t.tags["adisc"] = t.tags["disc"]
				
			new = {}
			# log.info(f"File: {t.filename!r}")
			if args.adjust_metadata:
				for key, val in conf["Metadata"].items():
					val = formak.vformat(val, [], t.tags)
					log.debug(f"  Metadata: {key}={val!r}")
					t.tags[key] = new[key] = val

			if rgain and args.replaygain and not args.list and t in rgain:
				new["R128_TRACK_GAIN"] = new["REPLAYGAIN_TRACK_GAIN"] = rgain[t].gain
				new["R128_ALBUM_GAIN"] = new["REPLAYGAIN_ALBUM_GAIN"] = rgain[None].gain
				new["R128_TRACK_PEAK"] = new["REPLAYGAIN_TRACK_PEAK"] = rgain[t].true_peak
				new["R128_ALBUM_PEAK"] = new["REPLAYGAIN_ALBUM_PEAK"] = rgain[None].true_peak
				new["R128_ALBUM_RANGE"] = new["REPLAYGAIN_ALBUM_RANGE"] = rgain[None].range
				new["R128_TRACK_RANGE"] = new["REPLAYGAIN_TRACK_RANGE"] = rgain[None].range
				new["R128_REFERENCE_LOUDNESS"] = new["REPLAYGAIN_REFERENCE_LOUDNESS"] = rgain[None].reference
			
			# Ensure the correct suffix is used for transcoding
			suffix = file_suffix or t.path.suffix
			npath = new_path(args.format, t.tags, suffix)
			if args.list:
				print(npath)
				continue

			if not args.remove and npath.exists() and npath.samefile(t.path):
				if args.transcode or new:
					log.warning(f"will not overwrite {t.filename!r}")
				continue

			if t.path != npath and ((args.album_art and t.is_image()) or args.rename or args.transcode):
				if args.dry_run or args.verbose:
					print(f"{t.filename!r} => {str(npath)!r}")

			check_dirs.add(t.path.parent)

			if args.rename or ((args.adjust_metadata or args.replaygain) and len(new)) or args.transcode or (args.album_art and t.is_image()):
				target, action = t.writeMeta(new, npath, codec=codec, dryRun = args.dry_run)
	
				if action is None:
					log.debug(f"<no-op {t.filename!r}>")
				elif action in ("replace", "transcode", "tmpcode"):
					if action == "replace":
						log.debug(["mv" if args.remove else "cp", t.filename, str(target)])
					if not args.dry_run:
						if args.remove:
							if not (npath.exists() and target.samefile(npath)):
								log.debug(["mv", str(target), str(npath)])
								target.replace(npath)
							else:
								log.debug(["rm", str(t.path)])
								t.path.unlink()
						elif not (npath.exists() and npath.samefile(t.path)):
							npath.write_bytes(target.read_bytes())
							if action == "tmpcode":
								target.unlink()
						t.path = npath

	## Pass 3: album art ##
	#if args.album_art:
	#	cpimg = set()
	#	for p, imgs in imgpaths.items():
	#		for i in imgs:
	#			nimg = p / i.path.name
	#			if nimg.exists() or nimg == i.path:
	#				log.debug(f"not overwriting {nimg}")
	#				continue
	#			(args.dry_run or args.verbose) and print(f"{str(i.path)!r} => {str(nimg)!r}")
	#			args.dry_run or nimg.write_bytes(i.path.read_bytes())
	#			cpimg.add(i)
	#	for i in cpimg:
	#		(args.dry_run or args.verbose) and log.debug(f"rm {str(i.path)!r}")
	#		args.dry_run or i.path.unlink()
	
	## Pass 4: check_dirs ##
	if (args.transcode or args.rename) and args.remove:
		args.dry_run and log.info("Dry run selected: empty directories won't be found")
		errored = set()
		alldirs = set()
		for d in reversed(sorted(check_dirs, key=lambda p:len(str(p)))):
			log.debug(f"Checking {str(d)!r}")
			d = d / "file"
			for par in d.parents:
				if par.samefile("."):
					continue
				for spec in args.paths:
					if par.is_relative_to(spec):
						alldirs.add(par)
						break

		for d in reversed(sorted(alldirs, key=lambda p:len(str(p)))):
			try:
				for e in errored:
					if e.is_relative_to(d):
						raise FoundItException
			except FoundItException:
				continue

			try:
				args.verbose and print(f"rmdir {str(d)!r}")
				args.dry_run or d.rmdir()
			except OSError:
				args.dry_run and log.warning(f"{str(d)!r} not empty")
				errored.add(d)
