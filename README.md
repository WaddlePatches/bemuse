# bemuse
Yet another tool to rename or transcode music files based on metadata, but with Replaygain tags.

## Usage
`bemuse.py [-h] [-A] [-c CONFIG] [-d DIRECTORY] [-D FILE] [-E] [-G] [-f FORMAT] [-K] [-L] [-m REGEX] [-n] [-P PRESET] [-R] [-T CODEC] [-v] [paths ...]`

`paths` is a list of directories or files that will be scanned. If none are given, then the current directory will be assumed.

### optional arguments:
* `-h`, `--help`
* `-A`, `--album-art` **(operational mode)**
  * Detected image files will be copied based on format rules. See *Album Art* and *Format Rules* below
* `-c CONFIG`, `--config CONFIG`
  * Load a config file `CONFIG`. Defaults to `$HOME/.config/bemuse.cfg`
* `-d DIRECTORY`, `--dest DIRECTORY`
  * The target directory new or moved files will be placed in
* `-D FILE`, `--from-file FILE`
  * Read in a list of `paths` from the given `FILE`. Can be specified multiple times
* `-E`, `--adjust-metadata`
  * Apply metadata rules from the config file. See *Config File*/*Metadata Section* below
* `-f FORMAT`, `--format FORMAT`
  * The target filename rules. See *Format Rules* below
* `-G`, `--replaygain` **(operational mode)**
  * Write ReplayGain tags (requires `loudgain` tool, https://github.com/Moonbase59/loudgain)
* `-K`, `--remove`
  * Delete the original file once finished, and any empty directories left over
* `-L`, `--list` **(operational mode)**
  * Print generated filenames without further operations
* `-m REGEX`, `--match REGEX`
  * Only perform operations on files with names that match the given (Python type) regex
* `-n`, `--dry-run`
  * Print information about the operations without performing them
* `-P PRESET`, `--preset PRESET`
  * Select the named `PRESET` from the config file
* `-R, --rename` **(operational mode)**
  * Rename or move the files according to the given format. **This will overwite files that already exist**
* `-T CODEC`, `--transcode CODEC` **(operational mode)**
  * Convert files using `CODEC` rules from the config file. **This will overwite files that already exist**
* `-v`, `--verbose`
  * Increase verbosity level (can be specified multiple times).
  * 0 times: only output if `-L` or `-n` is specified
  * 1 time: output basic information about what file is going where, and if empty directories will be removed
  * 2 times: debug level "INFO"
  * 3 or more times: debug level "DEBUG"

# Config File
The config file is an INI-type format, using Python's built-in `configparser` library. Interpolation is disabled.

## `[Format]` section
This section defines the filename presets that can be specified with `--preset`. The special name `default` specifies which preset will be used if `--preset` and `--format` are not given. See *Format Rules* below.

## `[Metadata]` section
If `--adjust-metadata` is given, then tags are added to (or, if left blank, removed from) each file according to these rules. The key names specify the metadata field, and the values are the same type as used for *Format Rules* (see below).

## `[Transcode:CODEC]` sections
Each `[Transcode:CODEC]` section defines codec rules that can be speficied with the `--transcode` option. The name after the `:` in the section name is what is matched against the `CODEC` option on the commandline.

`file_suffix` specifies the new filename suffix (including the `.` character), as this is not included in *Format Rules* (see below).

`codec` values, including those where a stream specifier is given (e.g. `codec:a`) can include a special value delimited by an exclamation mark `!`. The name before the `!` is the `ffmpeg` encoder name, and the name after the `!` is the decoder name, which is used to determine if a file can be skipped for transcoding. The decoder name for a file can be found with `ffprobe -show_entries stream | grep codec_name`

All other options are passed to `ffmpeg`.

## `[Tools]` section (TODO)
Provides paths to external tools required for functionality. `ffmpeg`, `ffprobe`, and `loudgain`

## Example config file
```ini
[Format]
default = modern
# NB: File extensions are not included in the format strings
classical = {composer!w?}/{album!w}/{.adisc?Disc {disc}/#.}{track:02?}-{composerlastname!w?}-{title!w}
modern = {.album_artist!w?{album_artist}#{artist}.}/{album!w}/{.adisc?Disc {disc}/#.}{track:02?}-{title!w}

[Metadata]
artistsort = {composerlastname!u}
composersort = {composerlastname!u}

[Transcode:opus]
file_suffix = .opus
# The following fields will be passed to ffmpeg
codec:a = libopus!opus
b:a = 256000
r:a = 48000
vbr = on
application = audio
```

# Format Rules (the Strink formatter)
The format language is based on Python's *Format Specification Mini-Language* https://docs.python.org/3/library/string.html#formatspec.
* `{{`, `}}`, and `##` are escaped literals, that resolve to `{`, `}` and `#` respectively
* Variable fields are enclosed between `{` and `}`, or `{.` and `.}` (e.g. `{artist}`)
* Field names must conform to `[a-zA-Z][a-zA-Z0-9_]*`. Pythonic features like subscripting and attribute referencing are not supported
* The alignment operator `:` is supported
  * The default alignment is `>`, not `=`
  * e.g. `{artist:10}` will right-align the `ARTIST` value to (at least) 10 characters wide
  * e.g. `{track:03}` will zero-fill the `TRACK` value to 3 characters wide
  * e.g. `{track:#^5}` will centre the `TRACK` in `#` characters, (at least) 5 characters wide
* The conversion operator `!` is supported, and the following conversions are added:
  * `u` removes all accents from characters
  * `w` removes all accents from characters, and strips any characters not allowed in Windows filenames
  * e.g. `{album!w}/{title!w}`
* A conditional operator `?` and `?#` is added, which must appear after both the `:` and `!` clauses if present
  * `?` on its own will return the field value if it is present, otherwise an empty string
    * e.g. `{invalidtag?}` => "", `{title?}` => "Track Title"
  * `?` with text following it will format the following text, if the given field name is present, otherwise an empty string
    * e.g. `{.album_artist?{album_artist}/{artist}.}`
  * `?` with a `#` clause works as an if/else
    * e.g. `{.album_artist?{album_artist}/{artist}#{artist}.}` will resolved to `ALBUM_ARTIST`/`ARTIST` if `ALBUM_ARTIST` is present, otherwise to `ARTIST`
  * Conditionals can be nested
  * NB: the presence of a variable is tested before alignment and conversion are performed

The following metadata tags are calculated programatically, and can be used even if they are not present in the media files:
|Field|Related tag|Description|
|-----|-----------|-----------|
|`{adisc}`|`DISC`|If all media files with the same `{album}` value have the same `{disc}` value, then `{adisc}` will be blank, otherwise `{disc}`|
|`{artist_the}` and `{album_artist_the}`|`ARTIST` and `ALBUMARTIST`|If the artist value begins with the word "the", it is moved to the end (e.g. "The Who" → "Who, The")|
|`{composerfirstnames}`|`COMPOSER`|All *except* the last space-separated sub-field of `{composer}`|
|`{composerinitials}`|`COMPOSER`|The first character of each space-separated sub-field of `{composerfirstnames}`|
|`{composerlastname}`|`COMPOSER`|The last space-separated sub-field of `{composer}`|
|`{title}`|Filename|If `{title}` is not already set, match the original filename|

The `-Lf FORMAT` (and `-nf FORMAT`, when combined with other operational modes) options are recommended for testing.

# Album Art
If `--album-art` is given, then image files will be copied (or moved if `--remove` is specified) based on format rules.

All files that `ffprobe` reports as a video with only single frame are considered images.

Metadata is attached to image files with the following rules when scanning directories:
* `{title}` always resolves to the original image filename
* `{track}` is never present
* Any metadata where the value is equal across all the tracks in the same directory as an image is attached
* Any tracks in subdirectories of where an image is found are also checked for matching metadata values
* If an image is found in a directory, metadata is not attached to images found in parent directories

It may be necessary for your needs to write an "albumart" preset into your config file, along the lines of:
```ini
[Format]
albumart = {.album_artist!w?{album_artist_the}#{artist_the}.}/{album}
```
The caveat here is that if you only specify the `--album-art` operational mode, then all your media files will still need to be scanned, in order to attach the metadata.

NB: due to metadata collection, all album art will be processed only after all other media files have been processed, but on a per `path` basis.

# Known Issues
* Need better distinction for operational mode arguments
* `--match` option not validated properly
* No support for multiple *different* albums with the same name (they will all be treated as the same album, for both album art and ReplayGain purposes)
* No sensible progress indicators
* No non-English language support (i.e. for `{artist_the}`)
* Album art image detection needs to be more rugged
* Errors from `loudgain` and `ffmpeg` are ignored if not fatal
* Untested on Windows, OSX, etc.
* internals: monolithic code style
* debug: inconsistent messaging

# TODO
1. Actually upload the source (:
2. Add an argument to specify an album-art preset, different to media file preset
3. Implement system installation (install `strink` library)
4. Add `[Tools]` section to config file
5. Modularise, add signalling system for progress (allow for GUI)
  * remove semi-hardcoded `ffprobe` output sections
  * eventually use libavc* instead of calling `ffmpeg` and `ffprobe`
  * eventually use libebur128 instead of calling `loudgain`
