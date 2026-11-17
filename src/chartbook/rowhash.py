"""Rows hashes: a hash of a table's rows, and not of its file.

A content hash (:mod:`chartbook.hashing`) names the bytes of a file. Two
people who build the same table get the same rows in other bytes: another
parquet writer, another compression, another order of rows. A rows hash
says "the same rows" where a content hash cannot
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

What it does not take yet is a column of lists or of structs
(:class:`NotHashed`): a table with one has no rows hash.
"""

from __future__ import annotations

import hashlib
import re
import struct
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

#: What every rows hash begins with: the name of the form. A change to the
#: form takes another name here and another prefix on the hash.
FORM = b"chartbook/rows/v1\n"

_DAY = 86_400_000_000  # microseconds
_EPOCH = datetime(1970, 1, 1)


class NotHashed(Exception):
    """Raised when a table's rows have no hash: it has a column of a kind the form does not take.

    Such a table is pinned by its bytes alone, and what reads this says so.
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
            if kind == pl.Date:
                column = column.cast(pl.Datetime("us"))
                unit = "us"
            else:
                if kind.time_zone:
                    column = column.dt.convert_time_zone("UTC").dt.replace_time_zone(None)
                unit = kind.time_unit
                if unit == "ms":
                    column, unit = column.cast(pl.Datetime("us")), "us"
            column = column.cast(pl.Int64)
            units[name] = unit
        elif said == "duration":
            unit = kind.time_unit
            if unit == "ms":
                column, unit = column.cast(pl.Duration("us")), "us"
            column = column.cast(pl.Int64)
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
