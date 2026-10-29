"""Tables stored as CSV, JSON lines or Arrow IPC (#134), and a glob in every load format (#135).

A dataframe's file is read by one reader, :mod:`chartbook.formats`, which
``data.load()``, ``data.sql()`` and ``data.ref()``, the page's glimpse, the
data glimpses and the data dictionary share. Its format is its entry's
``format``, else its path's ending; its ``read_options`` go to polars, and
to DuckDB under DuckDB's names.
"""

import gzip
import json
import os
from pathlib import Path

import duckdb
import jsonschema
import pandas as pd
import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import backends, data, formats, index, lock, snapshot
from chartbook.backends import BackendError
from chartbook.cli import main
from chartbook.errors import UnreadableTableError
from chartbook.gitcache import GitCache
from chartbook.manifest import load_manifest
from tests.test_model_versions import _commit, _git

RATES = pl.DataFrame({"d": ["2024-01-01", "2024-01-02", "2024-01-03"], "r": [4.1, 4.2, 4.3]})

#: One JSON object per line, nested: what an API pull or an event stream gives
EVENTS = pl.DataFrame(
    {
        "id": [1, 2],
        "event": [{"kind": "release", "tags": ["a"]}, {"kind": "call", "tags": ["b", "c"]}],
    }
)


def _pipeline(directory: Path, dataframes: dict, **more) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "_data").mkdir(exist_ok=True)
    (directory / "README.md").write_text("# A pipeline\n", encoding="utf-8", newline="\n")
    table = {"project": {"id": "acme/rates"}, **more, "dataframes": {
        name: {"docs": "A dataframe.", **entry} for name, entry in dataframes.items()
    }}
    (directory / "chartbook.toml").write_text(tomli_w.dumps(table), encoding="utf-8", newline="\n")
    return directory


def _write(frame: pl.DataFrame, path: Path) -> Path:
    """A frame written in the format its name's ending says."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = path.name.lower()
    if name.endswith(".gz"):
        inner = _write(frame, path.with_name(path.name[: -len(".gz")]))
        with open(inner, "rb") as plain, gzip.open(path, "wb") as packed:
            packed.write(plain.read())
        inner.unlink()
    elif name.endswith(".tsv"):
        frame.write_csv(path, separator="\t")
    elif name.endswith(".csv"):
        frame.write_csv(path)
    elif name.endswith((".jsonl", ".ndjson")):
        frame.write_ndjson(path)
    elif name.endswith((".arrow", ".feather", ".ipc")):
        frame.write_ipc(path)
    else:
        frame.write_parquet(path)
    return path


class TestTheFormat:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("x.parquet", "parquet"),
            ("x.csv", "csv"),
            ("x.TSV", "csv"),
            ("x.csv.gz", "csv"),
            ("x.tsv.gz", "csv"),
            ("x.jsonl", "jsonl"),
            ("x.ndjson", "jsonl"),
            ("x.jsonl.gz", "jsonl"),
            ("x.arrow", "ipc"),
            ("x.feather", "ipc"),
            ("x.ipc", "ipc"),
            ("year=*/*.csv", "csv"),
            # An ending that names none is parquet, as every path was before
            ("parts", "parquet"),
            ("000000_0", "parquet"),
            ("x.json", "parquet"),
            ("x.gz", "parquet"),
        ],
    )
    def test_the_ending_says_it(self, name, expected):
        read = formats.reading(Path("/data") / name)
        assert read.format == expected
        assert read.said_by == ("default" if formats.ending_of(name) is None else "ending")

    def test_the_entry_says_it_over_the_ending(self):
        read = formats.reading("/data/x.txt", "csv", {"separator": ";"})
        assert (read.format, read.said_by, read.options) == ("csv", "format", {"separator": ";"})
        assert formats.reading("/data/x.parquet", "ipc").format == "ipc"


class TestTheManifest:
    def test_format_and_read_options_are_taken_and_kept_in_the_dictionary(self, tmp_path):
        directory = _pipeline(
            tmp_path / "rates",
            {
                "rates": {
                    "path": "./_data/rates.txt",
                    "format": "csv",
                    "read_options": {"separator": ";", "schema_overrides": {"d": "String"}, "null_values": ["NA"]},
                }
            },
        )
        RATES.write_csv(directory / "_data" / "rates.txt", separator=";")
        loaded = load_manifest(directory)
        assert loaded["dataframes"]["rates"]["format"] == "csv"
        built = index.build_index(loaded)
        record = next(r for r in built["records"] if r["id"] == "acme/rates:rates")
        assert record["format"] == "csv" and [c["name"] for c in record["columns"]] == ["d", "r"]
        assert record["read_options"] == {"separator": ";", "schema_overrides": {"d": "String"}, "null_values": ["NA"]}
        schema = json.loads(index.schema_path("Dataframe").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(record)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate({**record, "format": "excel"})

    @pytest.mark.parametrize(
        "entry, message",
        [
            ({"path": "./_data/x.csv", "format": "excel"}, "format = 'excel' is not a format a dataframe is read in"),
            ({"path": "./_data/x.csv", "format": 3}, "format = 3 is not a format"),
            ({"path": "./_data/x.parquet", "read_options": {"separator": ";"}}, "read_options are for a CSV or JSON lines file"),
            ({"path": "./_data/parts", "read_options": {"separator": ";"}}, "the format of a path whose ending names none"),
            ({"path": "./_data/x.csv", "read_options": {"delimiter": ";"}}, "read_options has 'delimiter', which is not one ChartBook passes to a reader. Polars calls it 'separator'."),
            ({"path": "./_data/x.csv", "read_options": {"encoding": "latin1"}}, "has 'encoding', which is not one ChartBook passes to a reader. It gives"),
            ({"path": "./_data/x.jsonl", "read_options": {"separator": ";"}}, "they are: schema_overrides, infer_schema_length"),
            ({"path": "./_data/x.csv", "read_options": {"separator": ";;"}}, r"read_options.separator must be one character, e.g. separator = \";\""),
            ({"path": "./_data/x.csv", "read_options": {"infer_schema_length": 0}}, "must be a whole number of rows, 1 or more"),
            ({"path": "./_data/x.csv", "read_options": {"has_header": "no"}}, "must be true or false"),
            ({"path": "./_data/x.csv", "read_options": {"schema_overrides": {"zip": "Text"}}}, "gives 'zip' the type 'Text', which is not one ChartBook knows"),
            ({"path": "./_data/x.csv", "read_options": "separator=;"}, "read_options must be a table"),
            ({"source": "local", "table": "t", "format": "csv"}, "has format, and is a table in a source"),
        ],
    )
    def test_what_cannot_be_read_is_refused_when_the_manifest_loads(self, tmp_path, entry, message):
        sources = {"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}}
        directory = _pipeline(tmp_path / "rates", {"x": entry}, sources=sources)
        with pytest.raises(ValueError, match=message) as error:
            load_manifest(directory)
        assert f"{directory / 'chartbook.toml'}: [dataframes.x]" in str(error.value)

    def test_chartbook_check_says_it(self, tmp_path):
        directory = _pipeline(tmp_path / "rates", {"x": {"path": "./_data/x.xlsx", "format": "excel"}})
        result = CliRunner().invoke(main, ["check", "--project-dir", str(directory)])
        assert result.exit_code != 0
        assert "format = 'excel' is not a format a dataframe is read in" in result.output
        assert "[files]" in result.output

    def test_a_type_is_named_whatever_its_capitals(self):
        read = formats.reading("/x.csv", None, {"schema_overrides": {"zip": "string", "n": "INT64"}})
        assert read.options == {"schema_overrides": {"zip": "string", "n": "INT64"}}


class TestLoad:
    @pytest.mark.parametrize(
        "name",
        ["rates.csv", "rates.tsv", "rates.csv.gz", "rates.tsv.gz", "rates.jsonl", "rates.ndjson", "rates.jsonl.gz", "rates.arrow", "rates.feather", "rates.ipc"],
    )
    def test_each_format_loads_in_every_format_load_offers(self, tmp_path, name):
        directory = _pipeline(tmp_path / "rates", {"rates": {"path": f"./_data/{name}"}})
        _write(RATES, directory / "_data" / name)
        lazy = data.load("rates", project_dir=directory)
        assert isinstance(lazy, pl.LazyFrame)
        assert lazy.collect().equals(RATES)
        assert data.load("rates", format="polars_eager", project_dir=directory).equals(RATES)
        as_pandas = data.load("rates", format="pandas", project_dir=directory)
        assert isinstance(as_pandas, pd.DataFrame) and as_pandas["r"].tolist() == [4.1, 4.2, 4.3]

    @pytest.mark.parametrize("name", ["events.jsonl", "events.jsonl.gz", "events.arrow"])
    def test_nested_records_are_structs_and_lists(self, tmp_path, name):
        """Use case 2 of #134: one JSON object per line, gzipped and nested, is a table."""
        directory = _pipeline(tmp_path / "rates", {"events": {"path": f"./_data/{name}"}})
        _write(EVENTS, directory / "_data" / name)
        frame = data.load("events", project_dir=directory)
        schema = frame.collect_schema()
        assert isinstance(schema["event"], pl.Struct)
        unnested = frame.select(pl.col("event").struct.field("tags")).collect()
        assert unnested["tags"].to_list() == [["a"], ["b", "c"]]

    def test_read_options_reach_the_reader(self, tmp_path):
        """A file as a vendor delivers it: a line before the header, semicolons, a zip code with its zeros, NA for nothing."""
        directory = _pipeline(
            tmp_path / "rates",
            {
                "vendor": {
                    "path": "./_data/vendor.csv",
                    "read_options": {
                        "separator": ";",
                        "skip_lines": 1,
                        "null_values": "NA",
                        "schema_overrides": {"zip": "String"},
                    },
                }
            },
        )
        (directory / "_data" / "vendor.csv").write_text("delivered 2026-10-01\nzip;v\n00123;1.5\nNA;2.5\n", encoding="utf-8", newline="\n")
        frame = data.load("vendor", format="polars_eager", project_dir=directory)
        assert frame.schema == pl.Schema({"zip": pl.String, "v": pl.Float64})
        assert frame["zip"].to_list() == ["00123", None]

    def test_a_late_field_is_found_with_a_larger_sample(self, tmp_path):
        """JSON schema inference reads a sample; a field that comes late needs a larger one."""
        directory = _pipeline(
            tmp_path / "rates",
            {
                "short": {"path": "./_data/late.jsonl", "read_options": {"infer_schema_length": 2}},
                "long": {"path": "./_data/late.jsonl", "read_options": {"infer_schema_length": 1000}},
            },
        )
        lines = [f'{{"a": {i}}}' for i in range(5)] + ['{"a": 9, "b": "late"}']
        (directory / "_data" / "late.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        assert data.load("short", project_dir=directory).collect_schema().names() == ["a"]
        assert data.load("long", project_dir=directory).collect_schema().names() == ["a", "b"]

    def test_both_engines_infer_from_the_same_rows(self, tmp_path):
        """Found by a reviewer: polars inferred from 100 rows and DuckDB from 20480, so a field first
        seen at row 150 was dropped by data.load, and a column that turned to text at row 200 failed
        there and was text in data.sql. Both read formats.SAMPLE_ROWS by default."""
        directory = _pipeline(tmp_path / "rates", {"events": {"path": "./_data/late.jsonl"}, "codes": {"path": "./_data/codes.csv"}})
        lines = [f'{{"a": {i}}}' for i in range(150)] + ['{"a": 150, "b": "late"}']
        (directory / "_data" / "late.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        rows = [str(i) for i in range(200)] + ["A7"]
        (directory / "_data" / "codes.csv").write_text("code\n" + "\n".join(rows) + "\n", encoding="utf-8", newline="\n")
        assert data.load("events", project_dir=directory).collect()["b"].to_list()[-1] == "late"
        assert data.sql("select * from {events}", project_dir=directory).collect_schema().names() == ["a", "b"]
        loaded = data.load("codes", project_dir=directory).collect()
        queried = data.sql("select * from {codes}", project_dir=directory).collect()
        assert loaded.schema["code"] == queried.schema["code"] == pl.String
        assert loaded["code"].to_list()[-1] == queried["code"].to_list()[-1] == "A7"

    def test_a_glob_of_json_lines_keeps_a_field_a_later_file_brings(self, tmp_path):
        """Found by a reviewer, the issue's own case: one EARNINGS_RELEASE_<quarter>.jsonl.gz per
        quarter, and a field the later quarters have. Polars inferred a glob from its first file."""
        directory = _pipeline(tmp_path / "rates", {"archive": {"path": "./_data/archive/EARNINGS_RELEASE_*.jsonl.gz"}})
        _write(pl.DataFrame({"id": [1], "kind": ["release"]}), directory / "_data" / "archive" / "EARNINGS_RELEASE_2024Q1.jsonl.gz")
        _write(pl.DataFrame({"id": [2], "kind": ["call"], "guidance": [{"low": 1.0}]}), directory / "_data" / "archive" / "EARNINGS_RELEASE_2024Q2.jsonl.gz")
        loaded = data.load("archive", project_dir=directory).collect()
        assert loaded.columns == ["id", "kind", "guidance"] and loaded["guidance"].to_list() == [None, {"low": 1.0}]
        queried = data.sql("select * from {archive} order by id", project_dir=directory).collect()
        assert queried.columns == ["id", "kind", "guidance"] and queried["guidance"].to_list() == [None, {"low": 1.0}]

    @pytest.mark.parametrize("type_name", ["Int8", "Int16", "UInt8", "UInt16", "Int64", "Float32", "Time", "String"])
    def test_json_lines_overrides_are_casts_after_the_read(self, tmp_path, type_name):
        """Found by a reviewer: polars took JSON lines' overrides as the types to parse, which panicked
        for Int8, Int16, UInt8, UInt16 and Time (a BaseException, out of a page's reach). The file is
        read and then cast."""
        value = "12:30:00" if type_name == "Time" else "7"
        directory = _pipeline(tmp_path / "rates", {"x": {"path": "./_data/x.jsonl", "read_options": {"schema_overrides": {"v": type_name}}}})
        (directory / "_data" / "x.jsonl").write_text(f'{{"v": "{value}"}}\n', encoding="utf-8", newline="\n")
        loaded = data.load("x", project_dir=directory).collect()
        queried = data.sql("select * from {x}", project_dir=directory).collect()
        assert loaded.schema["v"] == getattr(pl, type_name) or (type_name == "Time" and loaded.schema["v"] == pl.Time)
        assert str(loaded["v"][0]) == str(queried["v"][0])

    @pytest.mark.parametrize(
        "values, type_name, expected",
        [
            ([1.5, 2.5, -1.5], "Int64", None),  # DuckDB rounds, polars truncates: one of them, in both
            (["2024-01-02", "01/02/2024"], "Date", "refused"),  # no guess between day and month
            (["yes", "No", "t", "0"], "Boolean", [True, False, True, False]),
            (["2024-01-01T10:00:00Z", "2024-01-02T12:00:00+01:00"], "Datetime", None),  # made UTC
            ([" 7", "8 "], "Int32", [7, 8]),
            ([{"a": 1}], "String", "refused"),
        ],
    )
    def test_json_lines_overrides_give_the_same_values_in_sql(self, tmp_path, values, type_name, expected):
        """Found by a second review: DuckDB's casts rounded where polars truncated, refused a day-first
        date polars guessed, took `yes` and an offset and a padded number where polars refused them,
        and wrote a struct as other text: silent differences. DuckDB is handed what polars reads."""
        directory = _pipeline(tmp_path / "rates", {"x": {"path": "./_data/x.jsonl", "read_options": {"schema_overrides": {"v": type_name}}}})
        (directory / "_data" / "x.jsonl").write_text("".join(json.dumps({"v": v}) + "\n" for v in values), encoding="utf-8", newline="\n")
        if expected == "refused":
            for read in (lambda: data.load("x", project_dir=directory).collect(), lambda: data.sql("select * from {x}", project_dir=directory).collect()):
                with pytest.raises((UnreadableTableError, pl.exceptions.PolarsError, BackendError, duckdb.Error)):
                    read()
            return
        loaded = data.load("x", project_dir=directory).collect()
        queried = data.sql("select * from {x}", project_dir=directory).collect()
        assert loaded.equals(queried)
        if expected is not None:
            assert loaded["v"].to_list() == expected

    def test_a_number_given_as_text_is_its_digits_in_both(self, tmp_path):
        """Found by a reviewer: on polars 1.20 a numeric zip read as String was null; it is cast, as DuckDB casts it."""
        directory = _pipeline(tmp_path / "rates", {"x": {"path": "./_data/x.jsonl", "read_options": {"schema_overrides": {"zip": "String"}}}})
        (directory / "_data" / "x.jsonl").write_text('{"zip": 123}\n', encoding="utf-8", newline="\n")
        assert data.load("x", project_dir=directory).collect()["zip"].to_list() == ["123"]
        assert data.sql("select * from {x}", project_dir=directory).collect()["zip"].to_list() == ["123"]

    @pytest.mark.parametrize("name", ["x.csv", "x.jsonl"])
    def test_an_override_of_a_column_the_file_lacks_is_refused_by_both(self, tmp_path, name):
        """Found by a reviewer: polars passed over it and DuckDB refused it."""
        directory = _pipeline(tmp_path / "rates", {"x": {"path": f"./_data/{name}", "read_options": {"schema_overrides": {"zip": "String"}}}})
        _write(RATES, directory / "_data" / name)
        for read in (lambda: data.load("x", project_dir=directory), lambda: data.sql("select * from {x}", project_dir=directory)):
            with pytest.raises(UnreadableTableError, match="read_options.schema_overrides names 'zip', which it has no column of. Its columns are: d, r."):
                read()

    def test_a_glob_of_csv_files_in_every_format(self, tmp_path):
        directory = _pipeline(tmp_path / "rates", {"years": {"path": "./_data/years/rates_*.csv"}})
        for year, part in (("2024", RATES[:2]), ("2025", RATES[2:])):
            _write(part, directory / "_data" / "years" / f"rates_{year}.csv")
        lazy = data.load("years", project_dir=directory).collect()
        assert lazy.sort("d").equals(RATES)
        assert data.load("years", format="polars_eager", project_dir=directory).sort("d").equals(RATES)
        assert sorted(data.load("years", format="pandas", project_dir=directory)["d"]) == RATES["d"].to_list()

    def test_a_folder_of_files_with_its_format(self, tmp_path):
        """A folder has no ending to say what it holds: its entry says, and the read takes its files of that format."""
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./_data/parts", "format": "csv"}})
        _write(RATES[:2], directory / "_data" / "parts" / "part-0.csv")
        _write(RATES[2:], directory / "_data" / "parts" / "part-1.csv")
        (directory / "_data" / "parts" / "_SUCCESS").write_bytes(b"")
        (directory / "_data" / "parts" / "README.md").write_text("Not a table.\n", encoding="utf-8", newline="\n")
        assert data.load("parts", project_dir=directory).collect().sort("d").equals(RATES)
        assert len(data.load("parts", format="pandas", project_dir=directory)) == 3

    def test_a_folder_of_parquet_is_read_by_its_parts_as_the_page_reads_it(self, tmp_path):
        """One rule for a folder that polars cannot be handed whole, where data.load failed and the glimpse read its parts."""
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./_data/parts"}})
        _write(RATES[:2], directory / "_data" / "parts" / "year=2024" / "000000_0")  # Hive's name, parquet inside
        _write(RATES[2:], directory / "_data" / "parts" / "year=2025" / "part.parquet")
        (directory / "_data" / "parts" / "_SUCCESS").write_bytes(b"")
        (directory / "_data" / "parts" / "README.txt").write_text("Not a table.\n", encoding="utf-8", newline="\n")
        frame = data.load("parts", project_dir=directory).collect()
        assert frame.columns == ["d", "r", "year"] and frame.height == 3
        # DuckDB handed the folder took its .parquet files only: it is handed the parts
        assert data.sql("select count(*) n, max(year) y from {parts}", project_dir=directory).collect().row(0) == (3, 2025)
        # As pandas reads a folder: its Hive keys as categories
        assert isinstance(data.load("parts", format="pandas", project_dir=directory)["year"].dtype, pd.CategoricalDtype)

    @pytest.mark.parametrize("declared", ["./env=prod/data", "./_data/prices/year=2024"])
    @pytest.mark.parametrize("junk", [False, True])
    def test_a_folder_has_no_keys_from_the_folders_above_it(self, tmp_path, declared, junk):
        """Found by a reviewer: handed the folder's files and not the folder, polars took a
        `key=value` above it for a column, so `…/env=prod/data` gained `env` and a folder declared
        as `prices/year=2024` gained `year`, in data.load, the page, the index and the glimpses.
        As before the change, a folder's keys start below it, in every reader; and so with a
        `_SUCCESS` beside the parts, which polars cannot be handed whole."""
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": declared}})
        folder = Path(os.path.normpath(directory / declared))
        _write(RATES[:2], folder / "a.parquet")
        _write(RATES[2:], folder / "b.parquet")
        if junk:
            (folder / "_SUCCESS").write_bytes(b"")
        from chartbook.create_data_glimpses import get_dataset_report
        from chartbook.utils import get_dataframe_glimpse

        assert data.load("parts", project_dir=directory).collect_schema().names() == ["d", "r"]
        assert data.load("parts", format="polars_eager", project_dir=directory).columns == ["d", "r"]
        assert list(data.load("parts", format="pandas", project_dir=directory).columns) == ["d", "r"]
        assert data.sql("select * from {parts}", project_dir=directory).collect_schema().names() == ["d", "r"]
        built = index.build_index(load_manifest(directory))
        record = next(r for r in built["records"] if r["id"] == "acme/rates:parts")
        assert [c["name"] for c in record["columns"]] == ["d", "r"]
        assert get_dataframe_glimpse(folder).startswith("Rows: 3\nColumns: 2\n")
        assert [c["name"] for c in get_dataset_report(folder)["columns"]] == ["d", "r"]

    def test_a_folder_polars_takes_whole_is_handed_to_it_whole(self, tmp_path):
        """A folder of parquet with nothing else in it is read as it was before formats: the folder itself, keys below it."""
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./env=prod/parts"}})
        folder = directory / "env=prod" / "parts"
        _write(RATES[:2], folder / "year=2024" / "a.parquet")
        _write(RATES[2:], folder / "year=2025" / "a.parquet")
        sources, at = formats._sources(folder, formats.reading(folder))
        assert (sources, at) == (str(folder), folder)
        expected = pl.scan_parquet(folder, hive_partitioning=True).collect()
        assert data.load("parts", project_dir=directory).collect().equals(expected)
        assert expected.columns == ["d", "r", "year"]
        assert data.sql("select * from {parts} order by d", project_dir=directory).collect().columns == ["d", "r", "year"]

    @pytest.mark.parametrize("junk", [False, True])
    def test_a_files_own_column_of_a_key_above_is_kept(self, tmp_path, junk):
        """Found by a second review: a file of `id, env` in `env=prod/x/year=2023/` lost its own `env`
        where the folder held a _SUCCESS, a README and a .DS_Store, and data.sql left it out even of a
        folder polars was handed whole. The keys below a folder are put on; a file's columns stay."""
        directory = _pipeline(tmp_path / "rates", {"x": {"path": "./_data/env=prod/x"}})
        folder = directory / "_data" / "env=prod" / "x"
        own = pl.DataFrame({"id": [1, 2], "env": ["a", "b"]})
        _write(own, folder / "year=2023" / "a.parquet")
        _write(own, folder / "year=2024" / "b.parquet")
        if junk:
            (folder / "_SUCCESS").write_bytes(b"")
            (folder / "README.md").write_text("Two years.\n", encoding="utf-8", newline="\n")
            (folder / ".DS_Store").write_bytes(b"\0")
        from chartbook.utils import get_dataframe_glimpse

        expected = [(1, "a", 2023), (1, "a", 2024), (2, "b", 2023), (2, "b", 2024)]
        assert sorted(data.load("x", project_dir=directory).collect().rows()) == expected
        assert sorted(data.sql("select * from {x}", project_dir=directory).collect().rows()) == expected
        assert list(data.load("x", format="pandas", project_dir=directory).columns) == ["id", "env", "year"]
        record = next(r for r in index.build_index(load_manifest(directory))["records"] if r["id"] == "acme/rates:x")
        assert [c["name"] for c in record["columns"]] == ["id", "env", "year"]
        assert "$ env  <str> 'a', 'b', 'a', 'b'" in get_dataframe_glimpse(folder)

    def test_a_key_of_a_folder_above_and_of_a_column_is_no_sql_error(self, tmp_path):
        """Found by a second review: a folder above named `a=b=c`, over files with a column `a`,
        made data.sql's select list empty."""
        directory = _pipeline(tmp_path / "rates", {"x": {"path": "./_data/a=b=c/x"}})
        _write(pl.DataFrame({"a": [1]}), directory / "_data" / "a=b=c" / "x" / "p.parquet")
        (directory / "_data" / "a=b=c" / "x" / "_SUCCESS").write_bytes(b"")
        assert data.sql("select * from {x}", project_dir=directory).collect().rows() == [(1,)]

    def test_a_key_above_a_folder_and_below_it_gives_each_file_its_own(self, tmp_path):
        """Found by a second review: `date=2024-01-01/exp/` holding `date=2024-01-01/` and
        `date=2024-01-02/` beside a _SUCCESS failed in data.load ("height of column 'date'"), and
        data.sql gave every row the date above."""
        directory = _pipeline(tmp_path / "rates", {"x": {"path": "./_data/date=2024-01-01/exp"}})
        folder = directory / "_data" / "date=2024-01-01" / "exp"
        _write(pl.DataFrame({"id": [1]}), folder / "date=2024-01-01" / "a.parquet")
        _write(pl.DataFrame({"id": [2]}), folder / "date=2024-01-02" / "b.parquet")
        (folder / "_SUCCESS").write_bytes(b"")
        import datetime as dt

        expected = [(1, dt.date(2024, 1, 1)), (2, dt.date(2024, 1, 2))]
        assert sorted(data.load("x", project_dir=directory).collect().rows()) == expected
        assert sorted(data.sql("select * from {x}", project_dir=directory).collect().rows()) == expected

    def test_a_key_not_every_file_has_is_no_column(self, tmp_path):
        """As polars reads a folder handed whole, whose files are at more than one depth."""
        for junk in (False, True):
            directory = _pipeline(tmp_path / f"rates{junk}", {"x": {"path": "./_data/x"}})
            _write(RATES[:1], directory / "_data" / "x" / "a.parquet")
            _write(RATES[1:], directory / "_data" / "x" / "y=2024" / "b.parquet")
            if junk:
                (directory / "_data" / "x" / "_SUCCESS").write_bytes(b"")
            assert data.load("x", project_dir=directory).collect_schema().names() == ["d", "r"], junk
            assert data.sql("select * from {x}", project_dir=directory).collect_schema().names() == ["d", "r"], junk

    def test_a_folder_read_as_its_files_keeps_polars_partition_pruning(self, tmp_path):
        """Found by a third review: a folder read as a list of files, every folder pinned from a store
        and every one with a _SUCCESS, had its keys put on by file, which polars cannot prune on: a
        filter on a year read every file, and a group-by took 4 GB where it took 263 MB. With no key
        above the folder, polars reads the keys itself, as it did before formats."""
        directory = _pipeline(tmp_path / "rates", {"x": {"path": "./_data/x"}, "above": {"path": "./_data/env=prod/x"}})
        for folder in (directory / "_data" / "x", directory / "_data" / "env=prod" / "x"):
            for year in (2023, 2024):
                _write(RATES, folder / f"year={year}" / "part-0.parquet")
            (folder / "_SUCCESS").write_bytes(b"")
        frame = data.load("x", project_dir=directory)
        assert formats._FILE not in frame.explain()
        assert frame.filter(pl.col("year") == 2024).collect().height == 3
        # A key above the folder still puts them on by file, as it must
        assert formats._FILE in data.load("above", project_dir=directory).explain()

    @pytest.mark.parametrize("junk", [False, True])
    def test_a_name_a_glob_would_read_otherwise_is_itself(self, tmp_path, junk):
        """Found by a third review: polars and DuckDB take each listed path for a glob, so `tag=[draft]`,
        `tag=a*` and `tag=q?` (as polars writes them with partition_by) gave 8 rows of 6 in data.sql,
        `a[1].parquet` beside `a1.parquet` read a1 twice, and a folder named `run [1]` was "no file yet"."""
        directory = _pipeline(
            tmp_path / "rates",
            {"tags": {"path": "./_data/tags"}, "twins": {"path": "./_data/twins"}, "run": {"path": "./_data/run [1]"}, "one": {"path": "./_data/one [x].parquet"}},
        )
        tags = pl.DataFrame({"tag": ["[draft]", "d", "a*", "ab", "q?", "qx"], "i": [1, 2, 3, 4, 5, 6]})
        tags.write_parquet(directory / "_data" / "tags", partition_by="tag")
        _write(pl.DataFrame({"i": [1]}), directory / "_data" / "twins" / "a[1].parquet")
        _write(pl.DataFrame({"i": [2]}), directory / "_data" / "twins" / "a1.parquet")
        _write(pl.DataFrame({"i": [1]}), directory / "_data" / "run [1]" / "a.parquet")
        _write(pl.DataFrame({"i": [2]}), directory / "_data" / "run [1]" / "b.parquet")
        _write(pl.DataFrame({"i": [1]}), directory / "_data" / "one [x].parquet")
        if junk:
            for folder in ("tags", "twins", "run [1]"):
                (directory / "_data" / folder / "_SUCCESS").write_bytes(b"")
        for name, expected in (("tags", [1, 2, 3, 4, 5, 6]), ("twins", [1, 2]), ("run", [1, 2]), ("one", [1])):
            assert sorted(data.load(name, project_dir=directory).collect()["i"].to_list()) == expected, name
            assert sorted(data.sql(f"select i from {{{name}}}", project_dir=directory).collect()["i"].to_list()) == expected, name
        assert sorted(data.load("tags", project_dir=directory).collect()["tag"].to_list()) == sorted(tags["tag"].to_list())

    def test_json_lines_files_named_as_globs_are_read_as_themselves(self, tmp_path):
        """Polars' JSON reader takes every path for a glob, and has no switch to say otherwise: each is escaped."""
        directory = _pipeline(tmp_path / "rates", {"j": {"path": "./_data/j", "format": "jsonl"}})
        _write(pl.DataFrame({"i": [1]}), directory / "_data" / "j" / "b[1].jsonl")
        _write(pl.DataFrame({"i": [2]}), directory / "_data" / "j" / "b1.jsonl")
        assert sorted(data.load("j", project_dir=directory).collect()["i"].to_list()) == [1, 2]
        assert sorted(data.sql("select i from {j}", project_dir=directory).collect()["i"].to_list()) == [1, 2]

    @pytest.mark.parametrize("above", ["", "env=prod/"])
    @pytest.mark.parametrize(
        "values",
        [["-5", "7"], ["007", "010"], ["", "3"], ["1.5", "2"], ["inf", "-inf"], ["nan", "1"], ["Infinity", "1_000"], ["%205", "x"], ["true", "false"], ["2024-01-01", "2024-01-02"]],
    )
    def test_a_keys_type_and_values_are_polars_own(self, tmp_path, above, values):
        """Found by a third review: ChartBook's own reading of a key's values differed from polars' for
        signs, nan, Infinity, 1_000, URL-escapes, an empty value and numbers past Int64, and a float key
        of inf or nan was SQL DuckDB refused. Polars is asked, on a folder of the same shape."""
        directory = _pipeline(tmp_path / "rates", {"x": {"path": f"./_data/{above}x"}})
        clean = tmp_path / "clean"
        for i, value in enumerate(values):
            for root in (directory / "_data" / f"{above}x", clean):
                _write(pl.DataFrame({"i": [i]}), root / f"k={value}" / "part.parquet")
        (directory / "_data" / f"{above}x" / "_SUCCESS").write_bytes(b"")
        expected = pl.scan_parquet(clean, hive_partitioning=True).collect().sort("i")
        loaded = data.load("x", project_dir=directory).collect().sort("i")
        assert loaded.equals(expected)
        queried = data.sql("select * from {x} order by i", project_dir=directory).collect()
        assert queried.columns == expected.columns
        assert queried.cast(pl.String).rows() == expected.cast(pl.String).rows()

    @pytest.mark.parametrize("format, ending", [("csv", ".dat"), ("csv", ".txt"), ("jsonl", ".json")])
    def test_a_folder_its_entry_names_the_format_of_takes_files_of_any_ending(self, tmp_path, format, ending):
        """Found by a reviewer: a folder of .dat, .txt or .json files was refused even with format given."""
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./_data/parts", "format": format}})
        for i, part in enumerate((RATES[:2], RATES[2:])):
            written = _write(part, directory / "_data" / "parts" / f"part-{i}.{'csv' if format == 'csv' else 'jsonl'}")
            written.rename(written.with_suffix(ending))
        (directory / "_data" / "parts" / "_SUCCESS").write_bytes(b"")
        assert data.load("parts", project_dir=directory).collect().sort("d").equals(RATES)
        assert data.sql("select count(*) n from {parts}", project_dir=directory).collect()["n"][0] == 3

    @pytest.mark.parametrize(
        "format, ending, beside",
        [("jsonl", ".json", ["README.md"]), ("csv", ".dat", ["README.txt", "schema.json"]), ("csv", ".txt", ["notes.md"])],
    )
    def test_such_a_folder_passes_over_what_is_plainly_not_a_table(self, tmp_path, format, ending, beside):
        """Found by a second review: a README.md beside .json files read as JSON lines, and a
        README.txt and a schema.json beside .dat files read as CSV, were read as data."""
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./_data/parts", "format": format}})
        for i, part in enumerate((RATES[:2], RATES[2:])):
            written = _write(part, directory / "_data" / "parts" / f"part-{i}.{'csv' if format == 'csv' else 'jsonl'}")
            written.rename(written.with_suffix(ending))
        for name in beside:
            (directory / "_data" / "parts" / name).write_text('{"about": "the parts"}\n', encoding="utf-8", newline="\n")
        assert data.load("parts", project_dir=directory).collect().sort("d").equals(RATES)
        assert data.sql("select count(*) n from {parts}", project_dir=directory).collect()["n"][0] == 3

    def test_a_json_lines_glob_is_one_scan_and_not_one_a_file(self, tmp_path):
        """Found by a second review: a scan per file, joined, took 48 s to collect 1000 files of 50
        rows. Each file's types are inferred, and the files read by one scan under all of them."""
        directory = _pipeline(tmp_path / "rates", {"many": {"path": "./_data/many/*.jsonl"}})
        for i in range(30):
            _write(pl.DataFrame({"id": [i]}), directory / "_data" / "many" / f"p{i:03d}.jsonl")
        _write(pl.DataFrame({"id": [30], "late": ["x"]}), directory / "_data" / "many" / "p030.jsonl")
        frame = data.load("many", project_dir=directory)
        assert "UNION" not in frame.explain()
        loaded = frame.collect()
        assert loaded.height == 31 and loaded.columns == ["id", "late"] and loaded["late"].to_list()[-1] == "x"

    def test_a_folder_of_arrow_ipc_files_has_its_hive_keys(self, tmp_path):
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./_data/parts", "format": "ipc"}})
        _write(RATES[:2], directory / "_data" / "parts" / "year=2024" / "p.arrow")
        _write(RATES[2:], directory / "_data" / "parts" / "year=2025" / "p.arrow")
        frame = data.load("parts", project_dir=directory).collect()
        assert frame.columns == ["d", "r", "year"] and sorted(frame["year"].to_list()) == [2024, 2024, 2025]

    def test_a_file_that_is_not_its_format_says_which_it_was_read_as(self, tmp_path):
        """Done when: an error naming the file's format, not polars' `... must end with PAR1`; whose words come after."""
        directory = _pipeline(tmp_path / "rates", {"rates": {"path": "./_data/rates.parquet"}})
        _write(RATES, directory / "_data" / "rates.csv").rename(directory / "_data" / "rates.parquet")
        for format in ("polars", "polars_eager", "pandas"):
            with pytest.raises(UnreadableTableError) as error:
                data.load("rates", format=format, project_dir=directory)
            said = str(error.value)
            assert said.startswith(
                f"Dataframe 'rates': {directory / '_data' / 'rates.parquet'} could not be read as parquet, "
                f"the format its ending, .parquet, says. The reader said: "
            )
            assert 'format = "parquet", "csv", "jsonl" or "ipc"' in said
            assert "A file that is not a table is declared under [files], not [dataframes]." in said
            assert error.value.format == "parquet"

    def test_the_readers_own_reason_is_kept(self, tmp_path):
        """Found by a reviewer: an empty CSV, a bad preamble and the like all read "If it is a table stored another way"."""
        directory = _pipeline(tmp_path / "rates", {"empty": {"path": "./_data/empty.csv"}})
        (directory / "_data" / "empty.csv").write_text("", encoding="utf-8", newline="\n")
        with pytest.raises(UnreadableTableError, match=r"could not be read as CSV, the format its ending, .csv, says. The reader said: .*empty"):
            data.load("empty", project_dir=directory)

    def test_a_page_names_no_path_of_the_machine(self, tmp_path):
        """Found by a reviewer: the glimpse of a file that could not be read gave its absolute path to the page."""
        from chartbook.utils import get_dataframe_glimpse

        bad = tmp_path / "deep" / "bad.parquet"
        bad.parent.mkdir()
        bad.write_text("not parquet\n", encoding="utf-8", newline="\n")
        glimpse = get_dataframe_glimpse(bad)
        assert glimpse.startswith("Error reading file: bad.parquet could not be read as parquet")
        assert str(tmp_path) not in glimpse and str(tmp_path.resolve()) not in glimpse
        # Nor the end of one that polars cuts short, for a file that is not there
        gone = get_dataframe_glimpse(tmp_path / "deep" / "gone.parquet")
        assert gone == "Error reading file: gone.parquet is not there."

    def test_a_panic_in_polars_is_a_line_on_the_page(self, tmp_path, monkeypatch):
        """Found by a reviewer: a panic is a BaseException, which `except Exception` let through to end the build."""
        from chartbook.utils import get_dataframe_glimpse

        def panics(*args, **kwargs):
            raise pl.exceptions.PanicException("unexpected dtype when deserializing ndjson")

        monkeypatch.setattr(formats, "scan", panics)
        assert get_dataframe_glimpse(tmp_path / "x.jsonl") == "Error reading file: unexpected dtype when deserializing ndjson"

    def test_a_file_that_begins_as_another_format_is_told_which(self, tmp_path):
        directory = _pipeline(tmp_path / "rates", {"rates": {"path": "./_data/rates.arrow"}, "other": {"path": "./_data/other.jsonl", "format": "ipc"}})
        _write(RATES, directory / "_data" / "rates.parquet").rename(directory / "_data" / "rates.arrow")
        with pytest.raises(UnreadableTableError, match='It begins as a parquet file does: if that is what it is, its entry in \\[dataframes\\] says so with format = "parquet"'):
            data.load("rates", project_dir=directory)
        _write(RATES, directory / "_data" / "other.jsonl")
        with pytest.raises(UnreadableTableError, match="could not be read as Arrow IPC, the format its entry gives"):
            data.load("other", project_dir=directory)

    def test_a_folder_with_none_of_its_format_says_what_it_holds(self, tmp_path):
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./_data/parts"}})
        _write(RATES, directory / "_data" / "parts" / "a.csv")
        with pytest.raises(UnreadableTableError) as error:
            data.load("parts", project_dir=directory)
        assert str(error.value) == (
            "The folder 'parts' holds no parquet file, and a folder is read as parquet unless its entry's "
            'format says otherwise. It holds CSV files: if they are the table, its entry in [dataframes] '
            'says so with format = "csv".'
        )

    def test_nothing_there_yet_is_file_not_found(self, tmp_path):
        directory = _pipeline(tmp_path / "rates", {"one": {"path": "./_data/one.csv"}, "many": {"path": "./_data/y/*.jsonl"}})
        with pytest.raises(FileNotFoundError):
            data.load("one", project_dir=directory)
        with pytest.raises(FileNotFoundError, match=r"\*.jsonl matches no file yet"):
            data.load("many", project_dir=directory)

    def test_the_returned_format_is_not_the_files(self, tmp_path):
        directory = _pipeline(tmp_path / "rates", {"rates": {"path": "./_data/rates.csv"}})
        _write(RATES, directory / "_data" / "rates.csv")
        with pytest.raises(ValueError, match="Invalid format: 'csv'") as error:
            data.load("rates", format="csv", project_dir=directory)
        assert 'is said in its entry in [dataframes]: format = "csv".' in str(error.value)


class TestSql:
    @pytest.fixture
    def pipeline(self, tmp_path):
        directory = _pipeline(
            tmp_path / "rates",
            {
                "rates": {"path": "./_data/rates.parquet"},
                "flat": {"path": "./_data/flat.csv.gz"},
                "tabs": {"path": "./_data/tabs.tsv"},
                "events": {"path": "./_data/events.jsonl.gz"},
                "vendor": {
                    "path": "./_data/vendor.txt",
                    "format": "csv",
                    "read_options": {"separator": ";", "schema_overrides": {"zip": "String"}, "null_values": ["NA", ""], "skip_lines": 1},
                },
                "typed": {"path": "./_data/typed.ndjson", "read_options": {"schema_overrides": {"id": "String"}, "infer_schema_length": 50}},
                "dotted": {"path": "./_data/dotted.jsonl", "read_options": {"schema_overrides": {"price.usd": "Float64"}}},
                "ipc": {"path": "./_data/ipc/year=*/p.arrow"},
                "bounds": {"source": "local", "table": "bounds"},
            },
            sources={"local": {"backend": "duckdb", "url": "duckdb:///./_data/local.duckdb"}},
        )
        _write(RATES, directory / "_data" / "rates.parquet")
        _write(RATES, directory / "_data" / "flat.csv.gz")
        _write(RATES, directory / "_data" / "tabs.tsv")
        _write(EVENTS, directory / "_data" / "events.jsonl.gz")
        _write(EVENTS, directory / "_data" / "typed.ndjson")
        (directory / "_data" / "vendor.txt").write_text("delivered 2026-10-01\nzip;v\n00123;1.5\nNA;2.5\n", encoding="utf-8", newline="\n")
        (directory / "_data" / "dotted.jsonl").write_text('{"price.usd": 1}\n{"price.usd": 2}\n', encoding="utf-8", newline="\n")
        _write(RATES[:2], directory / "_data" / "ipc" / "year=2024" / "p.arrow")
        _write(RATES[2:], directory / "_data" / "ipc" / "year=2025" / "p.arrow")
        con = duckdb.connect(str(directory / "_data" / "local.duckdb"))
        con.sql("create table bounds as select * from (values ('2024-01-01', 4.0), ('2024-01-03', 4.5)) t(d, cap)")
        con.close()
        return directory

    def test_each_format_is_duckdbs_reader_of_it(self, pipeline):
        root = (pipeline / "_data").as_posix()
        assert data.ref("rates", project_dir=pipeline) == f"read_parquet('{root}/rates.parquet')"
        # What DuckDB would otherwise guess is said as polars reads it
        said = "quote = '\"', escape = '\"', nullstr = [''], allow_quoted_nulls = false, sample_size = 20480"
        assert data.ref("flat", project_dir=pipeline) == (
            f"read_csv('{root}/flat.csv.gz', delim = ',', header = true, {said}, hive_partitioning = false)"
        )
        assert data.ref("tabs", project_dir=pipeline) == (
            f"read_csv('{root}/tabs.tsv', delim = '\t', header = true, {said}, hive_partitioning = false)"
        )
        assert data.ref("vendor", project_dir=pipeline) == (
            f"read_csv('{root}/vendor.txt', delim = ';', header = true, quote = '\"', escape = '\"', "
            f"nullstr = ['', 'NA'], allow_quoted_nulls = false, sample_size = 20480, types = {{'zip': 'VARCHAR'}}, "
            f"skip = 1, hive_partitioning = false)"
        )
        assert data.ref("events", project_dir=pipeline) == (
            f"read_json('{root}/events.jsonl.gz', format = 'newline_delimited', sample_size = 20480, hive_partitioning = false)"
        )
        # A JSON lines file with overrides is handed to DuckDB as polars reads it, and has no text
        for name in ("typed", "dotted"):
            with pytest.raises(ValueError, match="is a JSON lines file with schema_overrides, which polars applies and DuckDB is handed"):
                data.ref(name, project_dir=pipeline)
        with pytest.raises(ValueError, match="is an Arrow IPC file, which DuckDB reads with no function of its own"):
            data.ref("ipc", project_dir=pipeline)

    @pytest.mark.parametrize("name", ["rates", "flat", "tabs", "events", "vendor", "typed", "dotted", "ipc"])
    def test_sql_reads_what_load_reads(self, pipeline, name):
        loaded = data.load(name, project_dir=pipeline).collect()
        queried = data.sql(f"select * from {{{name}}}", project_dir=pipeline).collect()
        assert queried.columns == loaded.columns
        assert queried.height == loaded.height
        if name == "vendor":
            assert queried["zip"].to_list() == loaded["zip"].to_list() == ["00123", None]
        if name == "typed":
            assert queried.schema["id"] == loaded.schema["id"] == pl.String
        if name == "dotted":
            assert queried["price.usd"].to_list() == loaded["price.usd"].to_list() == [1.0, 2.0]

    @pytest.mark.parametrize(
        "query",
        [
            "select o.s, p.r from {one} o join {rates} p on o.d = p.d where p.r > 4.15 order by 1",
            "select a.s, b.s as t from {one} a join {one} b using (d) order by 1",
            "select s from {one} where d in (select d from {rates} where r > 4.15) order by 1",
        ],
    )
    def test_an_arrow_ipc_file_polars_wrote_joins_in_duckdb(self, pipeline, query):
        """Found by a reviewer: polars writes text as string_view, and the filter DuckDB pushes into
        the dataset in a join had no kernel for it (`array_filter` on string_view)."""
        _write(RATES.with_columns(s=pl.Series(["a", "b", "c"])), pipeline / "_data" / "one.arrow")
        _pipeline(pipeline, {"rates": {"path": "./_data/rates.parquet"}, "one": {"path": "./_data/one.arrow"}})
        got = data.sql(query, project_dir=pipeline).collect()
        assert got.height in (2, 3) and got["s"].dtype == pl.String

    def test_arrow_ipc_in_a_memory_source_is_one_view_however_often_it_is_read(self, pipeline):
        """Found by a reviewer: each data.sql() left a chartbook_ipc_<uuid> view in a :memory: source, for the process."""
        _pipeline(
            pipeline,
            {"ipc": {"path": "./_data/ipc/year=*/p.arrow"}, "kept": {"source": "mem", "table": "kept"}},
            sources={"mem": {"backend": "duckdb", "url": "duckdb:///:memory:"}},
        )
        data.connect("mem", project_dir=pipeline).sql("create or replace table kept as select '2024-01-01' as d")
        for _ in range(3):
            got = data.sql("select k.d, i.year from {kept} k join {ipc} i using (d)", project_dir=pipeline).collect()
            assert got.rows() == [("2024-01-01", 2024)]
        views = data.connect("mem", project_dir=pipeline).sql(
            "select count(*) from duckdb_views() where view_name like 'chartbook_ipc_%'"
        ).fetchone()[0]
        assert views == 1

    def test_an_engine_that_takes_no_arrow_is_not_handed_any(self):
        """A plugin's backend written before sql() took arrow= is refused an Arrow IPC file, with a message, not a TypeError."""
        from chartbook.data import _takes_arrow

        class Old:
            def sql(self, query):
                return query

        class New:
            def sql(self, query, arrow=None):
                return query

        assert not _takes_arrow(Old()) and _takes_arrow(New())
        assert _takes_arrow(backends.DuckDBBackend.scratch())

    def test_csv_options_mean_the_same_to_duckdb(self, tmp_path):
        """Found by a reviewer: null_values took DuckDB's '' away, a file with no header had other names
        in DuckDB (and overrides of them failed), DuckDB guessed ' for a quote and \\ for an escape,
        and a quoted "" was NULL in DuckDB and '' in polars."""
        directory = _pipeline(
            tmp_path / "rates",
            {
                "nulls": {"path": "./_data/nulls.csv", "read_options": {"null_values": ["NA"]}},
                "bare": {"path": "./_data/bare.csv", "read_options": {"has_header": False}},
                "typed": {"path": "./_data/typed.csv", "read_options": {"has_header": False}},
                "quotes": {"path": "./_data/quotes.csv"},
            },
        )
        (directory / "_data" / "nulls.csv").write_text("a,b\n1,NA\n2,\n", encoding="utf-8", newline="\n")
        (directory / "_data" / "bare.csv").write_text("1,x\n2,y\n", encoding="utf-8", newline="\n")
        (directory / "_data" / "quotes.csv").write_text(
            "name,said\nO'Brien,\"\"\nit's,\"a \"\"quote\"\"\"\nback\\slash,x\n", encoding="utf-8", newline="\n"
        )
        (directory / "_data" / "typed.csv").write_text("00123,1\n", encoding="utf-8", newline="\n")
        named = data.load("bare", project_dir=directory).collect_schema().names()
        manifest = {
            "nulls": {"path": "./_data/nulls.csv", "read_options": {"null_values": ["NA"]}},
            "bare": {"path": "./_data/bare.csv", "read_options": {"has_header": False}},
            "typed": {"path": "./_data/typed.csv", "read_options": {"has_header": False, "schema_overrides": {named[0]: "String"}}},
            "quotes": {"path": "./_data/quotes.csv"},
        }
        _pipeline(directory, manifest)
        for name in manifest:
            loaded = data.load(name, project_dir=directory).collect()
            queried = data.sql(f"select * from {{{name}}}", project_dir=directory).collect()
            assert queried.columns == loaded.columns, name
            assert queried.cast(pl.String).rows() == loaded.cast(pl.String).rows(), name
        assert data.load("nulls", project_dir=directory).collect()["b"].to_list() == [None, None]
        assert data.load("typed", project_dir=directory).collect()[named[0]].to_list() == ["00123"]
        assert data.load("quotes", project_dir=directory).collect()["said"].to_list() == ["", 'a "quote"', "x"]

    def test_csv_names_are_chartbooks_in_both_and_in_every_polars(self, tmp_path):
        """Found by a second review: a file with no header was column_1… in polars 1.33, column_0… in
        2.0 and column0… in DuckDB; an empty header name was "" in polars and column1 in DuckDB, and
        a repeated one a_duplicated_0 and a_1. ChartBook names them itself, and gives DuckDB the names."""
        directory = _pipeline(
            tmp_path / "rates",
            {
                "bare": {"path": "./_data/bare.csv", "read_options": {"has_header": False, "schema_overrides": {"column_1": "String"}}},
                "odd": {"path": "./_data/odd.csv"},
            },
        )
        (directory / "_data" / "bare.csv").write_text("007,x\n008,y\n", encoding="utf-8", newline="\n")
        (directory / "_data" / "odd.csv").write_text("a,,a\n1,2,3\n", encoding="utf-8", newline="\n")
        bare = data.load("bare", project_dir=directory).collect()
        assert bare.columns == ["column_1", "column_2"] and bare["column_1"].to_list() == ["007", "008"]
        assert data.sql("select * from {bare}", project_dir=directory).collect().equals(bare)
        odd = data.load("odd", project_dir=directory).collect()
        assert odd.columns[:2] == ["a", "column_2"]
        assert data.sql("select * from {odd}", project_dir=directory).collect().columns == odd.columns

    def test_a_csv_glob_whose_files_differ_is_refused_by_both(self, tmp_path):
        """Found by a second review: data.load refused it, and DuckDB read every file as the first."""
        directory = _pipeline(tmp_path / "rates", {"years": {"path": "./_data/y/*.csv"}})
        _write(RATES, directory / "_data" / "y" / "a.csv")
        _write(RATES.with_columns(extra=pl.lit(1)), directory / "_data" / "y" / "b.csv")
        for read in (lambda: data.load("years", project_dir=directory), lambda: data.sql("select * from {years}", project_dir=directory)):
            with pytest.raises(UnreadableTableError, match="could not be read as CSV"):
                read()

    def test_a_csv_override_to_boolean_takes_the_same_words_in_both(self, tmp_path):
        """Found by a second review: DuckDB took yes and no for true and false, and polars refused them."""
        directory = _pipeline(tmp_path / "rates", {"b": {"path": "./_data/b.csv", "read_options": {"schema_overrides": {"b": "Boolean"}}}})
        (directory / "_data" / "b.csv").write_text("b\nyes\nNo\nt\n0\n\n", encoding="utf-8", newline="\n")
        loaded = data.load("b", project_dir=directory).collect()
        assert loaded["b"].to_list() == [True, False, True, False, None]
        assert data.sql("select * from {b}", project_dir=directory).collect().equals(loaded)

    @pytest.mark.parametrize(
        "query",
        [
            "select * from {cats} where cat = 'x'",
            "select * from {cats} where kind = 'lo'",
            "select a.cat from {cats} a join {cats} b using (cat)",
            "select a.kind from {cats} a join {cats} b on a.kind = b.kind",
        ],
    )
    def test_arrow_ipc_categories_and_enums_are_read_in_duckdb(self, tmp_path, query):
        """Found by a second review: a Categorical or an Enum is a dictionary of string_view, which a
        filter or a join DuckDB pushed into the dataset had no kernel for."""
        directory = _pipeline(tmp_path / "rates", {"cats": {"path": "./_data/cats.arrow"}})
        _write(
            pl.DataFrame({"cat": pl.Series(["x", "y", "x"], dtype=pl.Categorical), "kind": pl.Series(["lo", "hi", "lo"], dtype=pl.Enum(["lo", "hi"]))}),
            directory / "_data" / "cats.arrow",
        )
        assert data.sql(query, project_dir=directory).collect().height in (2, 5)

    def test_arrow_ipc_under_a_key_has_the_keys_below_it_in_both(self, tmp_path):
        """Found by a second review: a file under `env=prod/` gained `env` in data.load and not in data.sql."""
        directory = _pipeline(tmp_path / "rates", {"one": {"path": "./_data/env=prod/one.arrow"}, "parts": {"path": "./_data/env=prod/parts/*/p.arrow"}})
        _write(RATES, directory / "_data" / "env=prod" / "one.arrow")
        _write(RATES[:2], directory / "_data" / "env=prod" / "parts" / "year=2024" / "p.arrow")
        _write(RATES[2:], directory / "_data" / "env=prod" / "parts" / "year=2025" / "p.arrow")
        for name, columns in (("one", ["d", "r"]), ("parts", ["d", "r", "year"])):
            loaded = data.load(name, project_dir=directory).collect()
            queried = data.sql(f"select * from {{{name}}}", project_dir=directory).collect()
            assert loaded.columns == queried.columns == columns, name
            assert sorted(loaded.rows()) == sorted(queried.rows()), name

    def test_files_of_every_format_join_a_table_in_a_source(self, pipeline):
        # DuckDB finds the dates in a CSV's text, where polars leaves it text
        joined = data.sql(
            "select i.d, f.r, i.year, b.cap::double as cap from {flat} f "
            "join {ipc} i on f.d::varchar = i.d join {bounds} b on b.d = i.d order by i.d",
            project_dir=pipeline,
        ).collect()
        assert joined.to_dicts() == [
            {"d": "2024-01-01", "r": 4.1, "year": 2024, "cap": 4.0},
            {"d": "2024-01-03", "r": 4.3, "year": 2025, "cap": 4.5},
        ]

    def test_csv_in_hive_folders_has_no_keys_in_either(self, tmp_path):
        """Polars reads no Hive columns from CSV or JSON lines, and DuckDB is told not to, so the two agree."""
        directory = _pipeline(tmp_path / "rates", {"years": {"path": "./_data/y/year=*/part.csv"}})
        _write(RATES[:2], directory / "_data" / "y" / "year=2024" / "part.csv")
        _write(RATES[2:], directory / "_data" / "y" / "year=2025" / "part.csv")
        assert data.load("years", project_dir=directory).collect_schema().names() == ["d", "r"]
        assert data.sql("select * from {years}", project_dir=directory).collect_schema().names() == ["d", "r"]


class TestTheDataframesPages:
    @pytest.fixture
    def pipeline(self, tmp_path):
        directory = _pipeline(
            tmp_path / "rates",
            {
                "flat": {"path": "./_data/flat.csv.gz", "date_col": "d"},
                "events": {"path": "./_data/events.jsonl"},
                "ipc": {"path": "./_data/ipc.feather"},
                "parts": {"path": "./_data/parts", "format": "csv", "read_options": {"separator": ";"}},
                "nothing": {"path": "./_data/nothing", "format": "jsonl"},
            },
        )
        _write(RATES, directory / "_data" / "flat.csv.gz")
        _write(EVENTS, directory / "_data" / "events.jsonl")
        _write(RATES, directory / "_data" / "ipc.feather")
        (directory / "_data" / "parts").mkdir()
        (directory / "_data" / "parts" / "a.csv").write_text("d;r\n2024-01-01;4.1\n", encoding="utf-8", newline="\n")
        (directory / "_data" / "parts" / "b.csv").write_text("d;r\n2024-01-02;4.2\n", encoding="utf-8", newline="\n")
        (directory / "_data" / "nothing").mkdir()
        return directory

    def test_the_dictionary_describes_each_as_load_reads_it(self, pipeline):
        built = index.build_index(load_manifest(pipeline))
        records = {r["id"]: r for r in built["records"] if r["kind"] == "Dataframe"}
        flat = records["acme/rates:flat"]
        assert (flat["row_count"], [c["name"] for c in flat["columns"]]) == (3, ["d", "r"])
        assert flat["date_range"] == {"first": "2024-01-01T00:00:00", "last": "2024-01-03T00:00:00"}
        assert records["acme/rates:events"]["row_count"] == 2
        assert {c["name"]: c["dtype"] for c in records["acme/rates:events"]["columns"]}["event"].startswith("struct")
        assert records["acme/rates:ipc"]["row_count"] == 3
        assert records["acme/rates:parts"]["row_count"] == 2 and records["acme/rates:parts"]["format"] == "csv"

    def test_the_page_glimpse_and_the_data_glimpses_read_each(self, pipeline):
        from chartbook.create_data_glimpses import create_txt_report, find_declared_dataframes, get_dataset_report
        from chartbook.utils import get_dataframe_glimpse

        assert get_dataframe_glimpse(pipeline / "_data" / "flat.csv.gz").startswith("Rows: 3\nColumns: 2\n")
        assert get_dataframe_glimpse(pipeline / "_data" / "events.jsonl").startswith("Rows: 2\nColumns: 2\n")
        assert get_dataframe_glimpse(pipeline / "_data" / "ipc.feather").startswith("Rows: 3\n")
        assert get_dataframe_glimpse(pipeline / "_data" / "parts", "csv", {"separator": ";"}).startswith("Rows: 2\nColumns: 2\n")
        assert get_dataframe_glimpse(pipeline / "_data" / "nothing", "jsonl") == (
            "No JSON lines file in nothing/: a folder is shown by its JSON lines parts, and this one has none yet."
        )
        declared = {d.dataframe_id: d for d in find_declared_dataframes(load_manifest(pipeline))}
        assert declared["parts"].format == "csv" and declared["parts"].read_options == {"separator": ";"}
        report = get_dataset_report(declared["parts"].path, format="csv", read_options={"separator": ";"})
        assert (report["n_rows"], report["n_cols"], report["file_type"]) == (2, 2, "CSV")
        assert report["file_size_bytes"] == sum(f.stat().st_size for f in (pipeline / "_data" / "parts").iterdir())
        assert get_dataset_report(pipeline / "_data" / "events.jsonl")["file_type"] == "JSONL"
        text = create_txt_report([declared["flat"], declared["events"], declared["parts"]])
        assert "**Type:** CSV |" in text and "**Type:** JSON lines |" in text
        assert "ERROR" not in text

    def test_a_download_keeps_its_files_ending(self):
        from chartbook.sitefiles import download_link

        def record(path, **more):
            return {"ref": {"name": "rates"}, "location": {"kind": "file", "path": path}, **more}

        assert download_link(record("./_data/rates.parquet")) == {"download_file": "rates.parquet", "download_format": "Parquet"}
        assert download_link(record("./_data/r.csv.gz")) == {"download_file": "rates.csv.gz", "download_format": "CSV"}
        assert download_link(record("./_data/r.ndjson")) == {"download_file": "rates.ndjson", "download_format": "JSON lines"}
        assert download_link(record("./_data/r.txt", format="csv")) == {"download_file": "rates.csv", "download_format": "CSV"}
        assert download_link(record("./_data/r.feather")) == {"download_file": "rates.feather", "download_format": "Arrow IPC"}


@pytest.fixture
def two_pipelines(tmp_path):
    """``rates`` keeps a vendor's CSV as delivered, and a folder of JSON lines; ``forecast`` reads them."""
    work = tmp_path.resolve() / "work"
    rates = _pipeline(
        work / "rates",
        {
            "vendor": {"path": "./_data/vendor.txt", "format": "csv", "read_options": {"separator": ";", "schema_overrides": {"zip": "String"}}},
            "events": {"path": "./_data/events", "format": "jsonl"},
            "flat": {"path": "./_data/flat.csv"},
        },
    )
    (rates / "_data" / "vendor.txt").write_text("zip;v\n00123;1.5\n00456;2.5\n", encoding="utf-8", newline="\n")
    _write(EVENTS[:1], rates / "_data" / "events" / "a.jsonl")
    _write(EVENTS[1:], rates / "_data" / "events" / "b.jsonl")
    _write(RATES, rates / "_data" / "flat.csv")
    forecast = work / "forecast"
    forecast.mkdir()
    (forecast / "README.md").write_text("# Forecast\n", encoding="utf-8", newline="\n")
    (forecast / "chartbook.toml").write_text(
        tomli_w.dumps({"project": {"id": "acme/forecast"}, "dependencies": {"rates": {"path": "../rates"}}}),
        encoding="utf-8",
        newline="\n",
    )
    _git(work, "init", "--quiet", "-b", "main")
    (work / ".gitignore").write_text("_data/\nchartbook.lock\n", encoding="utf-8", newline="\n")
    _commit(work)
    return rates, forecast


class TestAnotherPipelineReadsThem:
    def test_a_pin_keeps_how_its_owner_reads_it(self, two_pipelines, monkeypatch):
        """The reader of a pin has none of the owner's manifest: the record keeps its format and options."""
        rates, forecast = two_pipelines
        taken = snapshot.make(rates).snapshot
        assert taken.assets["vendor"]["location"] == {
            "kind": "file",
            "path": "./_data/vendor.txt",
            "format": "csv",
            "read_options": {"separator": ";", "schema_overrides": {"zip": "String"}},
        }
        # Nothing said, nothing kept: a record as it was before
        assert taken.assets["flat"]["location"] == {"kind": "file", "path": "./_data/flat.csv"}
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        vendor = data.load("rates:vendor", format="polars_eager")
        assert vendor["zip"].to_list() == ["00123", "00456"]
        assert data.sql("select count(*) n from {rates:vendor} where zip like '00%'").collect()["n"][0] == 2
        # A folder its record lists the files of, read as the owner's format says
        events = data.load("rates:events").collect()
        assert sorted(events["id"].to_list()) == [1, 2]
        assert data.load("rates:flat", format="pandas")["r"].tolist() == [4.1, 4.2, 4.3]

    def test_a_pinned_folder_its_name_gives_the_format_of_is_read_so(self, two_pipelines, monkeypatch):
        """Found by a reviewer: a Spark folder declared as `prices.csv`, with no format key, was read by
        its owner as CSV, and by a pipeline that pinned it as parquet: the store's folder has no ending,
        and the record keeps no format. The declared path's ending, which the record keeps, says it."""
        rates, forecast = two_pipelines
        _pipeline(rates, {"prices": {"path": "./_data/prices.csv"}})
        _write(RATES[:2], rates / "_data" / "prices.csv" / "part-00000.csv")
        _write(RATES[2:], rates / "_data" / "prices.csv" / "part-00001.csv")
        (rates / "_data" / "prices.csv" / "_SUCCESS").write_bytes(b"")
        _commit(rates.parent)
        assert data.load("prices", project_dir=rates).collect().height == 3
        taken = snapshot.make(rates).snapshot
        assert taken.assets["prices"]["location"] == {"kind": "file", "path": "./_data/prices.csv"}
        lock.pin(forecast)
        monkeypatch.chdir(forecast)
        assert data.load("rates:prices").collect().sort("d").equals(RATES)
        assert data.sql("select count(*) n from {rates:prices}").collect()["n"][0] == 3

    def test_a_git_dependency_keeps_it_too(self, tmp_path):
        work = tmp_path.resolve()
        upstream = _pipeline(
            work / "upstream",
            {"vendor": {"path": "./data/vendor.txt", "format": "csv", "read_options": {"separator": ";"}}},
        )
        (upstream / "data").mkdir()
        (upstream / "data" / "vendor.txt").write_text("zip;v\n00123;1.5\n", encoding="utf-8", newline="\n")
        _git(upstream, "init", "--quiet", "-b", "main")
        _git(upstream, "add", "-A")
        _git(upstream, "commit", "--quiet", "-m", "The vendor's file")
        downstream = work / "downstream"
        downstream.mkdir()
        (downstream / "chartbook.toml").write_text(
            tomli_w.dumps({"project": {"id": "downstream"}, "dependencies": {"acme/upstream": {"git": "../upstream"}}}),
            encoding="utf-8",
            newline="\n",
        )
        lock.pin(downstream, git_cache=GitCache(work / "cache"))
        locked = lock.read_lock(downstream / lock.LOCK_FILE)
        record = locked.assets["acme/upstream:vendor"]
        assert record["location"]["format"] == "csv" and record["location"]["read_options"] == {"separator": ";"}
        frame = data.load("acme/upstream:vendor", format="polars_eager", project_dir=downstream)
        assert frame.columns == ["zip", "v"]


def test_the_projects_template_asks_for_the_versions_chartbook_needs():
    """Found by a second review: the template still asked for polars 1.20, which DuckDB 1.5's lazy
    frames do not work with; and polars' Arrow IPC files hold string_view, which pyarrow reads from 16."""
    import re

    root = Path(__file__).parent.parent
    floors = dict(re.findall(r'"(polars|pyarrow)>=([\d.]+)"', (root / "pyproject.toml").read_text(encoding="utf-8")))
    assert floors == {"polars": "1.33", "pyarrow": "16"}
    template = root / "template" / "{{cookiecutter.project_slug}}"
    for name in ("requirements.txt", "pixi.toml", "environment.yml", "pyproject.toml"):
        text = (template / name).read_text(encoding="utf-8")
        for package, floor in floors.items():
            assert re.search(rf"{package}\W*>=\s*{re.escape(floor)}", text), (name, package)
