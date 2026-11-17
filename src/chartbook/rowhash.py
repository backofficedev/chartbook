"""Rows hashes: a hash of a table's rows, and not of its file.

A content hash (:mod:`chartbook.hashing`) names the bytes of a file. Two
people who build the same table get the same rows in other bytes: another
parquet writer, another compression, another order of rows. And a table
that follows a source gains rows after its last date between one pull and
the next. A rows hash says "the same rows" where a content hash cannot
(``docs_src/design/pins-and-rebuilds.md``).

Like the content hash, it is computed in one place, here, and its form is
part of the index specification (``docs_src/design/index-schema.md``,
"The rows hash"). It is ChartBook's own: polars' ``hash_rows`` is not
stable from one version of polars to the next, and the machine that pins
and the machine that checks do not have the same one.

**The form.** A table's rows are put in one form, whatever wrote them:

- *Every column in the one type of its kind.* A whole number is 64 bits,
  signed; a number with a fraction is a 64-bit float, with ``-0.0`` as
  ``0.0`` and one NaN; a date or a time on a day is a count of
  microseconds from 1970 in UTC, with what is finer than a microsecond
  kept beside it; a category is its text.
- *The rows sorted on every column*, the date column first and the rest in
  the order of their names, each column least first: an empty value after
  every value, NaN after every number, text by its UTF-8 bytes.
- *The columns taken in the order of their names*, and each column's
  values fed to SHA-256 as plain little-endian numbers and UTF-8 text with
  its lengths, with a bit for each empty value (:func:`_feed`).

So the hash does not see the writer, the compression, the order of the
rows or of the columns, or whether the table is one file, a folder or a
glob. It does see every value of every column.

**By period.** A table with a date column is hashed a period at a time: a
calendar year, or a month or a day of one where a year's rows are too many
to hold (:func:`hash_rows`). Each period is written by the first and the
last timestamp seen in it, both included, so the record holds no date that
has not happened. The periods are a function of the rows alone: what a
year's rows count for is counted from the rows (:func:`row_bytes`), never
from the file they came in, so the same rows give the same record. Whoever
checks reads the periods from the record and hashes their own rows in
those same periods, leaving out the rows after the record's last timestamp
(:func:`hash_in`).

**Memory.** A period's rows are what is held at once, never the table: the
files are read a few thousand rows at a time, each row is put in a scratch
file for its year, a year that is too large is put again by month and such
a month by day, and each period is then sorted and hashed alone. The size
of a period is fixed here (:data:`PERIOD_BYTES`), for a machine with 8 GB,
and is not taken from the machine that pins: the author may pin on 64 GB,
and a student then hashes those same periods on 8.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union

#: What every rows hash begins with: the name of the form. A change to the
#: form takes another name here and another prefix on the hash.
FORM = b"chartbook/rows/v1\n"

#: The most a period's rows count for, in bytes (:func:`row_bytes`): a year
#: over this is split into months, and a month over it into days. Sorting
#: and feeding a period takes a few times its size, so this is what sets
#: the peak. It is fixed, and no setting: the machine that checks a pin has
#: to hold the periods the machine that pinned chose.
PERIOD_BYTES = 128 * 1024 * 1024

#: What a column counts for in a row, in bytes, when a period is measured;
#: a value of text or binary counts for its own bytes besides.
COLUMN_BYTES = 8

#: The most rows hashed as one piece that cannot be split: one day of a
#: dated table, or the whole of a table with no date column. A table with
#: more than this in one piece has no rows hash, and is pinned by its bytes
#: alone.
MOST_BYTES = 2 * PERIOD_BYTES

#: The most a table in another format than parquet may take on disk to
#: have a rows hash, and how many times its size a gzipped file counts
#: for. Only parquet is read a little at a time: any other format is read
#: whole, once, which took about five times the table in memory when it
#: was measured (an Arrow file of 219 MB peaked at 1.4 GB).
OTHER_BYTES = PERIOD_BYTES
OTHER_ZIPPED = 8

#: The most columns a table is read with. A file is read a few thousand
#: rows at a time, and still a page or two of every column is held while it
#: is: about 2.7 MB a column was measured, which at 1000 columns is more
#: than a period. A wider table has no rows hash.
MOST_COLUMNS = 256

#: How much of a file is read at a time, in bytes as Arrow holds them.
BATCH_BYTES = 8 * 1024 * 1024

#: The key of the period of the rows whose date is empty, and of the one
#: hash of a table with no date column.
NO_DATE = "none"
ALL = "all"

#: The column pandas writes a frame's index into when the index has no
#: name. Where it holds row positions left from an earlier step, they shift
#: when a pull has more rows, and no row is then the row it was.
INDEX_COLUMN = "__index_level_0__"

_DAY = 86_400_000_000  # microseconds
_EPOCH = datetime(1970, 1, 1)


class NotHashed(Exception):
    """Raised when a table's rows have no hash: a column of a kind the form does not take, or a piece too large to hold.

    Such a table is pinned by its bytes alone, and what reads this says so.
    """


class NotRead(NotHashed):
    """Raised when a table's rows have no hash because its files could not be read as a table at all.

    What reads this says nothing more: a dataframe that is not a table is
    said to be one where it is read (:mod:`chartbook.formats`).
    """


# --- The form -----------------------------------------------------------------


def _polars():
    import polars as pl

    return pl


def _kind_of(name: str, kind) -> str:
    """The kind a column of this polars type is hashed as; :class:`NotHashed` for one the form does not take."""
    pl = _polars()
    if kind == pl.Boolean:
        return "bool"
    if kind.is_integer():
        return "int"
    if kind.is_float():
        return "float"
    if isinstance(kind, pl.Decimal) or kind == pl.Decimal:
        return "decimal"
    if kind == pl.Date or isinstance(kind, pl.Datetime) or kind == pl.Datetime:
        return "timestamp"
    if isinstance(kind, pl.Duration) or kind == pl.Duration:
        return "duration"
    if kind == pl.Time:
        return "time"
    if kind == pl.String or kind == pl.Categorical or kind == pl.Enum or isinstance(kind, (pl.Categorical, pl.Enum)):
        return "text"
    if kind == pl.Binary:
        return "binary"
    if kind == pl.Null:
        return "null"
    raise NotHashed(f"column {name!r} is {_type_said(kind)}, and a rows hash takes no such column yet")


def _type_said(kind) -> str:
    """A polars type as a message names it: in full, or its beginning where it goes on (a struct of a hundred fields)."""
    said = str(kind)
    return said if len(said) <= 80 else f"{said[:60]}… ({len(said):,} characters)"


def kinds_of(schema) -> dict:
    """The kind each column of a polars schema is hashed as by its type, by name; :class:`NotHashed` if one is of no kind.

    What a column's rows then make of it is told when they are hashed: an
    unsigned 64-bit column with a number past 63 bits is ``uint64``, and a
    column with no value in it is ``null``.
    """
    return {name: _kind_of(name, kind) for name, kind in schema.items()}


def _refused():
    """What polars raises for a value that cannot be put in a column's one type: its errors, and its panics, which are no Exception."""
    pl = _polars()
    return (pl.exceptions.PolarsError, pl.exceptions.PanicException)


def _normal(frame):
    """A frame with every column in the one type of its kind, ready to sort; each column's kind and, for a time, its unit; and the name each column goes by in it.

    A timestamp or a duration is left as a whole number in the unit it
    came in, nanoseconds or microseconds, which sorts as it does; what is
    fed is worked out from it (:func:`_feed`). A decimal is left as it is,
    which sorts by its value.

    The columns are taken by their place and given names of ChartBook's
    own while they are worked on (``c0``, ``c1``, …): polars reads a name
    that begins ``^`` and ends ``$`` as a pattern, and a column so named
    would be passed over without a word.
    """
    pl = _polars()
    columns, kinds, units, where = [], {}, {}, {}
    for place, (name, kind) in enumerate(frame.schema.items()):
        column = pl.nth(place)
        said = _kind_of(name, kind)
        if said == "int":
            if kind == pl.UInt64:
                most = frame.to_series(place).max()
                if most is not None and most > 2**63 - 1:
                    said = "uint64"  # past what 64 signed bits hold: its own kind
                else:
                    column = column.cast(pl.Int64)
            elif kind != pl.Int64:
                column = column.cast(pl.Int64)  # one past 64 bits is refused below
        elif said == "float":
            column = column.cast(pl.Float64)
            # One zero and one NaN, before the sort: either would put a row elsewhere
            column = (
                pl.when(column.is_nan()).then(pl.lit(float("nan"), dtype=pl.Float64))
                .when(column == 0.0).then(pl.lit(0.0, dtype=pl.Float64))
                .otherwise(column)
            )
        elif said == "timestamp":
            # The whole number a time is held as: days for a date, and for a time with a
            # zone the instant, which is the time in UTC
            column = column.to_physical().cast(pl.Int64)
            if kind == pl.Date:
                column, unit = _in_microseconds(frame, place, name, column, 86_400_000_000), "us"
            else:
                unit = kind.time_unit
                if unit == "ms":
                    column, unit = _in_microseconds(frame, place, name, column, 1000), "us"
            units[name] = unit
        elif said == "duration":
            unit = kind.time_unit
            column = column.to_physical().cast(pl.Int64)
            if unit == "ms":
                column, unit = _in_microseconds(frame, place, name, column, 1000), "us"
            units[name] = unit
        elif said == "time":
            column = column.cast(pl.Int64)
        elif said == "text" and kind != pl.String:
            column = column.cast(pl.String)
        kinds[name] = said
        where[name] = f"c{place}"
        columns.append(column.alias(where[name]))
    try:
        frame = frame.select(columns)
    except _refused() as error:  # a number past 64 bits, a date past what microseconds hold
        said = str(error).strip()
        raise NotHashed(
            f"its columns cannot be put in one form: {said.splitlines()[0] if said else type(error).__name__}"
        ) from None
    # A column with no value in it has no kind: whatever type its writer gave it
    for name, held in where.items():
        if frame.get_column(held).null_count() == frame.height:
            kinds[name] = "null"
    return frame, kinds, units, where


def _in_microseconds(frame, place: int, name: str, whole, each: int):
    """A column of days or of milliseconds, as whole numbers, in microseconds.

    Worked out here and not by a cast, and one past what 64 bits of
    microseconds hold is refused here: what a cast does with such a value
    is not one thing from one polars to the next (one stops, one panics,
    one wraps it round without a word), and a hash has to be.

    :raises NotHashed: If a value is past what microseconds hold.
    """
    held = frame.to_series(place).to_physical()
    least, most = held.min(), held.max()
    reach = (2**63 - 1) // each
    if least is not None and (least < -reach or most > reach):
        raise NotHashed(
            f"its columns cannot be put in one form: column {name!r} has a time past what 64 bits of microseconds hold"
        )
    return whole * each


def _names(names: Iterable[str]) -> list:
    """Column names in the order they are taken in: by their UTF-8 bytes."""
    return sorted(names, key=lambda name: name.encode("utf-8"))


def _sorted(frame, where: dict, first: Optional[str]):
    """A normal frame's rows sorted on every column: *first* first, then the rest in the order of their names; empty values last."""
    by = ([where[first]] if first in where else []) + [where[name] for name in _names(where) if name != first]
    if not by or frame.height < 2:
        return frame
    return frame.sort(by, nulls_last=True)


def _decimal_text(series):
    """A decimal column as text, each value written one way: plain digits, no zeros after its last digit, and no ``-0``."""
    pl = _polars()
    text = series.cast(pl.String)
    if getattr(series.dtype, "scale", 0):
        text = text.str.strip_chars_end("0").str.strip_chars_end(".")
    return text.replace("-0", "0")


def _feed(digest, frame, kinds: dict, units: dict, where: dict) -> None:
    """Feed a sorted, normal frame to a digest.

    First :data:`FORM`, then the number of rows and of columns, each as 8
    bytes, little-endian. Then each column, in the order of the names:

    - the length of its name in UTF-8, as 8 bytes, and the name; the length
      of its kind, as 1 byte, and the kind (``int``, ``uint64``, ``float``,
      ``bool``, ``text``, ``binary``, ``timestamp``, ``duration``, ``time``,
      ``decimal``, ``null``);
    - one byte, 0 if no value is empty; else 1, and a bit for each row, set
      where its value is empty, the first row in the high bit of the first
      byte;
    - its values, an empty one as zero or as no bytes: a whole number, a
      time of day in nanoseconds, as 8 bytes each; a float as 8 bytes
      each, IEEE 754; a boolean as a bit each, packed as the empty bits
      are; text and binary as the length of each in bytes, 8 bytes each,
      and then all their bytes; a decimal as its text;
    - a timestamp or a duration as its whole microseconds, 8 bytes each,
      rounded down, then one byte: 0 if none has anything finer, else 1 and
      the nanoseconds left over (0 to 999) of each, 8 bytes each.

    Every number is little-endian, on a machine of either kind.

    :param where: The name each column goes by in *frame*, by its own name
        (:func:`_normal`).
    """
    import numpy as np
    import pyarrow as pa

    pl = _polars()
    digest.update(FORM)
    digest.update(struct.pack("<QQ", frame.height, frame.width))
    for name in _names(where):
        series = frame.get_column(where[name])
        kind = kinds[name]
        raw = name.encode("utf-8")
        digest.update(struct.pack("<Q", len(raw)) + raw + struct.pack("<B", len(kind)) + kind.encode("ascii"))
        if series.null_count():
            digest.update(b"\x01" + np.packbits(series.is_null().to_numpy()).tobytes())
        else:
            digest.update(b"\x00")
        if kind == "null":
            continue
        if kind in ("text", "binary", "decimal"):
            if kind == "decimal":
                series = _decimal_text(series)
            if series.null_count():
                series = series.fill_null(b"" if kind == "binary" else "")  # an empty value takes no bytes
            array = series.to_arrow(compat_level=pl.CompatLevel.oldest())
            if isinstance(array, pa.ChunkedArray):
                array = array.combine_chunks()
            array = array.cast(pa.large_binary() if kind == "binary" else pa.large_string())
            validity, offsets, values = array.buffers()
            starts = np.frombuffer(offsets, dtype="<i8", count=len(array) + 1, offset=array.offset * 8)
            digest.update(np.ascontiguousarray(np.diff(starts).astype("<u8", copy=False)))
            if values is not None and len(array):
                digest.update(memoryview(values)[int(starts[0]): int(starts[-1])])
        elif kind == "float":
            digest.update(np.ascontiguousarray(series.fill_null(0.0).to_numpy().astype("<f8", copy=False)))
        elif kind == "bool":
            digest.update(np.packbits(series.fill_null(False).to_numpy()).tobytes())
        elif kind == "uint64":
            digest.update(np.ascontiguousarray(series.fill_null(0).to_numpy().astype("<u8", copy=False)))
        elif kind in ("timestamp", "duration"):
            whole = series.fill_null(0).to_numpy().astype("<i8", copy=False)
            if units.get(name) == "ns":
                # What arithmetic gives is in the machine's own byte order: said again
                micro = np.floor_divide(whole, 1000).astype("<i8", copy=False)
                left = (whole - micro * 1000).astype("<i8", copy=False)
                digest.update(np.ascontiguousarray(micro))
                if left.any():
                    digest.update(b"\x01")
                    digest.update(np.ascontiguousarray(left))
                else:
                    digest.update(b"\x00")
            else:
                digest.update(np.ascontiguousarray(whole))
                digest.update(b"\x00")
        else:  # int, time
            digest.update(np.ascontiguousarray(series.fill_null(0).to_numpy().astype("<i8", copy=False)))


def hash_frame(frame, date_col: Optional[str] = None) -> str:
    """The rows hash of a polars DataFrame held in memory: all of its rows, as one piece.

    :param date_col: The column the rows are sorted on first: the table's
        date column. With none, or one the frame does not have, the rows
        are sorted on the columns in the order of their names. It is part
        of the form: sorted on another column first, rows that are alike
        in that one may be fed in another order.
    :raises NotHashed: If a column is of a kind the form does not take, or
        holds a value its kind's one type cannot.
    :raises TypeError: If *frame* is not a polars DataFrame.
    """
    if not isinstance(frame, _polars().DataFrame):
        raise TypeError(f"hash_frame takes a polars DataFrame, and was given a {type(frame).__name__}")
    normal, kinds, units, where = _normal(frame)
    del frame  # from here it is the frame in its one form, and then that sorted, that are held
    digest = hashlib.sha256()
    _feed(digest, _sorted(normal, where, date_col), kinds, units, where)
    return "sha256:" + digest.hexdigest()


# --- Timestamps, as a record writes them ---------------------------------------

#: A timestamp as a record writes it, and nothing else: a date, and a time
#: to the second, with six digits of a second's fraction or nine.
_STAMP = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{6})(\d{3})?)?)?", re.ASCII)


def stamp_text(micro: int, left: int = 0) -> str:
    """A timestamp as a record writes it, in UTC: a date alone at midnight, else to the second or as fine as it is.

    ``2026-10-30``, ``2026-10-30T16:00:00``, ``2026-10-30T16:00:00.250000``,
    and with nanoseconds, ``2026-10-30T16:00:00.250000001``.

    :raises NotHashed: For a timestamp outside the years 1 to 9999, which
        has no such text.
    """
    days, within = divmod(micro, _DAY)
    try:
        day = (_EPOCH + timedelta(days=days)).date().isoformat()
    except OverflowError:
        raise NotHashed("it has a date outside the years 1 to 9999, which a record of rows cannot write") from None
    if not within and not left:
        return day
    seconds, fraction = divmod(within, 1_000_000)
    clock = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    if left:
        return f"{day}T{clock}.{fraction:06d}{left:03d}"
    return f"{day}T{clock}.{fraction:06d}" if fraction else f"{day}T{clock}"


def stamp_of(text: str) -> tuple[int, int]:
    """A timestamp a record wrote (:func:`stamp_text`) as its microseconds from 1970 and the nanoseconds left over.

    :raises ValueError: If it is not one, written as a record writes it.
    """
    matched = _STAMP.fullmatch(text) if isinstance(text, str) else None
    if matched is None:
        raise ValueError(f"{text!r} is not a timestamp a record writes")
    year, month, day, hours, minutes, seconds, fraction, finer = matched.groups()
    try:
        micro = (date(int(year), int(month), int(day)) - _EPOCH.date()).days * _DAY
    except ValueError:
        raise ValueError(f"{text!r} is not a timestamp a record writes") from None
    if hours is not None:
        if int(hours) > 23 or int(minutes) > 59 or int(seconds) > 59:
            raise ValueError(f"{text!r} is not a timestamp a record writes")
        micro += (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1_000_000 + int(fraction or 0)
    return micro, int(finer or 0)


# --- Reading a table a little at a time ----------------------------------------


@contextlib.contextmanager
def _lean():
    """While a table is read and split: Arrow takes its memory from the system, which gets it back when it is let go.

    Arrow's own allocator keeps what it has freed, to hand out again, and a
    process's memory then stands at the most it ever held: about 0.4 GB
    more on a wide table. The pool is the process's, so it is put back as
    it was however this ends.
    """
    import pyarrow as pa

    before = pa.default_memory_pool()
    try:
        pa.set_memory_pool(pa.system_memory_pool())
    except Exception:  # noqa: BLE001 - a pyarrow with no such pool: as it was
        yield
        return
    try:
        yield
    finally:
        pa.set_memory_pool(before)


def _taken(schema) -> None:
    """Refuse a table whose rows are not hashed: a column of no kind, or more columns than are read at once."""
    kinds_of(schema)
    if len(schema) > MOST_COLUMNS:
        raise NotHashed(
            f"it has {len(schema):,} columns, and a rows hash reads at most {MOST_COLUMNS} at once"
        )


@dataclass
class Table:
    """A dataframe's files, as ChartBook's reader reads them, to be read a little at a time.

    Attributes:
        path: The file, the glob or the folder.
        format: Its entry's ``format``, if it has one.
        read_options: Its entry's ``read_options``, if it has them.
        files, listed, inside: For one read from a store, as
            :func:`chartbook.formats.scan` takes them.
    """

    path: Union[str, Path]
    format: Optional[str] = None
    read_options: Optional[dict] = None
    files: tuple = ()
    listed: tuple = ()
    inside: Optional[dict] = None
    _schema: object = field(default=None, repr=False)
    _added: dict = field(default_factory=dict, repr=False)

    @classmethod
    def at(cls, location) -> "Table":
        """The table at a file location (:class:`chartbook.resolve.FileLocation`)."""
        return cls(
            location.path, getattr(location, "format", None), getattr(location, "read_options", None),
            tuple(location.files), tuple(location.listed), getattr(location, "inside", None),
        )

    def scan(self):
        """The whole table as a polars LazyFrame, as ChartBook's reader gives it."""
        from chartbook import formats

        return formats.scan(
            self.path, self.format, self.read_options, files=self.files, listed=self.listed, inside=self.inside
        )

    def schema(self):
        """Its columns and their polars types, as the reader gives them.

        :raises NotRead: If the reader cannot read it as a table.
        """
        if self._schema is None:
            try:
                self._schema = self.scan().collect_schema()
            except Exception as error:  # noqa: BLE001 - whatever the reader raises for what is no table
                raise NotRead(_first_line(error)) from None
            except BaseException as error:  # polars panics are not Exceptions
                if type(error).__name__ != "PanicException":
                    raise
                raise NotRead(_first_line(error)) from None
        return self._schema

    def arrow_schema(self):
        """Its columns as Arrow holds them here: the reader's types, a category as its text."""
        import pyarrow as pa

        pl = _polars()
        plain = {name: pl.String if _kind_of(name, kind) == "text" else kind for name, kind in self.schema().items()}
        empty = pl.DataFrame(schema=plain).to_arrow(compat_level=pl.CompatLevel.oldest())
        return pa.schema(list(empty.schema))

    def on_disk(self) -> int:
        """How many bytes its files take on disk; 0 where that cannot be told."""
        from chartbook import formats

        try:
            read = formats.reading(self.path, self.format, self.read_options)
            return sum(os.path.getsize(file) for file in formats.files_of(self.path, read, self.files, self.listed, self.inside))
        except Exception:  # noqa: BLE001 - nothing there, or a format ChartBook does not read: said where it is read
            return 0

    def batches(self, scratch: Optional[Path] = None) -> Iterator:
        """Its rows as Arrow record batches of a few thousand rows each, in no promised order, with the reader's columns.

        A parquet file is read by pyarrow a batch at a time, which holds
        one batch and not a row group. What the reader adds to a file's own
        columns, the ``key=value`` folders of its path, is asked of the
        reader for each file and put on its batches; a file the store keeps
        once for two partitions is read once for each, with each one's keys.
        Any other format is read whole by polars and written out as parquet
        once, into *scratch*, and read from there: so one over
        :data:`OTHER_BYTES` on disk is refused.

        :param scratch: A folder for the copy a format other than parquet
            is read through.
        :raises NotHashed: For a table in another format than parquet that
            is too large to read whole.
        :raises NotRead: If a file cannot be read a batch at a time.
        """
        from chartbook import formats

        pl = _polars()
        read = formats.reading(self.path, self.format, self.read_options)
        target = self.arrow_schema()
        if read.format != "parquet":
            if scratch is None:
                raise ValueError("a format other than parquet is read through a scratch folder")
            copy = Path(scratch) / "table.parquet"
            if not copy.exists():
                self._small_enough(read)
                try:
                    self.scan().sink_parquet(copy, row_group_size=50_000)
                except OSError:
                    raise  # the scratch folder, most likely: no fault of the table's
                except Exception as error:  # noqa: BLE001 - whatever polars raises for a file it cannot read through
                    raise NotRead(f"it could not be read ({_first_line(error)})") from None
            yield from _parquet_batches(copy, target, None)
            return
        sources, folder = formats._sources(Path(self.path), read, self.files, self.listed, self.inside)
        apart = formats._kept_apart(sources, self.inside)
        if apart:
            # Where the store keeps a file does not say its keys: each is read for each
            # path it has inside the table, with that path's keys, as the reader reads it
            try:
                first = formats._scan_files(pl.scan_parquet, [apart[0][0]], hive_partitioning=False).collect_schema()
                keys = formats._keys_of_pairs(apart, first)
            except Exception as error:  # noqa: BLE001 - whatever the reader raises for files it cannot read
                raise NotRead(f"its files could not be read ({_first_line(error)})") from None
            for place, (location, _) in enumerate(apart):
                put = {key: pl.Series(key, [values[place]], dtype=kind) for key, (kind, values) in keys.items() if key in target.names}
                yield from _parquet_batches(location, target, pl.DataFrame(list(put.values())) if put else None)
            return
        found = formats.files_of(self.path, read, self.files, self.listed, self.inside)
        by_file = formats._by_location(self.inside)
        alone = len(found) == 1 and folder is None
        for file in found:
            # Asked once for each file: a table is read more than once
            if str(file) not in self._added:
                try:
                    one = formats._scan(read, sources if alone else [str(file)], folder, by_file)
                    self._added[str(file)] = _added_by_the_reader(one, file, self.schema().names())
                except NotHashed:
                    raise
                except Exception as error:  # noqa: BLE001 - whatever the reader raises for a file it cannot read
                    raise NotRead(f"{Path(str(file)).name} could not be read ({_first_line(error)})") from None
            added = self._added[str(file)]
            if added is not None:
                # By their place: a name is a pattern to polars when it begins ^ and ends $
                added = added.select([pl.nth(i) for i, name in enumerate(added.columns) if name in target.names])
            yield from _parquet_batches(file, target, added if added is None or added.width else None)

    def _small_enough(self, read) -> None:
        """Refuse a table in another format than parquet that is too large to be read whole."""
        from chartbook import formats

        files = formats.files_of(self.path, read, self.files, self.listed, self.inside)
        zipped = sum(os.path.getsize(file) for file in files if str(file).lower().endswith(".gz"))
        plain = sum(os.path.getsize(file) for file in files) - zipped
        if plain + OTHER_ZIPPED * zipped > OTHER_BYTES:
            raise NotHashed(
                f"it is {read.format}, {(plain + zipped) / 2**20:,.0f} MB on disk, and only parquet is read a little "
                f"at a time: a table in another format has a rows hash up to {OTHER_BYTES // 2**20} MB "
                f"({OTHER_BYTES // OTHER_ZIPPED // 2**20} MB gzipped)"
            )


def _first_line(error: BaseException) -> str:
    said = str(error).strip()
    return said.splitlines()[0][:300] if said else type(error).__name__


def _added_by_the_reader(one, file, wanted: list):
    """What the reader puts on one file's rows beside the file's own columns: a polars frame of one row, or None.

    Asked of the reader, for this file among its fellows (*one* is its
    read of the file): the columns the file does not have, which are the
    ``key=value`` folders of its path; and a column the file has too that
    a folder of its path names, where the reader gives one value of it for
    the whole file, which is then the folder's and not the file's own.
    """
    import pyarrow.parquet as pq

    from chartbook import formats

    pl = _polars()
    names = one.collect_schema().names()
    opened = pq.ParquetFile(str(file))
    own = set(opened.schema_arrow.names)
    extra = [name for name in names if name in wanted and name not in own]
    named = {key for key, _ in formats._keys_of(Path(str(file)).parent)}
    doubtful = [name for name in names if name in wanted and name in own and name in named]
    if doubtful and opened.metadata.num_rows:
        # One value in the whole file, as the reader reads it: the key's, put in place of
        # the file's own column, or a column that says the same in every row, which is the same thing
        counted = one.select([pl.nth(names.index(name)).n_unique().alias(f"n{i}") for i, name in enumerate(doubtful)]).collect()
        extra.extend(name for i, name in enumerate(doubtful) if counted[f"n{i}"][0] == 1)
    if not extra:
        return None
    return one.select([pl.nth(names.index(name)) for name in extra]).head(1).collect()


def _parquet_batches(file, target, added) -> Iterator:
    """One parquet file's rows as Arrow record batches of the *target* schema, a batch at a time; *added* is a frame of one row whose columns go on every row."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    pl = _polars()
    constant = {}
    if added is not None:
        plain = added.select(
            [
                pl.nth(i).cast(pl.String) if _kind_of(name, kind) == "text" else pl.nth(i)
                for i, (name, kind) in enumerate(added.schema.items())
            ]
        ).to_arrow(compat_level=pl.CompatLevel.oldest())
        constant = {name: plain.column(name)[0] for name in plain.column_names}
    try:
        opened = pq.ParquetFile(str(file), pre_buffer=False)
        own = [name for name in target.names if name in opened.schema_arrow.names and name not in constant]
        metadata = opened.metadata
        # A little of each column at a time, and never a column chunk whole
        buffer = max(64 * 1024, min(1024 * 1024, (48 * 1024 * 1024) // max(1, len(own))))
        opened = pq.ParquetFile(str(file), pre_buffer=False, buffer_size=buffer)
        rows = max(1, metadata.num_rows)
        size = sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups))
        # About twice what the file says, uncompressed: text takes more in memory than in a file
        a_row = max(1, 2 * size // rows)
        at_a_time = int(max(256, min(65_536, BATCH_BYTES // a_row)))

        def finished(batch):
            count = batch.num_rows
            arrays = []
            for item in target:
                if item.name in constant:
                    array = pa.repeat(constant[item.name], count)
                else:
                    array = batch.column(item.name)
                if array.type != item.type:
                    array = array.cast(item.type)
                arrays.append(array)
            return pa.RecordBatch.from_arrays(arrays, schema=target)

        if not own:
            # Nothing of the file's own is wanted: only how many rows it has
            for start in range(0, metadata.num_rows, at_a_time):
                count = min(at_a_time, metadata.num_rows - start)
                yield finished(pa.RecordBatch.from_arrays([pa.nulls(count)], names=["__none__"]))
            return
        for batch in opened.iter_batches(batch_size=at_a_time, columns=own, use_threads=True):
            if batch.num_rows:
                yield finished(batch)
    except NotHashed:
        raise
    except Exception as error:  # noqa: BLE001 - whatever pyarrow raises for a file it cannot read, or a type it cannot cast
        raise NotRead(f"{Path(str(file)).name} could not be read a batch at a time ({_first_line(error)})") from None


# --- Periods ---------------------------------------------------------------------


def _stamps(column):
    """Each timestamp of a date column, as whole microseconds from 1970 in UTC and the nanoseconds left over (None where the column has none), with a mask of the rows that have no date.

    A date or a datetime as it is; text read as a date where it is
    written as one (:func:`_dates_in_text`), and a row with no date where
    it is not. Days and milliseconds are put in microseconds here, by
    ChartBook's own arithmetic after its own check of the range, as the
    form puts them (:func:`_in_microseconds`).

    :param column: The column, as an Arrow array or a polars Series.
    :raises NotHashed: If the column holds no dates, or one past what 64
        bits of microseconds hold.
    """
    import numpy as np

    pl = _polars()
    series = column if isinstance(column, pl.Series) else pl.from_arrow(column)
    name = series.name
    kind = series.dtype
    if kind == pl.String:
        series = _dates_in_text(series)
        kind = series.dtype
    if kind != pl.Date and not isinstance(kind, pl.Datetime):
        raise NotHashed(f"its date column{f' {name!r}' if name else ''} is {_type_said(kind)}, which is no date")
    empty = series.is_null().to_numpy()
    # The whole number a time is held as: days for a date, and for a time with a zone the instant
    whole = series.to_physical().cast(pl.Int64).fill_null(0).to_numpy().astype("int64", copy=False)
    unit = "d" if kind == pl.Date else kind.time_unit
    each = {"d": _DAY, "ms": 1000}.get(unit)
    if each is not None:
        reach = (2**63 - 1) // each
        if whole.size and (int(whole.min()) < -reach or int(whole.max()) > reach):
            raise NotHashed(
                f"its columns cannot be put in one form: column {name!r} has a time past what 64 bits of microseconds hold"
            )
        return whole * each, None, empty
    if unit == "ns":
        micro = np.floor_divide(whole, 1000)
        return micro, whole - micro * 1000, empty
    return whole, None, empty


#: What text has to be for a date to be read in it: ISO 8601, a date alone
#: or with a time to the minute, the second or a fraction of one down to
#: the microsecond, with an offset or none. Anything else is no date: a
#: space before it, a month of one digit, a finer fraction.
_ISO_DATE = r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"

#: How such a date is written, each tried in turn. Fixed, and not guessed
#: from a column's first values, so that a value is read the same in every
#: batch and on every machine.
_TEXT_DATES = (
    ("%Y-%m-%d", False),
    ("%Y-%m-%dT%H:%M:%S%.f", False),
    ("%Y-%m-%d %H:%M:%S%.f", False),
    ("%Y-%m-%dT%H:%M", False),
    ("%Y-%m-%d %H:%M", False),
    ("%Y-%m-%dT%H:%M:%S%.f%#z", True),
    ("%Y-%m-%d %H:%M:%S%.f%#z", True),
)


def _dates_in_text(series):
    """A text column's dates, in microseconds and UTC: each value that is written as one (:data:`_ISO_DATE`), as the first of :data:`_TEXT_DATES` it is written in; no date for any other."""
    pl = _polars()
    written = pl.select(pl.when(series.str.contains(_ISO_DATE)).then(series)).to_series().alias(series.name)
    tried = []
    for form, zoned in _TEXT_DATES:
        try:
            if zoned:
                read = written.str.to_datetime(form, strict=False, time_unit="us", time_zone="UTC").dt.replace_time_zone(None)
            else:
                read = written.str.to_datetime(form, strict=False, time_unit="us", exact=True)
        except Exception:  # noqa: BLE001 - a form this polars does not take: the others are tried
            continue
        tried.append(read)
    if not tried:
        return pl.Series(series.name, [None] * len(series), dtype=pl.Datetime("us"))
    return pl.select(pl.coalesce(tried)).to_series().alias(series.name)


def _ordered(micro, left):
    """Timestamps as numbers that compare as they do: nanoseconds where the column has them, else microseconds (which hold years nanoseconds cannot)."""
    return micro if left is None else micro * 1000 + left


def _bound(stamp: tuple, fine: bool, first: bool = False) -> int:
    """A record's timestamp on the scale :func:`_ordered` gives a column: in microseconds, a first timestamp with nanoseconds left over is the next microsecond; one past what the scale holds is its end."""
    micro, left = stamp
    found = micro * 1000 + left if fine else micro + (1 if first and left else 0)
    return max(-(2**63), min(2**63 - 1, found))


def _span(low: int, high: int, fine: bool) -> tuple:
    """A least and a greatest timestamp on the scale of :func:`_ordered`, each as microseconds and nanoseconds left over."""
    if fine:
        return (divmod(low, 1000), divmod(high, 1000))
    return ((low, 0), (high, 0))


_FIRST_DAY = (date(1, 1, 1) - _EPOCH.date()).days
_LAST_DAY = (date(9999, 12, 31) - _EPOCH.date()).days


def _months(days, empty=None):
    """The calendar month of each day, counted from January of the year 0: a year's months are twelve in a row, and its number is the count over twelve.

    :param days: Day numbers from 1970.
    :param empty: The rows that have no date, whose day is no day.
    :raises NotHashed: If a day is outside the years 1 to 9999.
    """
    import numpy as np

    dated = days if empty is None else days[~empty]
    if dated.size and (int(dated.min()) < _FIRST_DAY or int(dated.max()) > _LAST_DAY):
        raise NotHashed("it has a date outside the years 1 to 9999, which a record of rows cannot write")
    if empty is not None:
        days = np.where(empty, 0, days)
    return days.astype("datetime64[D]").astype("datetime64[M]").astype("int64") + 1970 * 12


def _text_columns(schema) -> list:
    """The places of the columns of text and of binary in an Arrow schema: those whose values have a length of their own."""
    import pyarrow as pa

    return [
        place for place, item in enumerate(schema)
        if pa.types.is_string(item.type) or pa.types.is_large_string(item.type)
        or pa.types.is_binary(item.type) or pa.types.is_large_binary(item.type)
    ]


def row_bytes(batch, text: Optional[list] = None):
    """What each row of an Arrow record batch counts for, in bytes, when a period is measured: :data:`COLUMN_BYTES` for each column, and the bytes of each value of text or binary.

    Counted from the rows alone, so that it is the same number whatever
    wrote them: a whole number is eight bytes whether its file held it in
    one or in eight, a date whether it was a date or a time at midnight, a
    category by its text. It is near what the rows take in memory in the
    one form they are hashed in, and never what a file's types happen to
    take.
    """
    import numpy as np
    import pyarrow.compute as pc

    size = np.full(batch.num_rows, COLUMN_BYTES * batch.num_columns, dtype="int64")
    for place in _text_columns(batch.schema) if text is None else text:
        size += pc.binary_length(batch.column(place)).fill_null(0).to_numpy(zero_copy_only=False).astype("int64", copy=False)
    return size


def _a_day_too_large(first: tuple, rows: int, size: int) -> NotHashed:
    when = stamp_text(first[0] - first[0] % _DAY)
    return NotHashed(
        f"its rows of {when} alone, {rows:,} of them, count for {size / 2**20:,.0f} MB (eight bytes a column and "
        f"the bytes of its text), and a rows hash holds at most a day of {MOST_BYTES // 2**20} MB at a time"
    )


@dataclass
class RowsRecord:
    """What a record says of a dataframe's rows.

    Attributes:
        rows: The hash of the rows of each period, by the period as it is
            written: ``"1961-06-14/1961-12-29"``, the first and the last
            timestamp seen in it; :data:`NO_DATE` for the rows with no
            date; or :data:`ALL` alone, for a table with no date column.
        as_of: The last timestamp in the table, as text; None for a table
            with no date column, or with no dated row.
        row_count: How many rows it has.
        date_col: The column its rows were dated by; None where they were
            hashed as a table with no date column.
    """

    rows: dict
    as_of: Optional[str]
    row_count: int
    date_col: Optional[str] = None

    def fields(self) -> dict:
        """What a snapshot's or a lockfile's record of the dataframe says of its rows: ``date_col``, ``as_of``, ``rows``, ``row_count``."""
        found: dict = {}
        if self.date_col:
            found["date_col"] = self.date_col
        if self.as_of:
            found["as_of"] = self.as_of
        found["rows"] = dict(self.rows)
        found["row_count"] = self.row_count
        return found


#: The fields of a dataframe's record that say its rows: those of
#: :meth:`RowsRecord.fields`; or ``not_hashed``, why its rows have no hash
#: (:class:`NotHashed`), with the ``date_col`` they would have been dated by.
FIELDS = ("date_col", "as_of", "rows", "row_count", "not_hashed")


class NotNow(Exception):
    """Raised when a table's rows could not be hashed this time, for no fault of the table's: no room for scratch files, a folder that cannot be written.

    Nothing is recorded of its rows then, and what made the record says
    so: the next time may hash them.
    """


def dated_by(table: "Table", date_col: Optional[str]) -> Optional[str]:
    """The column a table's rows are dated by: the one its entry declares, where the table has it and it holds dates, or text to read as dates; else None.

    :raises NotRead: If the table cannot be read as one.
    """
    return date_col if _dated_by(table.schema(), date_col) else None


def fields_of(table: "Table", date_col: Optional[str] = None) -> dict:
    """What a record says of a dataframe's rows (:data:`FIELDS`), hashing them now.

    :returns: Its rows by period; or ``not_hashed``, why its rows have no
        hash, with the ``date_col`` they would be dated by; or nothing at
        all for files that cannot be read as a table, of which there is
        nothing to say.
    :raises NotNow: If they could not be hashed this time, for no fault of
        the table's.
    """
    try:
        dated = dated_by(table, date_col)
    except NotRead:
        return {}
    try:
        return hash_rows(table, date_col).fields()
    except NotHashed as error:
        # One the reader reads, so there is something to say: why no rebuild can meet a pin of it
        return {**({"date_col": dated} if dated else {}), "not_hashed": str(error)}
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except BaseException as error:  # noqa: BLE001 - a full disk, a folder that cannot be written, a panic: none of them the table's
        raise NotNow(f"{type(error).__name__}: {_first_line(error)}") from None


@dataclass
class Compared:
    """What a table's rows are beside a record of rows (:func:`hash_in`).

    Attributes:
        differ: The periods of the record whose rows are not the table's,
            as the record writes them, in order.
        outside: How many of the table's rows, up to the record's last
            timestamp, fall in no period of the record: rows the pin did
            not have.
        newer: How many of its rows are after the record's last timestamp.
        rows: How many rows it has in all.
        index_column: Whether the table has the column pandas makes of an
            index with no name (:data:`INDEX_COLUMN`), which may be the
            whole of a difference.
    """

    differ: list
    outside: int
    newer: int
    rows: int
    index_column: bool = False

    @property
    def same(self) -> bool:
        """Whether the table holds the record's rows: every period the same, and no row up to its last timestamp that the record did not have."""
        return not self.differ and not self.outside


class _Pieces:
    """Rows put by piece into scratch files, a batch at a time, then read back a piece at a time.

    What is put is written once a little of it has gathered
    (:attr:`HELD`), so that a table whose rows are in no order of date,
    each batch a few rows of every piece, is not written a few rows at a
    time. A piece's file is opened to be added to and closed again each
    time, so that no file is held open: a table of thirty years of months
    has more pieces than a process may have files open. Nothing here is
    polars': a batch is cut and written by Arrow alone, so that what is
    held while a table is split is the batch.

    Attributes:
        sizes: What each piece's rows count for, in bytes (:func:`row_bytes`).
        counts: How many rows each piece has.
        spans: The least and the greatest timestamp in each piece.
    """

    #: The most that waits in memory to be written, in bytes
    HELD = 16 * 1024 * 1024

    def __init__(self, folder: Path, schema):
        import pyarrow as pa

        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.schema = schema
        self.text = _text_columns(schema)
        self.numbers: dict = {}
        self.waiting: dict = {}
        self.held = 0
        self.sizes: dict = {}
        self.counts: dict = {}
        self.spans: dict = {}
        try:
            self.options = pa.ipc.IpcWriteOptions(compression="lz4")
        except Exception:  # noqa: BLE001 - a pyarrow built without it
            self.options = pa.ipc.IpcWriteOptions()

    def __contains__(self, key) -> bool:
        return key in self.sizes

    def keys(self) -> list:
        return sorted(self.sizes)

    def add(self, key, batch, size: int, span=None) -> None:
        """Put a batch's rows in a piece; *size* is what they count for, and *span* the least and greatest timestamp among them."""
        self.waiting.setdefault(key, []).append(batch)
        self.held += batch.nbytes
        self.sizes[key] = self.sizes.get(key, 0) + int(size)
        self.counts[key] = self.counts.get(key, 0) + batch.num_rows
        if span is not None:
            was = self.spans.get(key)
            self.spans[key] = span if was is None else (min(was[0], span[0]), max(was[1], span[1]))
        if self.held > self.HELD:
            self.flush()

    def flush(self) -> None:
        import pyarrow as pa

        for key, batches in self.waiting.items():
            table = pa.Table.from_batches(batches, schema=self.schema)
            # Each time a stream of its own, one after another in the piece's file
            with open(self.path(key), "ab") as sink:
                with pa.ipc.new_stream(sink, self.schema, options=self.options) as writer:
                    writer.write_table(table.combine_chunks() if len(batches) > 1 else table)
        self.waiting, self.held = {}, 0

    def close(self) -> None:
        self.flush()

    def path(self, key) -> Path:
        return self.folder / f"{self.numbers.setdefault(key, len(self.numbers))}.arrows"

    def batches(self, key) -> Iterator:
        """A piece's rows, as Arrow record batches, in the order they were written."""
        import pyarrow as pa

        path = self.path(key)
        size = os.path.getsize(path)
        with open(path, "rb") as source:
            while source.tell() < size:
                yield from pa.ipc.open_stream(source)

    def read(self, keys):
        """The rows of some pieces together, as a polars DataFrame."""
        import pyarrow as pa

        pl = _polars()
        held = pa.Table.from_batches([batch for key in keys for batch in self.batches(key)], schema=self.schema)
        frame = pl.from_arrow(held)
        return frame if isinstance(frame, pl.DataFrame) else frame.to_frame()

    def drop(self, key) -> None:
        """Let a piece's file go, once its rows have been put elsewhere."""
        with contextlib.suppress(OSError):
            os.remove(self.path(key))

    def remove(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)


#: How long a scratch folder nobody removed is left, in seconds: one of a
#: process that was killed, which removed nothing.
_STALE = 24 * 3600


def _scratch_folder() -> Path:
    """A scratch folder on a disk, removed by whoever asked for it: in ChartBook's cache where that can be written, else in the system's temporary folder; never in memory.

    One left behind there by a process that was killed is removed here,
    once it is a day old.
    """
    import time

    try:
        from chartbook.config import get_cache_path

        root = Path(get_cache_path()) / "rows"
        root.mkdir(parents=True, exist_ok=True)
        for left in root.glob("chartbook-rows-*"):
            with contextlib.suppress(OSError):
                if time.time() - left.stat().st_mtime > _STALE:
                    shutil.rmtree(left, ignore_errors=True)
        return Path(tempfile.mkdtemp(prefix="chartbook-rows-", dir=root))
    except Exception:  # noqa: BLE001 - no cache to write to: the system's temporary folder
        return Path(tempfile.mkdtemp(prefix="chartbook-rows-"))


def _put(pieces: _Pieces, batch, index, stamps, fine: bool) -> None:
    """Put a batch's rows in their pieces, by the number each row was given; one below -1 is left out."""
    import numpy as np
    import pyarrow as pa

    if not len(index):
        return
    sizes = row_bytes(batch, pieces.text)
    least, most = int(index.min()), int(index.max())
    if least == most:
        if least >= -1:
            span = _span(int(stamps.min()), int(stamps.max()), fine) if least >= 0 else None
            pieces.add(least, batch, int(sizes.sum()), span)
        return
    order = np.argsort(index, kind="stable")
    taken = batch.take(pa.array(order))
    index, stamps, sizes = index[order], stamps[order], sizes[order]
    numbers, starts = np.unique(index, return_index=True)
    ends = list(starts[1:]) + [len(index)]
    for number, start, end in zip(numbers.tolist(), starts.tolist(), ends):
        if number < -1:
            continue
        end = int(end)
        span = _span(int(stamps[start:end].min()), int(stamps[start:end].max()), fine) if number >= 0 else None
        pieces.add(number, taken.slice(start, end - start), int(sizes[start:end].sum()), span)


def _whole(table: Table, scratch: Path, most: int):
    """A table's rows held whole, as a polars DataFrame, and how many there are; None once they count for more than *most* bytes (:func:`row_bytes`)."""
    import pyarrow as pa

    pl = _polars()
    target = table.arrow_schema()
    text = _text_columns(target)
    batches, size, rows = [], 0, 0
    for batch in table.batches(scratch=scratch):
        size += int(row_bytes(batch, text).sum())
        rows += batch.num_rows
        if size > most:
            batches = None
        elif batches is not None:
            batches.append(batch)
    if batches is None:
        return None, rows
    frame = pl.from_arrow(pa.Table.from_batches(batches, schema=target))
    return (frame if isinstance(frame, pl.DataFrame) else frame.to_frame()), rows


def hash_rows(table: Table, date_col: Optional[str] = None) -> RowsRecord:
    """Hash a table's rows as a snapshot records them: by period, where it has a date column.

    **The periods** are whole calendar years. A year whose rows count for
    more than :data:`PERIOD_BYTES` is split into its months, and such a
    month into its days. What rows count for is counted from the rows
    alone (:func:`row_bytes`), so the same rows give the same periods,
    whatever file, order or types they came in. Decided by the maintainer
    on 2026-11-15: years and not months, since twelve times the lines buys
    nothing for most tables, and no setting for it.

    :param date_col: The column its entry declares as its dates, if it
        declares one and the table has it.
    :raises NotHashed: If the table has a column of a kind the form does
        not take, one day's rows or its rows with no date are too many to
        hold, or it has no date column and is too large to hold whole.
    """
    schema = table.schema()
    _taken(schema)  # said before anything is read
    if not _dated_by(schema, date_col):
        date_col = None
    scratch = _scratch_folder()
    try:
        with _lean():
            return _hash_rows(table, date_col, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _dated_by(schema, date_col: Optional[str]) -> bool:
    """Whether a table's rows are dated by a column: it has the column, and it holds dates, or text to read as dates."""
    pl = _polars()
    if date_col is None or date_col not in schema.names():
        return False
    kind = schema[date_col]
    return kind == pl.Date or isinstance(kind, pl.Datetime) or kind == pl.String


#: A table whose files are over this on disk has its rows put by month from
#: the first, and not by year: most of its years will be split, and are
#: then written once and not twice. What is hashed is the same either way.
_BY_MONTH_FROM = 1024 * 1024 * 1024


def _hash_rows(table: Table, date_col: Optional[str], scratch: Path) -> RowsRecord:
    import numpy as np

    if date_col is None:
        whole, count = _whole(table, scratch, MOST_BYTES)
        if whole is None:
            raise NotHashed(
                f"it has no date column, and its rows count for more than {MOST_BYTES // 2**20} MB (eight bytes a "
                f"column and the bytes of its text): a rows hash holds a table with no date column whole"
            )
        return RowsRecord({ALL: hash_frame(whole)}, None, count)
    by_month = table.on_disk() > _BY_MONTH_FROM
    pieces = _Pieces(scratch / "pieces", table.arrow_schema())
    count = 0
    for batch in table.batches(scratch=scratch):
        micro, left, empty = _stamps(batch.column(date_col))
        months = _months(np.floor_divide(micro, _DAY), empty)
        index = months if by_month else months - months % 12
        _put(pieces, batch, np.where(empty, -1, index), _ordered(micro, left), left is not None)
        count += batch.num_rows
    pieces.close()
    years: dict = {}
    for key in pieces.keys():
        if key >= 0:
            years.setdefault(key // 12, []).append(key)
    rows: dict = {}
    as_of = None
    for year in sorted(years):
        for (first, last), hashed in _of_a_year(pieces, years[year], by_month, date_col, scratch):
            rows[f"{stamp_text(*first)}/{stamp_text(*last)}"] = hashed
            as_of = stamp_text(*last)
    if -1 in pieces:
        if pieces.sizes[-1] > MOST_BYTES:
            raise NotHashed(
                f"its rows with no date, {pieces.counts[-1]:,} of them, count for {pieces.sizes[-1] / 2**20:,.0f} MB "
                f"(eight bytes a column and the bytes of its text), and a rows hash holds at most "
                f"{MOST_BYTES // 2**20} MB of them at a time"
            )
        rows[NO_DATE] = hash_frame(pieces.read([-1]), date_col)
    return RowsRecord(rows, as_of, count, date_col)


def _of_a_year(pieces: _Pieces, keys: list, by_month: bool, date_col: str, scratch: Path) -> Iterator:
    """The periods of one year's rows, each with its span and its hash, in order: the year whole where it is within the size, else its months, and the days of a month that is not."""
    if sum(pieces.sizes[key] for key in keys) <= PERIOD_BYTES:
        first = min(pieces.spans[key][0] for key in keys)
        last = max(pieces.spans[key][1] for key in keys)
        yield (first, last), hash_frame(pieces.read(keys), date_col)
        return
    months = pieces if by_month else _split(pieces, keys[0], "month", date_col, scratch)
    try:
        for month in keys if by_month else months.keys():
            if months.sizes[month] <= PERIOD_BYTES:
                yield months.spans[month], hash_frame(months.read([month]), date_col)
                continue
            days = _split(months, month, "day", date_col, scratch)
            try:
                for day in days.keys():
                    if days.sizes[day] > MOST_BYTES:
                        raise _a_day_too_large(days.spans[day][0], days.counts[day], days.sizes[day])
                    yield days.spans[day], hash_frame(days.read([day]), date_col)
            finally:
                days.remove()
    finally:
        if months is not pieces:
            months.remove()


def _split(pieces: _Pieces, key, by: str, date_col: str, scratch: Path) -> _Pieces:
    """A piece's rows put again by month, or by day, a batch at a time; the piece itself is let go."""
    import numpy as np

    parts = _Pieces(Path(tempfile.mkdtemp(prefix=f"{by}s-", dir=scratch)), pieces.schema)
    first = pieces.spans[key][0][0] // _DAY  # days counted from the piece's first: none below zero
    for batch in pieces.batches(key):
        micro, left, _ = _stamps(batch.column(date_col))
        days = np.floor_divide(micro, _DAY)
        _put(parts, batch, days - first if by == "day" else _months(days), _ordered(micro, left), left is not None)
    parts.close()
    pieces.drop(key)
    return parts


def periods_of(rows: dict) -> list:
    """The periods a record of rows names, each as its key, its first and its last timestamp (microseconds and nanoseconds left over), in order.

    :raises ValueError: If a key is not a period a record writes.
    """
    found = []
    for key in rows:
        if key in (NO_DATE, ALL):
            continue
        first, _, last = key.partition("/")
        found.append((key, stamp_of(first), stamp_of(last)))
    return sorted(found, key=lambda period: period[1])


def hash_in(table: Table, date_col: Optional[str], rows: dict, as_of: Optional[str], known=()) -> Compared:
    """Hash a table's rows in the periods a record names, and say where they are not the record's.

    The table's rows after *as_of*, the record's last timestamp, are left
    out and counted: a table that has gained rows since still holds the
    record's. A row up to *as_of* that falls in no period of the record is
    one the record did not have. A record with no dated row has no last
    timestamp, and every dated row of the table is then after it.

    :param rows: The record's hashes, by period (:attr:`RowsRecord.rows`).
    :param as_of: Its last timestamp, as text; None if it has none.
    :param known: The periods already known to hold the record's rows, as
        the record writes them: their rows are passed over, not hashed.
    :raises NotHashed: If the table's rows cannot be hashed.
    :raises ValueError: If the record names a period that is none.
    """
    _taken(table.schema())
    periods = periods_of(rows)
    scratch = _scratch_folder()
    try:
        with _lean():
            return _hash_in(table, date_col, rows, as_of, periods, scratch, set(known))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _hash_in(
    table: Table, date_col: Optional[str], rows: dict, as_of: Optional[str], periods: list, scratch: Path, known: set
) -> Compared:
    import numpy as np

    pl = _polars()
    schema = table.schema()
    index_column = INDEX_COLUMN in schema.names()
    if ALL in rows or not _dated_by(schema, date_col):
        # No date column, here or in the record: all the rows, or nothing to compare by. More
        # than a record's one piece ever counts for cannot be its rows
        whole, total = _whole(table, scratch, MOST_BYTES)
        same = whole is not None and set(rows) == {ALL} and hash_frame(whole) == rows[ALL]
        return Compared([] if same else sorted(rows), 0, 0, total, index_column)
    fine = isinstance(schema[date_col], pl.Datetime) and schema[date_col].time_unit == "ns"
    firsts = np.array([_bound(first, fine, first=True) for _, first, _ in periods], dtype="int64")
    lasts = np.array([_bound(last, fine) for _, _, last in periods], dtype="int64")
    cap = _bound(stamp_of(as_of), fine) if as_of is not None else None
    pieces = _Pieces(scratch / "pieces", table.arrow_schema())
    outside = newer = total = 0
    too_many: set = set()
    passed_over = [number for number, (key, _, _) in enumerate(periods) if key in known]
    for batch in table.batches(scratch=scratch):
        micro, left, empty = _stamps(batch.column(date_col))
        stamps = _ordered(micro, left)
        # With no last timestamp, the record has no dated row: every dated row is newer
        after = ~empty & ((stamps > cap) if cap is not None else True)
        index = np.searchsorted(firsts, stamps, side="right") - 1
        inside = ~empty & ~after & (index >= 0)
        if len(periods):
            inside &= stamps <= lasts[np.clip(index, 0, None)]
        index = np.where(inside, index, -2)
        if NO_DATE in rows:
            index = np.where(empty, -1 if NO_DATE not in known else -3, index)
        total += batch.num_rows
        newer += int(after.sum())
        outside += int((index == -2).sum()) - int(after.sum())
        if passed_over:
            index = np.where(np.isin(index, passed_over), -3, index)  # known to be the same: not read again
        # No period of a record counts for more than the most one piece may: rows that
        # do are not its rows, and are not held to be hashed
        too_many |= {number for number, size in pieces.sizes.items() if size > MOST_BYTES}
        if too_many:
            index = np.where(np.isin(index, list(too_many)), -3, index)
        _put(pieces, batch, index, stamps, fine)
    pieces.close()
    too_many |= {number for number, size in pieces.sizes.items() if size > MOST_BYTES}
    differ = []
    for number, (key, _, _) in enumerate(periods):
        if key in known:
            continue
        if number in too_many or number not in pieces:
            differ.append(key)
        elif hash_frame(pieces.read([number]), date_col) != rows[key]:
            differ.append(key)
    if NO_DATE in rows and NO_DATE not in known:
        if -1 in too_many or -1 not in pieces or hash_frame(pieces.read([-1]), date_col) != rows[NO_DATE]:
            differ.append(NO_DATE)
    return Compared(differ, outside, newer, total, index_column)


# --- The rows a pin holds, of a table that has gained rows since -----------------


def _text_dates(column):
    """A text column's dates as a polars expression, in microseconds and UTC: what :func:`_dates_in_text` reads of a column, for a frame that is not read yet."""
    pl = _polars()
    written = pl.when(column.str.contains(_ISO_DATE)).then(column)
    return pl.coalesce(
        [
            written.str.to_datetime(form, strict=False, time_unit="us", time_zone="UTC").dt.replace_time_zone(None)
            if zoned else written.str.to_datetime(form, strict=False, time_unit="us", exact=True)
            for form, zoned in _TEXT_DATES
        ]
    )


def up_to(schema, date_col: str, as_of: Optional[str]):
    """A polars expression for the rows of a table up to a record's last timestamp, and its rows with no date: the rows the record is of, in a table that has gained rows since.

    A row is dated as a rows hash dates it (:func:`_stamps`), so this
    keeps exactly the rows :func:`hash_in` compares and leaves out the
    ones it counts as newer.

    :param schema: The table's polars schema.
    :param date_col: The column the record's rows are dated by.
    :param as_of: The record's last timestamp, as it writes it; None for a
        record with no dated row, which keeps the rows with no date alone.
    :raises NotHashed: If the column holds no dates.
    """
    pl = _polars()
    kind = schema[date_col]
    column = pl.nth(schema.names().index(date_col))  # by its place: a name is a pattern to polars when it begins ^ and ends $
    if kind == pl.String:
        column, kind = _text_dates(column), pl.Datetime("us")
    if kind != pl.Date and not isinstance(kind, pl.Datetime):
        raise NotHashed(f"its date column {date_col!r} is {_type_said(kind)}, which is no date")
    if as_of is None:
        return column.is_null()
    micro, left = stamp_of(as_of)
    # On the scale the column is held in: days, or a count of its unit from 1970, the instant for one with a zone
    if kind == pl.Date:
        last = micro // _DAY
    elif kind.time_unit == "ms":
        last = micro // 1000
    elif kind.time_unit == "ns":
        last = max(-(2**63), min(2**63 - 1, micro * 1000 + left))
    else:
        last = micro
    return column.is_null() | (column.to_physical().cast(pl.Int64) <= last)


def pinned_rows(frame, date_col: Optional[str], as_of: Optional[str]):
    """A frame without the rows after a record's last timestamp: a polars LazyFrame or DataFrame of a table that stands in for a pin, as the pin holds it.

    With no *date_col*, the record is of all the rows, and the frame is
    given back as it is.
    """
    pl = _polars()
    if date_col is None:
        return frame
    schema = frame.collect_schema() if isinstance(frame, pl.LazyFrame) else frame.schema
    return frame.filter(up_to(schema, date_col, as_of))
