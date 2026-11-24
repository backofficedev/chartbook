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

#: What a value counts for in a row, in bytes, when a period is measured:
#: eight; and sixteen and its own bytes for a value of text or binary, and
#: sixteen for a decimal, which is what they take in the form they are
#: hashed in. An empty value counts for eight, whatever its column.
COLUMN_BYTES = 8

#: The most rows hashed as one piece that cannot be split: one day of a
#: dated table, its rows with no date, or the whole of a table with no date
#: column. The same as a period: a piece is sorted whole, whatever it is,
#: and 248 MB of short text in one piece took 2.0 GB when it was twice
#: this. A table with more than this in one piece has no rows hash, and is
#: pinned by its bytes alone.
MOST_BYTES = PERIOD_BYTES

#: The most text a CSV or JSON lines table may be, unzipped, to have a
#: rows hash. Only parquet is read a little at a time: these are read
#: whole, once, and a number that is two bytes of text is eight in memory,
#: so the text is held well under a period. An Arrow IPC file has none:
#: what it takes in memory cannot be told from its file (19 MB of one,
#: compressed, was 4.2 GB).
OTHER_BYTES = 32 * 1024 * 1024

#: The most columns a table is read with. A file is read a few thousand
#: rows at a time, and still a page or two of every column is held while it
#: is: about 2.7 MB a column was measured, which at 1000 columns is more
#: than a period. A wider table has no rows hash.
MOST_COLUMNS = 256

#: How much of a file is handed on at a time, in bytes as its rows take
#: once each value is written out, and the most rows.
BATCH_BYTES = 8 * 1024 * 1024
BATCH_ROWS = 16_384

#: What reading a parquet file a little at a time is held to, told from
#: the file's own page headers before a row of it is read
#: (:func:`_read_plan`). A reader holds a page of every column at
#: once, and its dictionary, whatever is asked of it; and a page holds
#: what its writer put in it, a megabyte by default and far more where
#: values are long. So a file is refused, unread, where a row group's
#: largest pages and dictionaries together are more than :data:`HELD_MOST`
#: (256 columns of a megabyte page and a megabyte dictionary are within
#: it); where one value of text may be more than :data:`ROW_MOST`, which
#: a page as large as that may hold; and where a value of one fixed
#: length is more than :data:`VALUE_MOST` (five of 125 MB took 2.4 GB).
#: A dictionary is held more than once while it is read, as its page and
#: as its values, and what it took is not all given back before the
#: periods are hashed: so it counts three times for text, eight for
#: anything else (184 MB of numbers added 0.33 GB to what hashing took,
#: and 448 MB took 2.1 GB), six for a category. That is counted for the
#: eight largest, which is as many as are read at one moment. These are
#: of the file as it is written, not of its rows: the same rows written
#: with fewer values a page have a rows hash.
HELD_MOST = 768 * 1024 * 1024
ROW_MOST = 128 * 1024 * 1024
VALUE_MOST = 1024 * 1024

#: The most a run of rows may take as it is read, at worst, before it is
#: handed on :data:`BATCH_BYTES` at a time. At worst: each row of text
#: held by a dictionary its longest value, and each page of other text
#: wholly inside the run. What is read is nearly always a small part of
#: this.
READ_MOST = 32 * 1024 * 1024

#: Columns of text are read apart, a few together, where the pages a run
#: of rows begins and ends in could add more than this to it: what any run
#: takes is known only in whole pages, and two megabyte pages of each of
#: 150 columns are 300 MB at worst and a few kilobytes as a rule. Read
#: apart, what each few columns took is seen before the next are read,
#: and a run that has taken more than :data:`READ_MOST` and this already
#: is not read further.
APART_MOST = 64 * 1024 * 1024

#: The most a page header is read to, and the most pages a column chunk
#: and a file are walked to. A header is a few dozen bytes, and as long as
#: the longest value of its page where it holds the page's least and
#: greatest; a chunk has a page to a megabyte. A file past these was
#: written to be so (seven million pages of one value each took 78 s and
#: 3 GB to walk), and has no rows hash.
HEADER_MOST = 16 * 1024 * 1024
PAGES_MOST = 200_000
FILE_PAGES_MOST = 5_000_000

#: The most a parquet file's footer may be, in bytes. The footer lists
#: every column of every row group, and is read whole before anything
#: else: 164 MB of one, of 6,000 row groups of 251 columns, took 1.8 GB.
FOOTER_MOST = 16 * 1024 * 1024

#: The most calendar years a table's dates may fall in. Each period is
#: put by in a file of its own while a table is read; ten thousand of them
#: are no time series, and took 3 GB of scratch and a quarter of an hour.
MOST_YEARS = 1024

#: The key of the period of the rows whose date is empty, and of the one
#: hash of a table with no date column.
NO_DATE = "none"
ALL = "all"

#: The column pandas writes a frame's index into when the index has no
#: name. Where it holds row positions left from an earlier step, they shift
#: when a pull has more rows, and no row is then the row it was.
INDEX_COLUMN = "__index_level_0__"

#: That column, and the one pandas makes of any level with no name of an
#: index of several (``__index_level_1__``, …).
_INDEX_LEVEL = re.compile(r"__index_level_\d+__", re.ASCII)


def index_column_said(columns: Iterable[str] = (INDEX_COLUMN,)) -> str:
    """What a dataframe's owner is told of a file that has such a column, naming the ones it has."""
    return (
        f"its file has the column pandas makes of an index with no name ({', '.join(columns) or INDEX_COLUMN}). "
        f"Where that holds row positions, they shift when a pull has more rows, and no rebuild then has the rows "
        f"a pin of it names. to_parquet(index=False) drops it; reset_index() keeps it as a column with a name"
    )


#: What a dataframe's owner is told of a file that has that column.
INDEX_COLUMN_SAID = index_column_said()

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
    raise NotHashed(f"column {_name_said(name)} is {_type_said(kind)}, and a rows hash takes no such column yet")


def _name_said(name) -> str:
    """A column's name as a message writes it: quoted, and its beginning where it goes on."""
    said = repr(name)
    return said if len(said) <= 80 else f"{said[:60]}…' ({len(said):,} characters)"


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
                most = frame.to_series(place).alias("held").max()
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
    held = frame.to_series(place).alias("held").to_physical()  # a name is a pattern to polars when it begins ^ and ends $
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
            self._footers_within()
            try:
                self._schema = self.scan().collect_schema()
            except FileNotFoundError as error:
                raise NotRead(_first_line(error)) from None  # nothing there: no table, and nothing to say of one
            except MemoryError:
                raise
            except Exception as error:  # noqa: BLE001 - whatever the reader raises for what is no table
                # A file that may not be opened now is this machine's, not the table's
                trouble = _this_machines(error)
                if trouble is not None:
                    raise trouble from None
                raise NotRead(_first_line(error)) from None
            except BaseException as error:  # polars panics are not Exceptions
                if type(error).__name__ != "PanicException":
                    raise
                raise NotRead(_first_line(error)) from None
        return self._schema

    def _footers_within(self) -> None:
        """Refuse a parquet table one of whose files has a footer too large to read (:data:`FOOTER_MOST`), before any of it is read.

        :raises NotHashed: Naming the file and its footer's size.
        """
        from chartbook import formats

        try:
            read = formats.reading(self.path, self.format, self.read_options)
            if read.format != "parquet":
                return
            files = formats.files_of(self.path, read, self.files, self.listed, self.inside)
        except Exception:  # noqa: BLE001 - nothing there, or a format ChartBook does not read: said where it is read
            return
        for file in files:
            _footer_within(file)

    def arrow_schema(self):
        """Its columns as Arrow holds them here: the reader's types, a category as its text."""
        import pyarrow as pa

        pl = _polars()
        plain = {name: pl.String if _kind_of(name, kind) == "text" else kind for name, kind in self.schema().items()}
        try:
            empty = pl.DataFrame(schema=plain).to_arrow(compat_level=pl.CompatLevel.oldest())
        except Exception as error:  # noqa: BLE001 - a type Arrow has no batch of: a 128-bit whole number, say
            raise NotHashed(f"its columns cannot be read a batch at a time ({_first_line(error)})") from None
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
        """Its rows as Arrow record batches of a few megabytes each, in no promised order, with the reader's columns.

        A parquet file is read by pyarrow a batch at a time, which holds
        one batch and not a row group; how many rows a batch has is set by
        what the rows take as they are read (:func:`_parquet_batches`).
        What the reader adds to a file's own columns, the ``key=value``
        folders of its path, is asked of the reader for the table as a
        whole and put on each file's batches; a file the store keeps once
        for two partitions is read once for each, with each one's keys.

        A CSV or JSON lines table is read whole by polars and written out
        as parquet once, into *scratch*, and read from there: so one over
        :data:`OTHER_BYTES` of text is refused, and an Arrow IPC file,
        whose size in memory its file does not say, always.

        :param scratch: A folder for the copy a format other than parquet
            is read through.
        :raises NotHashed: For a table in another format than parquet that
            cannot be read whole within what is held.
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
                except (OSError, MemoryError):
                    raise  # the scratch folder, or this machine: no fault of the table's
                except Exception as error:  # noqa: BLE001 - whatever polars raises for a file it cannot read through
                    trouble = _this_machines(error)
                    if trouble is not None:
                        raise trouble from None
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
            except (OSError, MemoryError):
                raise
            except Exception as error:  # noqa: BLE001 - whatever the reader raises for files it cannot read
                trouble = _this_machines(error)
                if trouble is not None:
                    raise trouble from None
                raise NotRead(f"its files could not be read ({_first_line(error)})") from None
            for place, (location, _) in enumerate(apart):
                put = {key: pl.Series(key, [values[place]], dtype=kind) for key, (kind, values) in keys.items() if key in target.names}
                yield from _parquet_batches(location, target, pl.DataFrame(list(put.values())) if put else None)
            return
        found = formats.files_of(self.path, read, self.files, self.listed, self.inside)
        if not self._added:
            try:
                self._added.update(self._keys(read, sources, folder, found))
            except (OSError, MemoryError, NotHashed):
                raise
            except Exception as error:  # noqa: BLE001 - whatever the reader raises for files it cannot read
                trouble = _this_machines(error)
                if trouble is not None:
                    raise trouble from None
                raise NotRead(f"its files could not be read ({_first_line(error)})") from None
        for file in found:
            added = self._added.get(str(file))
            if added is not None:
                # By their place: a name is a pattern to polars when it begins ^ and ends $
                added = added.select([pl.nth(i) for i, name in enumerate(added.columns) if name in target.names])
            yield from _parquet_batches(file, target, added if added is None or added.width else None)

    def _keys(self, read, sources, folder, found: list) -> dict:
        """What the reader puts on each file's rows beside the file's own columns, by the file: a polars frame of one row, or None.

        The ``key=value`` folders of a file's path, as the reader makes
        columns of them **for the table as a whole**: a key's type is told
        from all its values, so ``code=007`` beside ``code=abc`` is the
        text ``007``, and folders that name different keys make none. For
        a folder that is asked of the reader's own rule
        (:func:`chartbook.formats._partitions`). For one file, or a glob,
        it is asked of the reader for each file, and what it says is held
        to the type the table's schema gives the column.
        """
        from chartbook import formats

        pl = _polars()
        by_file = formats._by_location(self.inside)
        wanted = self.schema()
        if folder is None and isinstance(sources, str) and formats.is_glob_pattern(sources) and not os.path.exists(sources):
            from chartbook import hashing

            folder = hashing.split_glob(sources)[0]
        if folder is not None:
            keys = formats._partitions([str(file) for file in found], Path(folder), by_file, own=wanted) if found else {}
            return {
                str(file): (
                    pl.DataFrame([pl.Series(key, [values[str(file)]], dtype=kind) for key, (kind, values) in keys.items() if key in wanted])
                    if any(key in wanted for key in keys) else None
                )
                for file in found
            }
        alone = len(found) == 1
        added = {}
        for file in found:
            one = formats._scan(read, sources if alone else [str(file)], None, by_file)
            said = _added_by_the_reader(one, file, wanted.names())
            if said is not None:
                # As the table has the column, where a file's own value read otherwise by itself
                told = dict(formats._keys_of(Path(str(file)).parent))
                said = pl.DataFrame(
                    [
                        _as_the_table_has_it(said.to_series(place), wanted[name], told.get(name))
                        for place, name in enumerate(said.columns)
                    ]
                )
            added[str(file)] = said
        return added

    def _small_enough(self, read) -> None:
        """Refuse a table in another format than parquet that cannot be read whole within what is held."""
        from chartbook import formats

        if read.format == "ipc":
            raise NotHashed(
                "it is an Arrow IPC file, and what one takes in memory cannot be told from its file: a rows hash reads "
                f"parquet, and a CSV or JSON lines file of up to {OTHER_BYTES // 2**20} MB of text"
            )
        files = formats.files_of(self.path, read, self.files, self.listed, self.inside)
        text = sum(_text_bytes(file, OTHER_BYTES) for file in files)
        if text > OTHER_BYTES:
            raise NotHashed(
                f"it is {read.format}, more than {OTHER_BYTES // 2**20} MB of text, and only parquet is read a little "
                f"at a time: a CSV or JSON lines table has a rows hash up to that"
            )


def _text_bytes(file, most: int) -> int:
    """How many bytes of text a file is, unpacked; counted no further than one past *most*.

    A packed file is known by how it begins, as the reader knows it, and
    not by its name: gzip, zlib or zstd. So the same text counts the same
    whatever it is kept in and whatever it is called.
    """
    with open(file, "rb") as held:
        begins = held.read(4)
    if begins[:2] == b"\x1f\x8b":
        import gzip

        opened = gzip.open(file, "rb")
    elif begins == b"\x28\xb5\x2f\xfd":
        import pyarrow as pa

        opened = pa.CompressedInputStream(pa.OSFile(str(file), "rb"), "zstd")
    elif len(begins) >= 2 and begins[0] == 0x78 and (begins[1] & 0x20) == 0 and (begins[0] * 256 + begins[1]) % 31 == 0:
        import zlib

        try:
            count, unpack = 0, zlib.decompressobj()
            with open(file, "rb") as held:
                while count <= most:
                    packed = held.read(256 * 1024)
                    if not packed:
                         break
                    while packed and count <= most:
                        count += len(unpack.decompress(packed, 1024 * 1024))
                        packed = unpack.unconsumed_tail
            return count
        except zlib.error:
            return os.path.getsize(file)
    else:
        return os.path.getsize(file)
    import zlib

    count = 0
    try:
        with opened:
            while count <= most:
                read = opened.read(1024 * 1024)
                if not read:
                    break
                count += len(read)
    except (EOFError, OSError, zlib.error) as error:
        if isinstance(error, (EOFError, zlib.error)) or _this_machines(error) is None:
            return os.path.getsize(file)
        raise
    return count


def _as_the_table_has_it(value, kind, written: Optional[str]):
    """A key's value for one file, as a polars Series of one row of the type the table gives the column.

    The reader, asked of one file alone, reads ``007`` as a number; the
    table, whose other folders hold text, has it as the text ``007``. So
    where the types differ, text is taken as the folder wrote it, and
    anything else is put in the table's type.
    """
    from chartbook import formats

    pl = _polars()
    if value.dtype == kind:
        return value
    if written is not None:
        coerced = formats._coerced_key_values(value.dtype, value.to_list(), [written], kind)
        return pl.Series(value.name, coerced, dtype=kind)
    return value.cast(kind, strict=False)


def _this_machines(error: BaseException) -> Optional[BaseException]:
    """The trouble of this machine's that an error came of, if it came of one: a file that may not be opened, a disk that failed, no memory; None for a file that is not there, and for anything else.

    ChartBook's reader says what a file could not be read as, and keeps
    what the system said as the cause.
    """
    from chartbook import formats

    seen = 0
    while error is not None and seen < 8:
        if isinstance(error, MemoryError):
            return error
        if isinstance(error, RuntimeError) and str(error).startswith(formats._SCRATCH):
            return error
        if isinstance(error, OSError) and not isinstance(error, FileNotFoundError):
            # What the system says of the machine has a number, or is one of its own kinds. An OSError
            # with neither is a library's word for bytes that are not what they should be
            # ("Corrupt snappy compressed data"), which is the file's, and the same at every try
            if (
                error.errno is not None
                or isinstance(error, (PermissionError, ConnectionError, TimeoutError, InterruptedError, BlockingIOError))
                or re.search(r"\(os error \d+\)", str(error)) is not None
            ):
                return error
        error, seen = error.__cause__ or error.__context__, seen + 1
    return None


def _first_line(error: BaseException) -> str:
    """What an error says, in one line, with no folder of this machine in it: a record of it is read on others."""
    said = str(error).strip()
    said = said.splitlines()[0][:400] if said else type(error).__name__
    return re.sub(r"(?:[A-Za-z]:)?[\\/](?:[^\s'\"\\/:]+[\\/])+", "", said)


def _added_by_the_reader(one, file, wanted: list):
    """What the reader puts on one file's rows beside the file's own columns: a polars frame of one row, or None.

    Asked of the reader, for this file (*one* is its read of the file):
    the columns the file does not have, which are the ``key=value``
    folders of its path; and a column the file has too that a folder of
    its path names, where the reader gives one value of it for the whole
    file, which is then the folder's and not the file's own.
    """
    import pyarrow.parquet as pq

    from chartbook import formats

    pl = _polars()
    names = one.collect_schema().names()
    opened = pq.ParquetFile(str(file))
    if not opened.metadata.num_rows:
        return None  # no row to put anything on
    own = set(opened.schema_arrow.names)
    extra = [name for name in names if name in wanted and name not in own]
    named = {key for key, _ in formats._keys_of(Path(str(file)).parent)}
    doubtful = [name for name in names if name in wanted and name in own and name in named]
    if doubtful:
        # One value in the whole file, as the reader reads it: the key's, put in place of
        # the file's own column, or a column that says the same in every row, which is the same thing
        counted = one.select([pl.nth(names.index(name)).n_unique().alias(f"n{i}") for i, name in enumerate(doubtful)]).collect()
        extra.extend(name for i, name in enumerate(doubtful) if counted[f"n{i}"][0] == 1)
    if not extra:
        return None
    return one.select([pl.nth(names.index(name)) for name in extra]).head(1).collect()


# --- How a parquet file is laid out, told before it is read ----------------------


def _footer_within(file) -> None:
    """Refuse a parquet file whose footer is more than :data:`FOOTER_MOST`, by the eight bytes it ends with.

    :raises NotHashed: Naming the file and the size of its footer.
    """
    try:
        with open(file, "rb") as held:
            held.seek(0, os.SEEK_END)
            whole = held.tell()
            if whole < 12:
                return  # no parquet file: said by whoever reads it
            held.seek(-8, os.SEEK_END)
            ends = held.read(8)
    except OSError:
        return  # said by whoever reads it
    if ends[4:] != b"PAR1":
        return
    size = int.from_bytes(ends[:4], "little")
    if size > whole - 12:
        return  # no footer of this file's: no parquet file, and said by whoever reads it
    if size > FOOTER_MOST:
        raise NotHashed(
            f"{Path(str(file)).name} has a footer of {size / 2**20:,.0f} MB, which lists every column of every row "
            f"group and is read whole before any row: a rows hash reads one of up to {FOOTER_MOST // 2**20} MB. "
            f"Written with fewer row groups, its rows can be hashed"
        )


class _Short(Exception):
    """Raised when a page header runs past the bytes that were read of it."""

    def __init__(self, needed: int = 0):
        super().__init__(needed)
        self.needed = needed


#: The most values a page header is read to: a real one has a few dozen.
_HEADER_VALUES = 5_000


def _number(data, at: int) -> tuple:
    """A whole number as a page header writes one (a varint), and where it ends."""
    found = shift = 0
    while True:
        if at >= len(data):
            raise _Short(at + 1)
        byte = data[at]
        at += 1
        found |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return found, at
        shift += 7
        if shift > 70:
            raise ValueError("a number of more than 64 bits")


def _counted(steps: list) -> None:
    """Count a value of a page header; more than a header has is no header."""
    steps[0] += 1
    if steps[0] > _HEADER_VALUES:
        raise ValueError("a page header of more values than one has")


def _several(data, at: int, size: int, of: int, depth: int, steps: list) -> int:
    """Where *size* values of one type end, in a list, a set or a map of a page header."""
    if of in (1, 2, 3):
        return at + size  # a byte each, however many: not counted one by one
    if of == 7:
        return at + 8 * size
    if size > len(data) - at:
        raise _Short(at + size)  # a byte each at the least
    for _ in range(size):
        _counted(steps)
        at = _passed(data, at, of, depth + 1, steps)
    return at


def _passed(data, at: int, kind: int, depth: int, steps: list) -> int:
    """Where a value of a page header ends, by its type: nothing of it is kept."""
    if depth > 24:
        raise ValueError("a page header nested too deep")
    if kind in (1, 2):
        return at
    if kind == 3:
        return at + 1
    if kind in (4, 5, 6):
        return _number(data, at)[1]
    if kind == 7:
        return at + 8
    if kind == 8:
        size, at = _number(data, at)
        return at + size
    if kind in (9, 10):
        if at >= len(data):
            raise _Short(at + 1)
        head = data[at]
        at += 1
        size, of = head >> 4, head & 0x0F
        if size == 15:
            size, at = _number(data, at)
        return _several(data, at, size, of, depth, steps)
    if kind == 11:
        size, at = _number(data, at)
        if size:
            if at >= len(data):
                raise _Short(at + 1)
            head = data[at]
            at += 1
            if 2 * size > len(data) - at and not {head >> 4, head & 0x0F} <= {1, 2, 3, 7}:
                raise _Short(at + 2 * size)
            for _ in range(size if not {head >> 4, head & 0x0F} <= {1, 2, 3, 7} else 0):
                _counted(steps)
                for of in (head >> 4, head & 0x0F):
                    at = at + 1 if of in (1, 2) else _passed(data, at, of, depth + 1, steps)
            if {head >> 4, head & 0x0F} <= {1, 2, 3, 7}:
                at += size * sum(8 if of == 7 else 1 for of in (head >> 4, head & 0x0F))
        return at
    if kind == 12:
        return _header_fields(data, at, depth + 1, steps)[1]
    raise ValueError(f"a value of no type a page header has ({kind})")


def _header_fields(data, at: int, depth: int = 0, steps: Optional[list] = None) -> tuple:
    """The whole numbers and the structs of a struct in a page header (Thrift's compact form), by field number, and where it ends.

    Only what tells a page's size is kept; text and lists, a page's
    statistics among them, are passed over wherever they end. What is no
    header is found out in a bounded number of steps, at a bounded depth.
    """
    steps = steps if steps is not None else [0]
    if depth > 24:
        raise ValueError("a page header nested too deep")
    found, last = {}, 0
    while True:
        _counted(steps)
        if at >= len(data):
            raise _Short(at + 1)
        head = data[at]
        at += 1
        if head == 0:
            return found, at
        kind, step = head & 0x0F, head >> 4
        if step:
            number = last + step
        else:
            raw, at = _number(data, at)
            number = (raw >> 1) ^ -(raw & 1)
        last = number
        if kind in (4, 5, 6):
            raw, at = _number(data, at)
            found[number] = (raw >> 1) ^ -(raw & 1)
        elif kind == 12:
            found[number], at = _header_fields(data, at, depth + 1, steps)
        else:
            at = _passed(data, at, kind, depth, steps)
        if at > len(data):
            raise _Short(at)


#: The page types of a parquet file, and the encodings that hold a value as
#: a place in a dictionary, or as what it adds to the value before it.
_DATA_PAGES, _DICTIONARY_PAGE = (0, 3), 2
_BY_DICTIONARY, _BY_PREFIX = (2, 8), 7


def _pages(held, start: int, length: int, values: int) -> Iterator:
    """Each page of a column chunk, from its header alone: its type, what it takes unpacked, how many values it has, how they are written, and where in the file its own bytes begin and how many they are.

    No more of the file is read than a header can be: one that says it
    runs past its chunk, or past :data:`HEADER_MOST`, is no header.

    :param held: The file, open to be read.
    :param start: Where the chunk begins, and *length* how many bytes it is.
    :param values: How many values the chunk has, which ends it.
    :raises ValueError: If what is there is no run of pages.
    """
    at, end, counted, seen = start, start + length, 0, 0
    if start < 0 or length < 0:
        raise ValueError("a column chunk that begins nowhere")
    while at < end and (counted < values or not seen):
        most = min(HEADER_MOST, end - at)
        want = min(256, most)
        while True:
            held.seek(at)
            data = held.read(want)
            try:
                found, used = _header_fields(data, 0)
                break
            except _Short as short:
                if len(data) < want or want >= most or short.needed > most:
                    raise ValueError("a page header runs past its chunk") from None
                want = min(most, max(want * 8, short.needed + 64))
        kind, spread, packed = found.get(1), found.get(2), found.get(3)
        if not all(isinstance(one, int) and 0 <= one < 2**31 for one in (kind, spread, packed)):
            raise ValueError("a page header with no sizes")
        if used + packed > end - at:
            raise ValueError("a page runs past its chunk")
        inner = found.get(5) or found.get(8) or found.get(7) or {}
        inner = inner if isinstance(inner, dict) else {}
        count = inner.get(1, 0)
        count = count if isinstance(count, int) and 0 <= count < 2**31 else 0
        written = inner.get(4 if isinstance(found.get(8), dict) else 2)
        if kind in _DATA_PAGES:
            counted += count
        seen += 1
        # A page that is not packed is read as the bytes it has, whatever size its header says it unpacks
        # to; one that is packed cannot unpack to more than its header says. So it takes the greater
        yield kind, max(spread, packed), count, written, at + used, packed
        at += used + packed


#: What pyarrow calls the ways a parquet page is packed.
_PACKED_AS = {"SNAPPY": "snappy", "GZIP": "gzip", "ZSTD": "zstd", "LZ4_RAW": "lz4_raw", "BROTLI": "brotli"}


def _unpacked(data: bytes, spread: int, how: str) -> bytes:
    """A page's bytes unpacked, by the way its column says it is packed.

    :raises Exception: If pyarrow has no name here for the packing, or the bytes are not that.
    """
    import pyarrow as pa

    if how == "UNCOMPRESSED":
        return data
    if how == "LZ4":
        # The older LZ4 of parquet is written two ways: blocks, each after its two sizes, as
        # Hadoop frames them; or one block as it is, which is how pyarrow writes it
        out, at = [], 0
        while at + 8 <= len(data):
            long, short = int.from_bytes(data[at:at + 4], "big"), int.from_bytes(data[at + 4:at + 8], "big")
            if long > spread or short > len(data) - at - 8:
                break
            try:
                out.append(pa.Codec("lz4_raw").decompress(data[at + 8:at + 8 + short], decompressed_size=long, asbytes=True))
            except Exception:  # noqa: BLE001 - not framed so
                break
            at += 8 + short
        if out and at == len(data) and sum(len(one) for one in out) == spread:
            return b"".join(out)
        return pa.Codec("lz4_raw").decompress(data, decompressed_size=spread, asbytes=True)
    return pa.Codec(_PACKED_AS[how]).decompress(data, decompressed_size=spread, asbytes=True)


def _longest_value(held, at: int, packed: int, spread: int, how: str) -> int:
    """The longest value of a dictionary page of text, in bytes: read from the page, which says each value's length before it; the whole page's size where that cannot be read.

    Text held by a dictionary is a few bytes a row in its file and a
    value a row once read, so what a run of rows takes is what the longest
    value takes, at worst. A megabyte of dictionary may be fifty values of
    twenty kilobytes, and then sixteen thousand rows are 300 MB.
    """
    if spread <= 64:
        return spread  # short enough whatever is in it
    try:
        held.seek(at)
        data = held.read(packed)
        # Unpacked to what its header says; a page that is not packed is its bytes as they are
        data = data if how == "UNCOMPRESSED" else _unpacked(data, spread, how)
        longest, place, end = 0, 0, len(data)
        length = struct.Struct("<I").unpack_from
        while place + 4 <= end:
            (size,) = length(data, place)
            if size > longest:
                longest = size
            place += 4 + size
        return longest if place == end else spread
    except Exception:  # noqa: BLE001 - a packing pyarrow has no name for here, a page that is not what it should be: the worst it can be
        return spread


def _most_in(starts, sizes, rows: int, most: int) -> int:
    """The most bytes any *most* rows in a row may take in one column, counted in whole pages: what the pages such a run begins and ends in hold, with those between.

    :param starts: The row each page begins at.
    :param sizes: What each page takes unpacked.
    :param rows: How many rows the column chunk has.
    """
    import numpy as np

    if not len(starts):
        return 0
    following = np.append(starts[1:], rows)
    # A run that begins on the last row of a page ends furthest on: `most` rows from there
    last = np.searchsorted(starts, following + most - 1, side="left")
    gathered = np.concatenate(([0], np.cumsum(sizes, dtype="float64")))
    return int((gathered[last] - gathered[: len(starts)]).max())


#: What a value of each kind a parquet file holds takes once read, in bytes, where the kind says.
_WIDTHS = {"BOOLEAN": 1, "INT32": 4, "INT64": 8, "INT96": 12, "FLOAT": 4, "DOUBLE": 8}


def _read_plan(held, group, wanted: dict, file, walked: Optional[list] = None, as_dictionary=(), lengths: Optional[dict] = None) -> tuple:
    """How a row group is read: how many rows at once, and which columns together; refused where what a reader must hold of it is too much.

    All from its page headers and its dictionaries, before a row of it is
    read. A reader holds a page of every column, and each column's
    dictionary, while it reads a row group: so those together are held to
    :data:`HELD_MOST`, or the file has no rows hash. What a run of rows
    takes once read is: a column of one width, that width a row; text held
    by a dictionary, the dictionary's longest value a row
    (:func:`_longest_value`); and other text, the pages the run lies in,
    counted whole, since what one value of a page takes is not said
    anywhere but in the page. The most rows are read for which that is
    within :data:`READ_MOST` and the pages a run begins and ends in.

    Those pages, two of each column of text, are megabytes at worst and
    bytes as a rule. So where they could add more than :data:`APART_MOST`,
    the columns of text are read apart, a few together, and what each few
    took is seen before the next are read (:func:`_parquet_batches`).

    :param held: The file, open to be read.
    :param group: The row group's metadata.
    :param wanted: The columns to be read, each with the bytes a value of
        it takes, or None for text.
    :param file: The file's path, for what is said of it.
    :param walked: How many pages of the file have been walked, in a list
        of one, counted on here.
    :param as_dictionary: The columns the file's own schema gives as
        dictionaries, a category's: held more times over than text is.
    :param lengths: The declared length of each column of values of one
        fixed length, in bytes.
    :returns: The rows read at once, and the columns to read together,
        each a list of names.
    :raises NotHashed: If the row group cannot be read within what is held.
    """
    import array

    import numpy as np

    name_of = Path(str(file)).name
    walked = walked if walked is not None else [0]
    rows = group.num_rows
    chunks = [group.column(place) for place in range(group.num_columns)]
    chunks = [column for column in chunks if column.path_in_schema in wanted]
    kept = 0
    again: list = []  # what each column's dictionary is held over and above once
    largest = ("", 0)
    fixed, longest, dense = 0, 0, 0.0
    text = []  # for each column of text written out in its pages: its name, where each page begins, what each takes
    for column in chunks:
        name = column.path_in_schema
        of_text = column.physical_type == "BYTE_ARRAY"
        if not of_text:
            # Its width: what its kind says, or its declared length; and what it is read as, if that is more
            width = _WIDTHS.get(column.physical_type) or (lengths or {}).get(name) or 16
            if width > VALUE_MOST:
                raise NotHashed(
                    f"{name_of} holds values of {width / 2**20:,.0f} MB each in {_name_said(name)}, a column of values "
                    f"of one fixed length, and a rows hash reads such values of up to {VALUE_MOST // 2**20} MB"
                )
            fixed += max(width, wanted[name] or 0)
        begins = column.data_page_offset
        if column.has_dictionary_page and column.dictionary_page_offset and 0 < column.dictionary_page_offset < begins:
            begins = column.dictionary_page_offset
        top = dictionary = seen = 0
        counts, sizes = array.array("q"), array.array("d")
        by_dictionary, by_prefix, of_dictionary = False, 0, []
        try:
            for kind, spread, count, written, at, packed in _pages(held, begins, column.total_compressed_size, column.num_values):
                seen += 1
                walked[0] += 1
                if seen > PAGES_MOST or walked[0] > FILE_PAGES_MOST:
                    raise NotHashed(
                        f"{name_of} is written in more pages than are read to learn how it is laid out "
                        f"(more than {PAGES_MOST:,} in a column chunk, or {FILE_PAGES_MOST:,} in the file): pages of a "
                        f"few values each. Written as pandas, polars and pyarrow write by default, its rows can be hashed"
                    )
                if kind == _DICTIONARY_PAGE:
                    dictionary += spread
                    of_dictionary.append((at, packed, spread))
                elif kind in _DATA_PAGES:
                    top = max(top, spread)
                    if not of_text:
                        continue
                    if written in _BY_DICTIONARY:
                        by_dictionary = True
                    elif written == _BY_PREFIX:
                        by_prefix = max(by_prefix, spread)  # each value may be as long as its page
                    else:
                        counts.append(max(1, count))
                        sizes.append(spread)
        except (ValueError, OSError, RecursionError, MemoryError, OverflowError) as error:
            if isinstance(error, (OSError, MemoryError)) and _this_machines(error) is not None:
                raise
            # What the footer says of a chunk is not what a reader holds of it, and is not taken
            # in the place of its pages: what reading it takes is not told, so it is not read
            raise NotHashed(
                f"{name_of} has a column, {_name_said(name)}, whose pages could not be read to learn how it is laid "
                f"out ({_first_line(error)}): what reading it takes is not told, and a rows hash reads only what is"
            ) from None
        # A dictionary is held as its page and again as the values read from it, more times for
        # numbers than for text; one the file's own schema gives as a dictionary is held again by
        # every batch, and once more as each is written out. The eight largest, as they are read
        times = 6 if name in as_dictionary else 3 if of_text else 8
        again.append(dictionary * (times - 1))
        kept += top + dictionary
        if top + dictionary * times > largest[1]:
            largest = (name, top + dictionary * times)
        if kept + sum(sorted(again)[-8:]) > HELD_MOST:
            break  # said below, before any dictionary is read to learn its longest value
        if not of_text:
            continue
        fixed += 8  # where a value begins and ends
        most_a_value = by_prefix
        if by_dictionary:
            # A row of it is a value of the dictionary once read: the longest, at worst
            most_a_value = max(
                most_a_value,
                max(
                    (_longest_value(held, at, min(packed, column.total_compressed_size), spread, column.compression) for at, packed, spread in of_dictionary),
                    default=top,
                ),
            )
        longest += most_a_value
        if len(sizes):
            count_of, size_of = np.frombuffer(counts, dtype="int64"), np.frombuffer(sizes, dtype="float64")
            starts = np.concatenate(([0], np.cumsum(count_of)[:-1]))
            text.append((name, starts, size_of.copy(), int(count_of.sum())))
            dense += float((size_of / count_of).max())
        if max(most_a_value, float(max(sizes, default=0))) > ROW_MOST:
            raise NotHashed(
                f"{name_of} holds text in pages or dictionaries too large to read a row at a time: one value of "
                f"{_name_said(name)} may take {max(most_a_value, float(max(sizes, default=0))) / 2**20:,.0f} MB, and a rows "
                f"hash reads values of up to {ROW_MOST // 2**20} MB. Written with fewer values a page, its rows can be hashed"
            )
    kept += sum(sorted(again)[-8:])
    if kept > HELD_MOST:
        raise NotHashed(
            f"{name_of} has pages too large to read a little at a time: a reader holds a row group's "
            f"largest pages and dictionaries at once, {kept / 2**20:,.0f} MB here ({_name_said(largest[0])} alone "
            f"{largest[1] / 2**20:,.0f} MB), and a rows hash reads up to {HELD_MOST // 2**20} MB. "
            f"Written with fewer values a page or fewer rows a row group, its rows can be hashed"
        )
    most_text = sum(float(sizes.max()) for _, _, sizes, _ in text)
    allowed = READ_MOST + 2 * most_text
    # What is known for sure, the columns of one width, is read a batch at a time; what a row takes in
    # its fullest page, as it is if its values are alike; and what is only bounded, up to the bound
    most = max(1, min(BATCH_ROWS, BATCH_BYTES // max(1, fixed), int(READ_MOST // max(1.0, fixed + longest + dense))))
    while most > 1:
        at_worst = (fixed + longest) * most + sum(_most_in(starts, sizes, count, most) for _, starts, sizes, count in text)
        if at_worst <= allowed:
            break
        most //= 2
    most = max(1, min(most, rows or 1))
    # Which columns are read together: all of them, where the pages a run begins and ends in add little;
    # else the columns of text a few together, each few within what such pages may add
    apart, together, held_by = [], [], 0.0
    if 2 * most_text > APART_MOST:
        for name, _, sizes, _ in text:
            ends = 2 * float(sizes.max())
            if together and held_by + ends > APART_MOST:
                apart.append(together)
                together, held_by = [], 0.0
            together.append(name)
            held_by += ends
        if together:
            apart.append(together)
    of_text_apart = {name for names in apart for name in names}
    first = [column.path_in_schema for column in chunks if column.path_in_schema not in of_text_apart]
    return most, ([first] if first else []) + apart


def _is_arrow_text_or_binary(kind) -> bool:
    import pyarrow as pa

    return (
        pa.types.is_string(kind)
        or pa.types.is_large_string(kind)
        or pa.types.is_binary(kind)
        or pa.types.is_large_binary(kind)
        or getattr(pa.types, "is_string_view", lambda _: False)(kind)
        or getattr(pa.types, "is_binary_view", lambda _: False)(kind)
    )


def _arrow_binary_length(array):
    import pyarrow as pa
    import pyarrow.compute as pc

    kind = array.type
    if getattr(pa.types, "is_string_view", lambda _: False)(kind) or getattr(pa.types, "is_binary_view", lambda _: False)(kind):
        array = array.cast(pa.large_binary())
    return pc.binary_length(array)


def _row_sizes(batch):
    """What each row of a batch takes once every value is written out, in bytes: its own bytes for text, a dictionary's value for each row that names it, and its width for anything else."""
    import numpy as np
    import pyarrow as pa
    import pyarrow.compute as pc

    sizes = np.zeros(batch.num_rows, dtype="int64")
    for column in batch.columns:
        kind = column.type
        if pa.types.is_dictionary(kind):
            if _is_arrow_text_or_binary(column.dictionary.type) and len(column.dictionary):
                long = _arrow_binary_length(column.dictionary)
                sizes += pc.fill_null(pc.take(long, column.indices), 0).to_numpy(zero_copy_only=False).astype("int64") + 8
            else:
                sizes += 8
        elif _is_arrow_text_or_binary(kind):
            sizes += pc.fill_null(_arrow_binary_length(column), 0).to_numpy(zero_copy_only=False).astype("int64") + 8
        else:
            try:
                sizes += max(1, kind.bit_width // 8)
            except ValueError:
                sizes += 16
    return sizes


def _a_little_at_a_time(batch) -> Iterator:
    """A batch in runs of rows that take about :data:`BATCH_BYTES` each once written out, and never less than a row."""
    import numpy as np

    sizes = _row_sizes(batch)
    if int(sizes.sum()) <= 2 * BATCH_BYTES:
        yield batch
        return
    gathered = np.cumsum(sizes)
    start, before = 0, 0
    while start < batch.num_rows:
        end = int(np.searchsorted(gathered, before + BATCH_BYTES, side="right"))
        end = max(end, start + 1)
        yield batch.slice(start, end - start)
        start, before = end, int(gathered[end - 1])


def _parquet_batches(file, target, added) -> Iterator:
    """One parquet file's rows as Arrow record batches of the *target* schema, a few megabytes at a time; *added* is a frame of one row whose columns go on every row.

    What reading a row group takes is told before it is read, from its
    page headers and its dictionaries (:func:`_read_plan`): how many rows
    are read at once, which columns together, and whether it can be read
    within what is held at all. So nothing here is learnt by reading too
    much first. Where its columns of text are read apart, what the ones
    read so far took is looked at before the next are read, and a run of
    rows that has taken too much already is read no further. A batch is
    handed on in runs of rows of about :data:`BATCH_BYTES`
    (:func:`_a_little_at_a_time`).

    :raises NotHashed: If the file is written so that it cannot be read
        within what is held: a footer, a page or a dictionary too large.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    pl = _polars()
    try:
        _footer_within(file)
        # A little of each column at a time, and never a column chunk whole
        buffer = max(64 * 1024, min(1024 * 1024, (48 * 1024 * 1024) // max(1, len(target.names))))
        opened = pq.ParquetFile(str(file), pre_buffer=False, buffer_size=buffer)
        metadata = opened.metadata
        if not metadata.num_rows:
            return
        constant = {}
        if added is not None:
            plain = added.select(
                [
                    pl.nth(i).cast(pl.String) if _kind_of(name, kind) == "text" else pl.nth(i)
                    for i, (name, kind) in enumerate(added.schema.items())
                ]
            ).to_arrow(compat_level=pl.CompatLevel.oldest())
            constant = {name: plain.column(name)[0] for name in plain.column_names}
        stored = opened.schema_arrow
        own = [name for name in target.names if name in stored.names and name not in constant]
        own_set = set(own)

        def finished(batch):
            count = batch.num_rows
            arrays = []
            for item in target:
                if item.name in constant:
                    array = pa.repeat(constant[item.name], count)
                elif item.name in own_set:
                    array = batch.column(item.name)
                else:
                    array = pa.nulls(count, type=item.type)
                if array.type != item.type:
                    array = array.cast(item.type)
                arrays.append(array)
            return pa.RecordBatch.from_arrays(arrays, schema=target)

        if not own:
            # Nothing of the file's own is wanted: only how many rows it has
            for start in range(0, metadata.num_rows, BATCH_ROWS):
                count = min(BATCH_ROWS, metadata.num_rows - start)
                yield finished(pa.RecordBatch.from_arrays([pa.nulls(count)], names=["__none__"]))
            return
        # What a value of each column takes once read: its width, or None for text
        wanted = {}
        for name in own:
            kind = target.field(name).type
            if _is_arrow_text_or_binary(kind):
                wanted[name] = None
            else:
                try:
                    wanted[name] = max(1, kind.bit_width // 8)
                except ValueError:
                    wanted[name] = 16
        as_dictionary = {name for name in own if pa.types.is_dictionary(stored.field(name).type)}
        described = metadata.schema
        lengths = {described.column(place).path: int(described.column(place).length or 0) for place in range(len(described.names))}
        walked = [0]
        others: dict = {}  # the file opened again, once for each few columns read apart

        def reader_of(place: int):
            if place == 0:
                return opened
            if place not in others:
                others[place] = pq.ParquetFile(str(file), metadata=metadata, pre_buffer=False, buffer_size=buffer)
            return others[place]

        with open(file, "rb") as held:
            for group in range(metadata.num_row_groups):
                of_group = metadata.row_group(group)
                if not of_group.num_rows:
                    continue
                rows, together = _read_plan(held, of_group, wanted, file, walked, as_dictionary, lengths)
                readers = [
                    iter(reader_of(place).iter_batches(batch_size=rows, columns=names, row_groups=[group], use_threads=True))
                    for place, names in enumerate(together)
                ]
                while True:
                    parts, taken = [], 0
                    for place, reader in enumerate(readers):
                        if taken > READ_MOST + APART_MOST:
                            # Each few columns were within what is held; together they are not, and no more is read
                            raise NotHashed(
                                f"{Path(str(file)).name} has rows too unevenly large to read within what is held: "
                                f"{rows:,} rows of some of its columns took {taken / 2**20:,.0f} MB as they were read, "
                                f"where their pages said a little. Written with fewer values a page, its rows can be hashed"
                            )
                        part = next(reader, None)
                        if part is None:
                            break
                        parts.append(part)
                        taken += part.nbytes
                    if len(parts) != len(readers):
                        if parts:
                            raise ValueError("its columns ended at different rows")
                        break
                    if len({part.num_rows for part in parts}) != 1:
                        raise ValueError("its columns came in runs of different lengths")
                    if not parts[0].num_rows:
                        continue
                    batch = parts[0] if len(parts) == 1 else pa.RecordBatch.from_arrays(
                        [array for part in parts for array in part.columns],
                        names=[name for part in parts for name in part.schema.names],
                    )
                    for some in _a_little_at_a_time(batch):
                        yield finished(some)
    except (NotHashed, MemoryError):
        raise  # what is no fault of the file's is not said of the file
    except OSError as error:
        if _this_machines(error) is not None:
            raise
        # What pyarrow says of bytes that are not what they should be: the file's, for good
        raise NotRead(f"{Path(str(file)).name} could not be read a batch at a time ({_first_line(error)})") from None
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
    series = series.alias("when")  # a name is a pattern to polars when it begins ^ and ends $
    kind = series.dtype
    if kind == pl.String:
        series = _dates_in_text(series)
        kind = series.dtype
    if kind != pl.Date and not isinstance(kind, pl.Datetime):
        raise NotHashed(f"its date column{f' {_name_said(name)}' if name else ''} is {_type_said(kind)}, which is no date")
    empty = series.is_null().to_numpy()
    # The whole number a time is held as: days for a date, and for a time with a zone the instant
    whole = series.to_physical().cast(pl.Int64).fill_null(0).to_numpy().astype("int64", copy=False)
    unit = "d" if kind == pl.Date else kind.time_unit
    each = {"d": _DAY, "ms": 1000}.get(unit)
    if each is not None:
        reach = (2**63 - 1) // each
        if whole.size and (int(whole.min()) < -reach or int(whole.max()) > reach):
            raise NotHashed(
                f"its columns cannot be put in one form: column {_name_said(name)} has a time past what 64 bits of microseconds hold"
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
    ("%Y-%m-%dT%H:%M%#z", True),
    ("%Y-%m-%d %H:%M%#z", True),
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


def _weighed(schema) -> tuple:
    """The places, in an Arrow schema, of the columns whose values count for more than eight bytes: those of text and of binary, and those of decimals."""
    import pyarrow as pa

    text = [
        place for place, item in enumerate(schema)
        if _is_arrow_text_or_binary(item.type)
    ]
    decimal = [place for place, item in enumerate(schema) if pa.types.is_decimal(item.type)]
    return text, decimal


def row_bytes(batch, weighed: Optional[tuple] = None):
    """What each row of an Arrow record batch counts for, in bytes, when a period is measured.

    Eight bytes for each value (:data:`COLUMN_BYTES`); sixteen, and its
    own bytes, for a value of text or binary; sixteen for a decimal; and
    eight for an empty value, whatever its column. That is what a value
    takes in the one form the rows are hashed in, so a period held to
    :data:`PERIOD_BYTES` is held in about that much memory before it is
    sorted.

    It is counted from the rows alone, so that it is the same number
    whatever wrote them: a whole number is eight bytes whether its file
    held it in one or in eight, a date whether it was a date or a time at
    midnight, a category by its text, and a column with no value in it
    eight a row whatever type its writer gave it.
    """
    import numpy as np

    text, decimal = _weighed(batch.schema) if weighed is None else weighed
    size = np.full(batch.num_rows, COLUMN_BYTES * batch.num_columns, dtype="int64")
    for place in text:
        column = batch.column(place)
        held = column.is_valid().to_numpy(zero_copy_only=False)
        long = _arrow_binary_length(column).fill_null(0).to_numpy(zero_copy_only=False).astype("int64", copy=False)
        size += np.where(held, COLUMN_BYTES + long, 0)
    for place in decimal:
        size += np.where(batch.column(place).is_valid().to_numpy(zero_copy_only=False), COLUMN_BYTES, 0)
    return size


#: How what rows count for is said in a message.
_COUNTED = "eight bytes a value, and sixteen and its own bytes for one of text"


def _a_day_too_large(first: tuple, rows: int, size: int) -> NotHashed:
    when = stamp_text(first[0] - first[0] % _DAY)
    return NotHashed(
        f"its rows of {when} alone, {rows:,} of them, count for {size / 2**20:,.0f} MB ({_COUNTED}), and a rows "
        f"hash holds at most {MOST_BYTES // 2**20} MB at a time, which is never less than a day"
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
    """Raised when a table's rows could not be hashed this time, for no fault of the table's: no room for scratch files, a folder that cannot be written, a file that could not be read just now, no memory.

    Nothing is recorded of its rows then, and what made the record says
    so: the next time may hash them. Only what the system says of the
    machine is this (an ``OSError``, a ``MemoryError``); anything else is
    the same at every try, and is why the table has no rows hash.
    """


def index_columns(names: Iterable[str]) -> list:
    """The columns among some that pandas makes of an index, or a level of one, with no name: ``__index_level_0__``, ``__index_level_1__``, …"""
    return [name for name in names if isinstance(name, str) and _INDEX_LEVEL.fullmatch(name)]


def index_columns_of(table: "Table") -> list:
    """The columns of a parquet table that pandas makes of an index with no name (:func:`index_columns`); none for another format, where pandas writes none, and for what cannot be read as a table.

    Told by the first file's columns, for a table of several files.
    """
    from chartbook import formats

    try:
        if formats.reading(table.path, table.format, table.read_options).format != "parquet":
            return []
        return index_columns(table.schema().names())
    except (NotHashed, ValueError, OSError):
        return []  # no table, or one not read at all: a footer too large, a file that may not be opened


def has_index_column(table: "Table") -> bool:
    """Whether a parquet table has a column pandas makes of an index with no name (:func:`index_columns_of`)."""
    return bool(index_columns_of(table))


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
    except NotHashed as error:
        return {"not_hashed": _first_line(error)}  # a file written so that it is not read: its footer too large
    except (OSError, MemoryError, RuntimeError) as error:
        if _this_machines(error) is None:
            return {}  # no table the reader reads: nothing to say of one
        raise NotNow(f"{type(error).__name__}: {_first_line(error)}") from None
    try:
        return hash_rows(table, date_col).fields()
    except NotHashed as error:
        # One the reader reads, so there is something to say: why no rebuild can meet a pin of it
        return {**({"date_col": dated} if dated else {}), "not_hashed": _first_line(error)}
    except (OSError, MemoryError, RuntimeError) as error:
        if _this_machines(error) is None:
            # A library's word for bytes that are not what they should be: the same at every try
            return {
                **({"date_col": dated} if dated else {}),
                "not_hashed": f"its rows could not be hashed ({type(error).__name__}: {_first_line(error)})",
            }
        # A full disk, a folder that cannot be written, a file that could not be read just
        # now, no memory: this machine's, this time, and nothing to say of the table
        raise NotNow(f"{type(error).__name__}: {_first_line(error)}") from None
    except (KeyboardInterrupt, SystemExit, GeneratorExit):
        raise
    except BaseException as error:  # noqa: BLE001 - whatever else, a panic of polars among them: the same at every try, so it is the table's
        return {
            **({"date_col": dated} if dated else {}),
            "not_hashed": f"its rows could not be hashed ({type(error).__name__}: {_first_line(error)})",
        }


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
        undated: Whether the record's rows are dated by a column that the
            table does not have, or has with no dates in it: nothing of it
            could be put beside a period, and every period differs.
        no_date: How many of the table's rows have no date, where the
            record has no such rows: rows the pin did not have, counted
            apart from *outside*, since no date says where they fall.
    """

    differ: list
    outside: int
    newer: int
    rows: int
    index_column: bool = False
    undated: bool = False
    no_date: int = 0

    @property
    def same(self) -> bool:
        """Whether the table holds the record's rows: every period the same, and no row up to its last timestamp, or with no date, that the record did not have."""
        return not self.differ and not self.outside and not self.no_date


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
        self.weighed = _weighed(schema)
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
        # What it holds, and what it costs to hold at all: a slice of one row of 256 columns is mostly the latter
        self.held += batch.nbytes + 64 * batch.num_columns
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

        return _as_polars(pa.Table.from_batches([batch for key in keys for batch in self.batches(key)], schema=self.schema))

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
                    # Not one that is still written to: a folder's own time does not move when a file in it grows
                    newest = max((inside.stat().st_mtime for inside in left.rglob("*")), default=0)
                    if time.time() - newest > _STALE:
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
    sizes = row_bytes(batch, pieces.weighed)
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

    target = table.arrow_schema()
    weighed = _weighed(target)
    batches, size, rows = [], 0, 0
    for batch in table.batches(scratch=scratch):
        size += int(row_bytes(batch, weighed).sum())
        rows += batch.num_rows
        if size > most:
            return None, rows  # read no further: it is not held, and how many more rows it has is not asked
        batches.append(batch)
    return _as_polars(pa.Table.from_batches(batches, schema=target)), rows


def _as_polars(table):
    """An Arrow table as a polars DataFrame, each column under the name it has: polars gives a column with no name one of its place (``column_0``), which is no name of the table's."""
    pl = _polars()
    frame = pl.from_arrow(table)
    frame = frame if isinstance(frame, pl.DataFrame) else frame.to_frame()
    if frame.columns != list(table.column_names):
        frame.columns = list(table.column_names)
    return frame


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
    # Text is read as dates; and a category is its text, as the form has it
    return kind == pl.Date or isinstance(kind, pl.Datetime) or _kind_of(date_col, kind) == "text"


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
                f"it has no date column, and its rows count for more than {MOST_BYTES // 2**20} MB ({_COUNTED}): "
                f"a rows hash holds a table with no date column whole"
            )
        return RowsRecord({ALL: hash_frame(whole)}, None, count)
    by_month = table.on_disk() > _BY_MONTH_FROM
    pieces = _Pieces(scratch / "pieces", table.arrow_schema())
    count = 0
    in_years: set = set()
    for batch in table.batches(scratch=scratch):
        micro, left, empty = _stamps(batch.column(date_col))
        months = _months(np.floor_divide(micro, _DAY), empty)
        index = months if by_month else months - months % 12
        in_years.update(np.unique(months[~empty] // 12).tolist())
        if len(in_years) > MOST_YEARS:
            # Said as soon as it is so, and not after a file has been put by for each
            raise NotHashed(
                f"its dates fall in more than {MOST_YEARS:,} calendar years, and a rows hash holds a period for "
                f"each year: {MOST_YEARS:,} at most"
            )
        _put(pieces, batch, np.where(empty, -1, index), _ordered(micro, left), left is not None)
        count += batch.num_rows
    pieces.close()
    if -1 in pieces and pieces.sizes[-1] > MOST_BYTES:
        # Said before a year is hashed, and not after all of them
        raise NotHashed(
            f"its rows with no date, {pieces.counts[-1]:,} of them, count for {pieces.sizes[-1] / 2**20:,.0f} MB "
            f"({_COUNTED}), and a rows hash holds at most {MOST_BYTES // 2**20} MB of them at a time"
        )
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
    timestamp, and every dated row of the table is then after it. A record
    of no rows at all holds nothing to compare by, and is not compared.

    :param rows: The record's hashes, by period (:attr:`RowsRecord.rows`).
    :param as_of: Its last timestamp, as text; None if it has none.
    :param known: The periods already known to hold the record's rows, as
        the record writes them: their rows are passed over, not hashed.
    :raises NotHashed: If the table's rows cannot be hashed, or the record
        holds no rows.
    :raises ValueError: If the record names a period that is none.
    """
    if not rows:
        raise NotHashed("the record holds no rows, so there is nothing to tell a table's rows by")
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
    index_column = has_index_column(table)
    if ALL not in rows and not _dated_by(schema, date_col):
        try:
            total = int(table.scan().select(pl.len()).collect().item())
        except Exception:  # noqa: BLE001
            total = 0
        return Compared(sorted(rows) or [ALL], 0, 0, total, index_column, undated=True)
    if ALL in rows:
        # No date column, here or in the record: all the rows, or nothing to compare by
        whole, total = _whole(table, scratch, MOST_BYTES)
        if whole is None:
            raise _too_many("its rows")
        same = set(rows) == {ALL} and hash_frame(whole) == rows[ALL]
        # Never the same for want of a period to differ in: a record of no rows says nothing of a table
        return Compared([] if same else (sorted(rows) or [ALL]), 0, 0, total, index_column, undated=False)
    fine = isinstance(schema[date_col], pl.Datetime) and schema[date_col].time_unit == "ns"
    firsts = np.array([_bound(first, fine, first=True) for _, first, _ in periods], dtype="int64")
    lasts = np.array([_bound(last, fine) for _, _, last in periods], dtype="int64")
    cap = _bound(stamp_of(as_of), fine) if as_of is not None else None
    pieces = _Pieces(scratch / "pieces", table.arrow_schema())
    outside = newer = total = no_date = 0
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
        else:
            no_date += int(empty.sum())  # rows with no date, of which the record has none
        total += batch.num_rows
        newer += int(after.sum())
        outside += int((index == -2).sum()) - int(after.sum()) - (0 if NO_DATE in rows else int(empty.sum()))
        if passed_over:
            index = np.where(np.isin(index, passed_over), -3, index)  # known to be the same: not read again
        # More than is held at a time: not held, and said when the table has been read
        too_many |= {number for number, size in pieces.sizes.items() if size > MOST_BYTES}
        if too_many:
            index = np.where(np.isin(index, list(too_many)), -3, index)
        _put(pieces, batch, index, stamps, fine)
    pieces.close()
    too_many |= {number for number, size in pieces.sizes.items() if size > MOST_BYTES}
    if too_many:
        # No period this version records counts for so much, so they are not such a record's
        # rows; but a record another version made may hold larger periods, and its rows are
        # then not told to differ: they are not compared
        number = min(too_many)
        raise _too_many("its rows with no date" if number == -1 else f"its rows of {periods[number][0].replace('/', ' to ')}")
    differ = []
    for number, (key, _, _) in enumerate(periods):
        if key in known:
            continue
        if number not in pieces or hash_frame(pieces.read([number]), date_col) != rows[key]:
            differ.append(key)
    if NO_DATE in rows and NO_DATE not in known:
        if -1 not in pieces or hash_frame(pieces.read([-1]), date_col) != rows[NO_DATE]:
            differ.append(NO_DATE)
    return Compared(differ, outside, newer, total, index_column, no_date=no_date)


def _too_many(which: str) -> NotHashed:
    """What is said of a table beside a record when a period of the record holds more of the table's rows than are held at a time."""
    return NotHashed(
        f"{which} count for more than {MOST_BYTES // 2**20} MB ({_COUNTED}), which is more than a rows hash holds "
        f"at a time, and more than any period this ChartBook records: they are not compared"
    )


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
    if kind != pl.Date and not isinstance(kind, pl.Datetime) and _kind_of(date_col, kind) == "text":
        # Text is read as dates; and a category is its text, as the form has it
        column, kind = _text_dates(column.cast(pl.String)), pl.Datetime("us")
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
