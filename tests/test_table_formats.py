"""Tables stored as CSV, JSON lines or Arrow IPC (#134), and a glob in every load format (#135).

A dataframe's file is read by one reader, :mod:`chartbook.formats`, which
``data.load()``, ``data.sql()`` and ``data.ref()``, the page's glimpse, the
data glimpses and the data dictionary share. Its format is its entry's
``format``, else its path's ending; its ``read_options`` go to polars, and
to DuckDB under DuckDB's names.
"""

import gzip
import json
from pathlib import Path

import duckdb
import jsonschema
import pandas as pd
import polars as pl
import pytest
import tomli_w
from click.testing import CliRunner

from chartbook import data, formats, index, lock, snapshot
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
        """A file as a vendor delivers it: semicolons, a comment line, a zip code with its zeros, NA for nothing."""
        directory = _pipeline(
            tmp_path / "rates",
            {
                "vendor": {
                    "path": "./_data/vendor.csv",
                    "read_options": {
                        "separator": ";",
                        "comment_prefix": "#",
                        "null_values": "NA",
                        "schema_overrides": {"zip": "String"},
                    },
                }
            },
        )
        (directory / "_data" / "vendor.csv").write_text("# delivered 2026-10-01\nzip;v\n00123;1.5\nNA;2.5\n", encoding="utf-8", newline="\n")
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
        """One rule for a folder, where data.load handed polars the folder and the glimpse read its parts."""
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./_data/parts"}})
        _write(RATES[:2], directory / "_data" / "parts" / "year=2024" / "000000_0")  # Hive's name, parquet inside
        _write(RATES[2:], directory / "_data" / "parts" / "year=2025" / "part.parquet")
        (directory / "_data" / "parts" / "_SUCCESS").write_bytes(b"")
        (directory / "_data" / "parts" / "README.txt").write_text("Not a table.\n", encoding="utf-8", newline="\n")
        frame = data.load("parts", project_dir=directory).collect()
        assert frame.columns == ["d", "r", "year"] and frame.height == 3
        assert data.sql("select count(*) n, max(year) y from {parts}", project_dir=directory).collect().row(0) == (3, 2025)
        # As pandas reads a folder: its Hive keys as categories
        assert isinstance(data.load("parts", format="pandas", project_dir=directory)["year"].dtype, pd.CategoricalDtype)

    def test_a_folder_of_arrow_ipc_files_has_its_hive_keys(self, tmp_path):
        directory = _pipeline(tmp_path / "rates", {"parts": {"path": "./_data/parts", "format": "ipc"}})
        _write(RATES[:2], directory / "_data" / "parts" / "year=2024" / "p.arrow")
        _write(RATES[2:], directory / "_data" / "parts" / "year=2025" / "p.arrow")
        frame = data.load("parts", project_dir=directory).collect()
        assert frame.columns == ["d", "r", "year"] and sorted(frame["year"].to_list()) == [2024, 2024, 2025]

    def test_a_file_that_is_not_its_format_says_which_it_was_read_as(self, tmp_path):
        """Done when: an error naming the file's format, not polars' `... must end with PAR1`."""
        directory = _pipeline(tmp_path / "rates", {"rates": {"path": "./_data/rates.parquet"}})
        _write(RATES, directory / "_data" / "rates.csv").rename(directory / "_data" / "rates.parquet")
        for format in ("polars", "polars_eager", "pandas"):
            with pytest.raises(UnreadableTableError) as error:
                data.load("rates", format=format, project_dir=directory)
            said = str(error.value)
            assert said.startswith(f"Dataframe 'rates': {directory / '_data' / 'rates.parquet'} could not be read as parquet")
            assert "the format its ending, .parquet, says" in said
            assert 'format = "parquet", "csv", "jsonl" or "ipc"' in said
            assert "A file that is not a table is declared under [files], not [dataframes]." in said
            assert "PAR1" not in said
            assert error.value.format == "parquet"

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
                    "read_options": {"separator": ";", "schema_overrides": {"zip": "String"}, "null_values": ["NA", ""], "skip_rows": 1},
                },
                "typed": {"path": "./_data/typed.ndjson", "read_options": {"schema_overrides": {"id": "String"}, "infer_schema_length": 50}},
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
        _write(RATES[:2], directory / "_data" / "ipc" / "year=2024" / "p.arrow")
        _write(RATES[2:], directory / "_data" / "ipc" / "year=2025" / "p.arrow")
        con = duckdb.connect(str(directory / "_data" / "local.duckdb"))
        con.sql("create table bounds as select * from (values ('2024-01-01', 4.0), ('2024-01-03', 4.5)) t(d, cap)")
        con.close()
        return directory

    def test_each_format_is_duckdbs_reader_of_it(self, pipeline):
        root = (pipeline / "_data").as_posix()
        assert data.ref("rates", project_dir=pipeline) == f"read_parquet('{root}/rates.parquet')"
        assert data.ref("flat", project_dir=pipeline) == (
            f"read_csv('{root}/flat.csv.gz', delim = ',', header = true, hive_partitioning = false)"
        )
        assert data.ref("tabs", project_dir=pipeline) == (
            f"read_csv('{root}/tabs.tsv', delim = '\t', header = true, hive_partitioning = false)"
        )
        assert data.ref("vendor", project_dir=pipeline) == (
            f"read_csv('{root}/vendor.txt', delim = ';', header = true, types = {{'zip': 'VARCHAR'}}, "
            f"nullstr = ['NA', ''], skip = 1, hive_partitioning = false)"
        )
        assert data.ref("events", project_dir=pipeline) == (
            f"read_json('{root}/events.jsonl.gz', format = 'newline_delimited', hive_partitioning = false)"
        )
        assert data.ref("typed", project_dir=pipeline) == (
            f"(select * replace (cast(\"id\" as VARCHAR) as \"id\") from read_json('{root}/typed.ndjson', "
            f"format = 'newline_delimited', hive_partitioning = false, sample_size = 50))"
        )
        with pytest.raises(ValueError, match="is an Arrow IPC file, which DuckDB reads with no function of its own"):
            data.ref("ipc", project_dir=pipeline)

    @pytest.mark.parametrize("name", ["rates", "flat", "tabs", "events", "vendor", "typed", "ipc"])
    def test_sql_reads_what_load_reads(self, pipeline, name):
        loaded = data.load(name, project_dir=pipeline).collect()
        queried = data.sql(f"select * from {{{name}}}", project_dir=pipeline).collect()
        assert queried.columns == loaded.columns
        assert queried.height == loaded.height
        if name == "vendor":
            assert queried["zip"].to_list() == loaded["zip"].to_list() == ["00123", None]
        if name == "typed":
            assert queried.schema["id"] == loaded.schema["id"] == pl.String

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
