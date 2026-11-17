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
to hold (:func:`choose`). Each period is written by the first and the
last timestamp seen in it, both included, so the record holds no date that
has not happened. Whoever pins chooses the periods; whoever checks reads
them from the record and hashes their own rows in those same periods,
leaving out the rows after the record's last timestamp (:func:`hash_in`).

**Memory.** A period's rows are what is held at once, never the table: the
files are read a few thousand rows at a time, each row is put in a scratch
file for its period, and each period is then sorted and hashed alone. The
size of a period is fixed here (:data:`PERIOD_BYTES`), for a machine with
8 GB, and is not taken from the machine that pins: the author may pin on
64 GB, and a student then hashes those same periods on 8.
"""

from __future__ import annotations

import contextlib
import hashlib
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

#: The most a period's rows take in memory, in bytes, as Arrow holds them:
#: a year over this is split into months, and a month over it into days.
#: Sorting and feeding a period takes a few times its size, so this is what
#: sets the peak. It is fixed, and no setting: the machine that checks a
#: pin has to hold the periods the machine that pinned chose.
PERIOD_BYTES = 128 * 1024 * 1024

#: The most rows hashed as one piece that cannot be split: one day of a
#: dated table, or the whole of a table with no date column. A table with
#: more than this in one piece has no rows hash, and is pinned by its bytes
#: alone.
MOST_BYTES = 2 * PERIOD_BYTES

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
    raise NotHashed(f"column {name!r} is {kind}, and a rows hash takes no such column yet")


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

    def arrow_schema(self, columns: Optional[list] = None):
        """Its columns as Arrow holds them here: the reader's types, a category as its text."""
        import pyarrow as pa

        pl = _polars()
        schema = self.schema()
        plain = {
            name: pl.String if _kind_of(name, kind) == "text" else kind
            for name, kind in schema.items() if columns is None or name in columns
        }
        empty = pl.DataFrame(schema=plain).to_arrow(compat_level=pl.CompatLevel.oldest())
        return pa.schema(list(empty.schema))

    def batches(self, columns: Optional[list] = None, scratch: Optional[Path] = None, sample: bool = False) -> Iterator:
        """Its rows as Arrow record batches of a few thousand rows each, in no promised order, with the reader's columns.

        A parquet file is read by pyarrow a batch at a time, which holds
        one batch and not a row group. What the reader adds to a file's own
        columns, the ``key=value`` folders of its path, is asked of the
        reader for each file and put on its batches. Any other format is
        written out as parquet once, into *scratch*, by polars' streaming
        engine, and read from there.

        :param columns: The columns wanted; all of them by default.
        :param scratch: A folder for the copy a format other than parquet
            is read through.
        :param sample: Whether to give only a few batches, from places
            spread through the files: enough to say what a row takes.
        """
        from chartbook import formats

        pl = _polars()
        read = formats.reading(self.path, self.format, self.read_options)
        target = self.arrow_schema(columns)
        if read.format != "parquet":
            if scratch is None:
                raise ValueError("a format other than parquet is read through a scratch folder")
            copy = Path(scratch) / "table.parquet"
            if not copy.exists():
                try:
                    self.scan().sink_parquet(copy, row_group_size=50_000)
                except Exception as error:  # noqa: BLE001 - whatever polars raises for a file it cannot read through
                    raise NotRead(f"it could not be read ({_first_line(error)})") from None
            yield from _parquet_batches(copy, target, None, sample)
            return
        sources, folder = formats._sources(Path(self.path), read, self.files, self.listed, self.inside)
        found = formats.files_of(self.path, read, self.files, self.listed, self.inside)
        by_file = formats._by_location(self.inside)
        alone = len(found) == 1 and folder is None
        if sample and len(found) > 4:
            found = [found[i * (len(found) - 1) // 3] for i in range(4)]
        for file in found:
            added = None
            if not alone:
                # Asked once for each file, of all its columns: a table is read more than once
                if str(file) not in self._added:
                    self._added[str(file)] = _added_by_the_reader(
                        formats._scan(read, [str(file)], folder, by_file), file, self.schema().names()
                    )
                added = self._added[str(file)]
                if added is not None:
                    # By their place: a name is a pattern to polars when it begins ^ and ends $
                    added = added.select([pl.nth(i) for i, name in enumerate(added.columns) if name in target.names])
            yield from _parquet_batches(file, target, added if added is None or added.width else None, sample)


def _first_line(error: BaseException) -> str:
    said = str(error).strip()
    return said.splitlines()[0] if said else type(error).__name__


def _added_by_the_reader(one, file, wanted: list):
    """What the reader puts on one file's rows beside the file's own columns: a polars frame of one row, or None.

    Asked of the reader, for this file among its fellows (*one* is its
    read of the file): the columns the file does not have, which are the
    ``key=value`` folders of its path; and a column the file has that the
    reader gives another first value of, a key put in its place.
    """
    import pyarrow.parquet as pq

    pl = _polars()
    names = one.collect_schema().names()
    opened = pq.ParquetFile(str(file))
    own = set(opened.schema_arrow.names)
    extra = [name for name in names if name in wanted and name not in own]
    from chartbook import formats

    doubtful = [name for name in names if name in wanted and name in own and name in {key for key, _ in formats._keys_of(Path(str(file)).parent)}]
    if doubtful and opened.metadata.num_rows:
        first = one.select([pl.nth(names.index(name)) for name in doubtful]).head(1).collect()
        theirs = pl.from_arrow(next(opened.iter_batches(batch_size=1, columns=doubtful)))
        for name in doubtful:
            try:
                same = first[name].cast(pl.String)[0] == theirs[name].cast(pl.String)[0]
            except Exception:  # noqa: BLE001 - two types with no text to compare: the file's own column stands
                same = True
            if not same:
                extra.append(name)
    if not extra:
        return None
    return one.select([pl.nth(names.index(name)) for name in extra]).head(1).collect()


def _parquet_batches(file, target, added, sample: bool = False) -> Iterator:
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
        groups = list(range(metadata.num_row_groups))
        if sample:
            groups = sorted({groups[i * (len(groups) - 1) // 3] for i in range(4)}) if len(groups) > 4 else groups
            for group in groups:
                for batch in opened.iter_batches(batch_size=at_a_time, columns=own, row_groups=[group], use_threads=True):
                    if batch.num_rows:
                        yield finished(batch)
                    break
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
    it is not.

    :param column: The column, as an Arrow array or a polars Series.
    """
    import numpy as np

    pl = _polars()
    series = column if isinstance(column, pl.Series) else pl.from_arrow(column)
    name = series.name
    kind = series.dtype
    if kind == pl.String:
        series = _dates_in_text(series)
        kind = series.dtype
    if kind == pl.Date:
        series = series.cast(pl.Datetime("us"))
        kind = series.dtype
    if not isinstance(kind, pl.Datetime):
        raise NotHashed(f"its date column{f' {name!r}' if name else ''} is {kind}, which is no date")
    if kind.time_zone:
        series = series.dt.convert_time_zone("UTC").dt.replace_time_zone(None)
    unit = kind.time_unit
    if unit == "ms":
        series, unit = series.cast(pl.Datetime("us")), "us"
    empty = series.is_null().to_numpy()
    whole = series.cast(pl.Int64).fill_null(0).to_numpy().astype("int64", copy=False)
    if unit == "ns":
        micro = np.floor_divide(whole, 1000)
        return micro, whole - micro * 1000, empty
    return whole, None, empty


#: How a date is written in text, each tried in turn: ISO 8601, with a time
#: or none, with an offset or none. Fixed, and not guessed from a column's
#: first values, so that a value is read the same in every batch and on
#: every machine.
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
    """A text column's dates, in microseconds and UTC: each value as the first of :data:`_TEXT_DATES` it is written in, and no date for one written in none."""
    pl = _polars()
    tried = []
    for form, zoned in _TEXT_DATES:
        try:
            if zoned:
                read = series.str.to_datetime(form, strict=False, time_unit="us", time_zone="UTC").dt.replace_time_zone(None)
            else:
                read = series.str.to_datetime(form, strict=False, time_unit="us", exact=True)
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
    """A record's timestamp on the scale :func:`_ordered` gives a column: in microseconds, a first timestamp with nanoseconds left over is the next microsecond."""
    micro, left = stamp
    if fine:
        return micro * 1000 + left
    return micro + (1 if first and left else 0)


def _span(low: int, high: int, fine: bool) -> tuple:
    """A least and a greatest timestamp on the scale of :func:`_ordered`, each as microseconds and nanoseconds left over."""
    if fine:
        return (divmod(low, 1000), divmod(high, 1000))
    return ((low, 0), (high, 0))


def choose(days: dict, a_row: float, period_bytes: int = None, most_bytes: int = None) -> list:
    """The periods a table is hashed in, from how many rows each of its days has.

    Whole calendar years. A year whose rows take more than
    :data:`PERIOD_BYTES` in memory is split into its months, and such a
    month into its days. Decided by the maintainer on 2026-11-15: years and
    not months, since twelve times the lines buys nothing for most tables,
    and no setting for it.

    :param days: How many rows each day has, by the day's number from 1970.
    :param a_row: About how many bytes a row takes in memory.
    :returns: Each period as the first and the last day in it that has
        rows, both included, in order.
    :raises NotHashed: If one day's rows take more than :data:`MOST_BYTES`.
    """
    period_bytes = PERIOD_BYTES if period_bytes is None else period_bytes
    most_bytes = MOST_BYTES if most_bytes is None else most_bytes
    by_year: dict = {}
    for day in sorted(days):
        when = _EPOCH.date() + timedelta(days=int(day))
        by_year.setdefault(when.year, {}).setdefault(when.month, []).append(int(day))
    periods = []
    for year in sorted(by_year):
        months = by_year[year]
        every = [day for month in sorted(months) for day in months[month]]
        if sum(days[day] for day in every) * a_row <= period_bytes:
            periods.append((every[0], every[-1]))
            continue
        for month in sorted(months):
            within = months[month]
            if sum(days[day] for day in within) * a_row <= period_bytes:
                periods.append((within[0], within[-1]))
                continue
            for day in within:
                if days[day] * a_row > most_bytes:
                    raise _a_day_too_large(day, days[day], days[day] * a_row)
                periods.append((day, day))
    return periods


def _a_day_too_large(day: int, rows: Optional[int], size: float) -> NotHashed:
    when = _EPOCH.date() + timedelta(days=int(day))
    count = f", {rows:,} of them," if rows is not None else ""
    return NotHashed(
        f"its rows of {when.isoformat()} alone{count} take about {size / 1e6:,.0f} MB in memory, and a rows "
        f"hash holds a day at a time"
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
#: :meth:`RowsRecord.fields`, or ``not_hashed`` alone, why its rows have no
#: hash (:class:`NotHashed`).
FIELDS = ("date_col", "as_of", "rows", "row_count", "not_hashed")


def fields_of(table: "Table", date_col: Optional[str] = None) -> dict:
    """What a record says of a dataframe's rows (:data:`FIELDS`), hashing them now.

    :returns: Its rows by period; or ``{"not_hashed": why}`` for a table
        whose rows have no hash; or nothing at all for files that cannot be
        read as a table, of which there is nothing to say.
    """
    try:
        return hash_rows(table, date_col).fields()
    except NotRead:
        return {}
    except NotHashed as error:
        return {"not_hashed": str(error)}


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
    """Rows put by period into scratch files, a batch at a time, then read back a period at a time.

    What is put is written once a little of it has gathered
    (:attr:`HELD`), so that a table whose rows are in no order of date,
    each batch a few rows of every period, is not written a few rows at a
    time. Nothing here is polars': a batch is cut and written by Arrow
    alone, so that what is held while a table is split is the batch.
    """

    #: The most that waits in memory to be written, in bytes
    HELD = 16 * 1024 * 1024

    def __init__(self, folder: Path, schema):
        import pyarrow as pa

        self.folder = folder
        self.schema = schema
        self.writers: dict = {}
        self.waiting: dict = {}
        self.held = 0
        self.sizes: dict = {}
        self.spans: dict = {}
        try:
            self.options = pa.ipc.IpcWriteOptions(compression="lz4")
        except Exception:  # noqa: BLE001 - a pyarrow built without it
            self.options = pa.ipc.IpcWriteOptions()

    def add(self, key, batch, span=None) -> None:
        """Put a batch's rows in a piece; *span* is the least and greatest timestamp among them."""
        self.waiting.setdefault(key, []).append(batch)
        self.held += batch.nbytes
        self.sizes[key] = self.sizes.get(key, 0) + batch.nbytes
        if span is not None:
            was = self.spans.get(key)
            self.spans[key] = span if was is None else (min(was[0], span[0]), max(was[1], span[1]))
        if self.held > self.HELD:
            self.flush()

    def flush(self) -> None:
        import pyarrow as pa

        for key, batches in self.waiting.items():
            if key not in self.writers:
                number = len(self.writers)
                sink = pa.OSFile(str(self.folder / f"{number}.arrows"), "wb")
                self.writers[key] = (sink, pa.ipc.new_stream(sink, self.schema, options=self.options), number)
            table = pa.Table.from_batches(batches, schema=self.schema)
            self.writers[key][1].write_table(table.combine_chunks() if len(batches) > 1 else table)
        self.waiting, self.held = {}, 0

    def close(self) -> None:
        try:
            self.flush()
        finally:
            for sink, writer, _ in self.writers.values():
                writer.close()
                sink.close()

    def path(self, key) -> Path:
        return self.folder / f"{self.writers[key][2]}.arrows"

    def read(self, key):
        """A piece's rows, as a polars DataFrame."""
        return _polars().read_ipc_stream(self.path(key))


def _scratch_folder() -> Path:
    """A scratch folder on a disk, removed by whoever asked for it: in ChartBook's cache, and never in memory."""
    try:
        from chartbook.config import get_cache_path

        root = Path(get_cache_path()) / "rows"
        root.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - no cache to write to: the system's temporary folder
        root = None
    return Path(tempfile.mkdtemp(prefix="chartbook-rows-", dir=root))


def _put(pieces: _Pieces, batch, index, stamps, fine: bool) -> None:
    """Put a batch's rows in their pieces, by the number each row was given; one below -1 is left out."""
    import numpy as np
    import pyarrow as pa

    if not len(index):
        return
    least, most = int(index.min()), int(index.max())
    if least == most:
        if least >= -1:
            pieces.add(least, batch, _span(int(stamps.min()), int(stamps.max()), fine) if least >= 0 else None)
        return
    order = np.argsort(index, kind="stable")
    taken = batch.take(pa.array(order))
    index, stamps = index[order], stamps[order]
    numbers, starts = np.unique(index, return_index=True)
    ends = list(starts[1:]) + [len(index)]
    for number, start, end in zip(numbers.tolist(), starts.tolist(), ends):
        if number < -1:
            continue
        end = int(end)
        span = _span(int(stamps[start:end].min()), int(stamps[start:end].max()), fine) if number >= 0 else None
        pieces.add(number, taken.slice(start, end - start), span)


def _days_and_a_row(table: Table, date_col: str, scratch: Path) -> tuple[dict, float, int]:
    """How many rows each day has, about how many bytes a row takes in memory, and how many rows there are."""
    import numpy as np

    days: dict = {}
    rows = 0
    for batch in table.batches(columns=[date_col], scratch=scratch):
        micro, _, empty = _stamps(batch.column(date_col))
        rows += batch.num_rows
        found, counts = np.unique(np.floor_divide(micro[~empty], _DAY), return_counts=True)
        for day, count in zip(found.tolist(), counts.tolist()):
            days[day] = days.get(day, 0) + count
    sampled_bytes = sampled_rows = 0
    for batch in table.batches(scratch=scratch, sample=True):
        sampled_bytes += batch.nbytes
        sampled_rows += batch.num_rows
    return days, sampled_bytes / max(1, sampled_rows), rows


def _whole(table: Table, scratch: Path, most: int):
    """A table's rows held whole, as a polars DataFrame, and how many there are; None once they pass *most* bytes."""
    import pyarrow as pa

    pl = _polars()
    target = table.arrow_schema()
    batches, size, rows = [], 0, 0
    for batch in table.batches(scratch=scratch):
        size += batch.nbytes
        rows += batch.num_rows
        if size > most:
            return None, rows
        batches.append(batch)
    frame = pl.from_arrow(pa.Table.from_batches(batches, schema=target))
    return (frame if isinstance(frame, pl.DataFrame) else frame.to_frame()), rows


def hash_rows(table: Table, date_col: Optional[str] = None) -> RowsRecord:
    """Hash a table's rows as a snapshot records them: by period, where it has a date column.

    :param date_col: The column its entry declares as its dates, if it
        declares one and the table has it.
    :raises NotHashed: If the table has a column of a kind the form does
        not take, one day's rows are too many to hold, or it has no date
        column and is too large to hold whole.
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


def _hash_rows(table: Table, date_col: Optional[str], scratch: Path) -> RowsRecord:
    import numpy as np

    if date_col is None:
        whole, count = _whole(table, scratch, MOST_BYTES)
        if whole is None:
            raise NotHashed(
                f"it has no date column, and its rows take more than {MOST_BYTES // 2**20} MB in "
                f"memory: a rows hash holds a table with no date column whole"
            )
        return RowsRecord({ALL: hash_frame(whole)}, None, count)
    days, a_row, count = _days_and_a_row(table, date_col, scratch)
    periods = choose(days, a_row)
    firsts = np.array([first for first, _ in periods], dtype="int64")
    pieces = _Pieces(scratch, table.arrow_schema())
    try:
        for batch in table.batches(scratch=scratch):
            micro, left, empty = _stamps(batch.column(date_col))
            index = np.searchsorted(firsts, np.floor_divide(micro, _DAY), side="right") - 1
            _put(pieces, batch, np.where(empty, -1, index), _ordered(micro, left), left is not None)
    finally:
        pieces.close()
    rows: dict = {}
    as_of = None
    for number in sorted(key for key in pieces.writers if key >= 0):
        if pieces.sizes[number] > MOST_BYTES:
            # More than was reckoned from a few of its rows: a day at a time, then
            for (first, last), hashed in _by_day(pieces, number, date_col, scratch):
                rows[f"{stamp_text(*first)}/{stamp_text(*last)}"] = hashed
                as_of = stamp_text(*last)
            continue
        first, last = pieces.spans[number]
        rows[f"{stamp_text(*first)}/{stamp_text(*last)}"] = hash_frame(pieces.read(number), date_col)
        as_of = stamp_text(*last)
    if -1 in pieces.writers:
        rows[NO_DATE] = hash_frame(pieces.read(-1), date_col)
    return RowsRecord(rows, as_of, count, date_col)


def _by_day(pieces: _Pieces, number, date_col: str, scratch: Path) -> Iterator:
    """A piece that turned out too large to hold, hashed a day at a time: each day's span and hash, in order."""
    import numpy as np
    import pyarrow as pa

    folder = Path(tempfile.mkdtemp(prefix="days-", dir=scratch))
    days = _Pieces(folder, pieces.schema)
    first = pieces.spans[number][0][0] // _DAY  # its days counted from its first: none below zero
    try:
        with pa.OSFile(str(pieces.path(number)), "rb") as source:
            for batch in pa.ipc.open_stream(source):
                micro, left, _ = _stamps(batch.column(date_col))
                _put(days, batch, np.floor_divide(micro, _DAY) - first, _ordered(micro, left), left is not None)
    finally:
        days.close()
    for day in sorted(days.writers):
        if days.sizes[day] > MOST_BYTES:
            raise _a_day_too_large(first + day, None, days.sizes[day])
        yield days.spans[day], hash_frame(days.read(day), date_col)
    shutil.rmtree(folder, ignore_errors=True)


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
    one the record did not have.

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
        # No date column, here or in the record: all the rows, or nothing to compare by
        whole, total = _whole(table, scratch, 2 * MOST_BYTES)
        same = whole is not None and set(rows) == {ALL} and hash_frame(whole) == rows[ALL]
        return Compared([] if same else sorted(rows), 0, 0, total, index_column)
    fine = isinstance(schema[date_col], pl.Datetime) and schema[date_col].time_unit == "ns"
    firsts = np.array([_bound(first, fine, first=True) for _, first, _ in periods], dtype="int64")
    lasts = np.array([_bound(last, fine) for _, _, last in periods], dtype="int64")
    cap = _bound(stamp_of(as_of), fine) if as_of is not None else None
    pieces = _Pieces(scratch, table.arrow_schema())
    outside = newer = total = 0
    too_many: set = set()
    passed_over = [number for number, (key, _, _) in enumerate(periods) if key in known]
    try:
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
            # A period with far more rows than any that was pinned cannot be the pinned one
            too_many |= {number for number, size in pieces.sizes.items() if size > 2 * MOST_BYTES}
            if too_many:
                index = np.where(np.isin(index, list(too_many)), -3, index)
            _put(pieces, batch, index, stamps, fine)
    finally:
        pieces.close()
    differ = []
    for number, (key, _, _) in enumerate(periods):
        if key in known:
            continue
        if number in too_many or number not in pieces.writers:
            differ.append(key)
        elif hash_frame(pieces.read(number), date_col) != rows[key]:
            differ.append(key)
    if NO_DATE in rows and NO_DATE not in known:
        if -1 not in pieces.writers or hash_frame(pieces.read(-1), date_col) != rows[NO_DATE]:
            differ.append(NO_DATE)
    return Compared(differ, outside, newer, total, index_column)

