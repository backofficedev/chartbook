"""Tests for the reference grammar: ``chartbook.refs``.

The grammar is specified in ``docs_src/design/references.md``. Parsing
accepts all of it; which references *resolve* is tested in
``test_resolve.py``.
"""

import dataclasses
import json

import pytest

from chartbook.refs import (
    DEFAULT_KIND,
    KIND_TABLES,
    KINDS,
    AssetRef,
    KindMismatchError,
    parse_asset_ref,
)

# Every form the specification gives, as (text, the fields it sets)
EXAMPLES = [
    ("treasury_rates", dict(name="treasury_rates")),
    ("chart/yield_curve", dict(kind="chart", name="yield_curve")),
    ("notebook/analysis", dict(kind="notebook", name="analysis")),
    ("note/methodology", dict(kind="note", name="methodology")),
    ("model/rate_forecaster", dict(kind="model", name="rate_forecaster")),
    ("treasury_rates#dgs10", dict(name="treasury_rates", part="dgs10")),
    (
        "model/rate_forecaster#weights/best.pt",
        dict(kind="model", name="rate_forecaster", part="weights/best.pt"),
    ),
    ("model/rate_forecaster@v3", dict(kind="model", name="rate_forecaster", rev="v3")),
    (
        "model/rate_forecaster#config.json@champion",
        dict(kind="model", name="rate_forecaster", part="config.json", rev="champion"),
    ),
    (
        "fed_yield_curve:treasury_rates",
        dict(pipeline="fed_yield_curve", name="treasury_rates"),
    ),
    (
        "ftsfr/fed_yield_curve:treasury_rates",
        dict(scope="ftsfr", pipeline="fed_yield_curve", name="treasury_rates"),
    ),
    (
        "ftsfr/fed_yield_curve:chart/curve_today",
        dict(scope="ftsfr", pipeline="fed_yield_curve", kind="chart", name="curve_today"),
    ),
    (
        "ftsfr/fed_yield_curve:treasury_rates#dgs10@a1b2c3d",
        dict(
            scope="ftsfr",
            pipeline="fed_yield_curve",
            name="treasury_rates",
            part="dgs10",
            rev="a1b2c3d",
        ),
    ),
    (
        "treasury_rates@sha256:7f3a9c",
        dict(name="treasury_rates", rev="sha256:7f3a9c"),
    ),
    (
        "charthub.example/acme/rates:model/forecaster@v3",
        dict(
            registry="charthub.example",
            scope="acme",
            pipeline="rates",
            kind="model",
            name="forecaster",
            rev="v3",
        ),
    ),
    (
        "localhost:5000/acme/rates:treasury_rates",
        dict(
            registry="localhost:5000",
            scope="acme",
            pipeline="rates",
            name="treasury_rates",
        ),
    ),
]


class TestParse:
    @pytest.mark.parametrize("text,fields", EXAMPLES)
    def test_examples(self, text, fields):
        assert parse_asset_ref(text) == AssetRef(**fields)

    @pytest.mark.parametrize("text,fields", EXAMPLES)
    def test_text_round_trips(self, text, fields):
        assert str(parse_asset_ref(text)) == text
        assert parse_asset_ref(str(AssetRef(**fields))) == AssetRef(**fields)

    def test_default_kind_is_dataframe(self):
        assert DEFAULT_KIND == "dataframe"
        assert parse_asset_ref("gdp").kind == "dataframe"

    def test_explicit_default_kind_is_the_same_reference(self):
        assert parse_asset_ref("dataframe/gdp") == parse_asset_ref("gdp")
        assert str(parse_asset_ref("dataframe/gdp")) == "gdp"

    def test_whitespace_is_trimmed(self):
        assert parse_asset_ref("  chart/gdp \n") == AssetRef(kind="chart", name="gdp")

    def test_a_dotted_scope_is_a_scope_not_a_registry(self):
        """Only the first of three components can be a registry."""
        ref = parse_asset_ref("my.group/rates:gdp")
        assert (ref.registry, ref.scope, ref.pipeline) == (None, "my.group", "rates")

    def test_an_asset_may_be_named_like_a_kind(self):
        assert parse_asset_ref("chart") == AssetRef(name="chart")
        assert parse_asset_ref("chart/chart") == AssetRef(kind="chart", name="chart")

    def test_a_parsed_reference_is_returned_as_is(self):
        ref = AssetRef(kind="chart", name="gdp")
        assert parse_asset_ref(ref) is ref


class TestExpectedKind:
    """``kind=`` says what the caller expects."""

    def test_fills_in_when_the_reference_names_no_kind(self):
        assert parse_asset_ref("gdp", kind="chart") == AssetRef(kind="chart", name="gdp")

    def test_agrees_with_the_reference(self):
        assert parse_asset_ref("chart/gdp", kind="chart").kind == "chart"

    def test_disagrees_with_the_reference(self):
        with pytest.raises(KindMismatchError) as excinfo:
            parse_asset_ref("chart/gdp", kind="dataframe")
        assert excinfo.value.found == "chart"
        assert excinfo.value.expected == "dataframe"
        assert "names a chart, but a dataframe was expected" in str(excinfo.value)
        assert isinstance(excinfo.value, ValueError)

    def test_an_explicit_default_kind_is_still_a_kind(self):
        with pytest.raises(KindMismatchError):
            parse_asset_ref("dataframe/gdp", kind="chart")

    def test_is_checked_against_a_parsed_reference(self):
        with pytest.raises(KindMismatchError):
            parse_asset_ref(AssetRef(kind="chart", name="gdp"), kind="note")

    def test_must_itself_be_a_kind(self):
        with pytest.raises(ValueError, match="Unknown kind 'charts'.*Did you mean 'chart'"):
            parse_asset_ref("gdp", kind="charts")


class TestRejected:
    def test_empty(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_asset_ref("   ")

    def test_plural_kind_suggests_the_singular(self):
        with pytest.raises(ValueError, match="Did you mean 'chart'"):
            parse_asset_ref("charts/gdp")
        with pytest.raises(ValueError, match="Did you mean 'model'"):
            parse_asset_ref("acme/rates:models/forecaster")

    def test_unknown_kind_after_a_pipeline(self):
        with pytest.raises(ValueError, match="Unknown kind 'figure'"):
            parse_asset_ref("acme/rates:figure/gdp")

    def test_a_pipeline_where_an_asset_was_wanted(self):
        with pytest.raises(ValueError) as excinfo:
            parse_asset_ref("ftsfr/fed_yield_curve")
        message = str(excinfo.value)
        assert "does not name an asset" in message
        assert "'ftsfr/fed_yield_curve:<asset>'" in message

    @pytest.mark.parametrize(
        "text",
        ["ftsfr/fed_yield_curve/treasury_rates", "acme/rates:chart/gdp/extra"],
    )
    def test_slashes_all_the_way_down(self, text):
        with pytest.raises(ValueError, match="is not an asset reference"):
            parse_asset_ref(text)

    @pytest.mark.parametrize("text", [":gdp", "a/b/c/d:gdp", "x:y:gdp", "two words:gdp"])
    def test_invalid_pipeline(self, text):
        with pytest.raises(ValueError, match="invalid pipeline"):
            parse_asset_ref(text)

    @pytest.mark.parametrize("text", ["two words", "semi;colon", "quo'te", "chart/"])
    def test_invalid_name(self, text):
        with pytest.raises(ValueError, match="Invalid asset name"):
            parse_asset_ref(text)

    @pytest.mark.parametrize("text", ["gdp@", "gdp@two words"])
    def test_invalid_revision(self, text):
        with pytest.raises(ValueError, match="invalid revision"):
            parse_asset_ref(text)

    @pytest.mark.parametrize("text", ["gdp#", "gdp#two words", "gdp#a#b"])
    def test_invalid_part(self, text):
        with pytest.raises(ValueError, match="invalid part"):
            parse_asset_ref(text)


class TestAssetRef:
    def test_is_immutable_and_hashable(self):
        ref = AssetRef(name="gdp")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.name = "other"
        assert {ref: 1}[AssetRef(name="gdp")] == 1

    def test_fields_are_keyword_only(self):
        with pytest.raises(TypeError):
            AssetRef("gdp")

    def test_is_local(self):
        assert AssetRef(name="gdp").is_local
        assert not AssetRef(pipeline="rates", name="gdp").is_local

    def test_pipeline_id(self):
        assert AssetRef(name="gdp").pipeline_id is None
        assert AssetRef(pipeline="rates", name="gdp").pipeline_id == "rates"
        assert AssetRef(scope="acme", pipeline="rates", name="gdp").pipeline_id == (
            "acme/rates"
        )

    def test_table(self):
        assert [AssetRef(kind=kind, name="x").table for kind in KINDS] == [
            "dataframes",
            "charts",
            "notebooks",
            "notes",
            "models",
        ]
        assert set(KIND_TABLES) == set(KINDS)

    def test_local_name(self):
        assert AssetRef(scope="acme", pipeline="rates", name="gdp").local_name == "gdp"
        assert AssetRef(kind="chart", name="gdp", rev="v1").local_name == "chart/gdp"

    @pytest.mark.parametrize(
        "fields,message",
        [
            (dict(name="gdp", kind="charts"), "Did you mean 'chart'"),
            (dict(name="two words"), "Invalid asset name"),
            (dict(name="gdp", scope="acme"), "scope needs a pipeline"),
            (dict(name="gdp", pipeline="a/b"), "Invalid pipeline"),
            (
                dict(name="gdp", registry="charthub.example", pipeline="rates"),
                "registry needs a scope",
            ),
            (
                dict(name="gdp", registry="acme", scope="a", pipeline="rates"),
                "Invalid registry",
            ),
            (dict(name="gdp", part="a#b"), "Invalid part"),
            (dict(name="gdp", rev="two words"), "Invalid revision"),
        ],
    )
    def test_is_checked_when_made(self, fields, message):
        with pytest.raises(ValueError, match=message):
            AssetRef(**fields)


class TestDictForm:
    """The JSON spelling of a reference: named fields, nothing to parse."""

    def test_local_dataframe(self):
        assert AssetRef(name="gdp").to_dict() == {"kind": "dataframe", "name": "gdp"}

    def test_full_reference_keys_are_in_address_order(self):
        ref = parse_asset_ref("charthub.example/acme/rates:model/forecaster#w.pt@v3")
        assert list(ref.to_dict().items()) == [
            ("registry", "charthub.example"),
            ("scope", "acme"),
            ("pipeline", "rates"),
            ("kind", "model"),
            ("name", "forecaster"),
            ("part", "w.pt"),
            ("rev", "v3"),
        ]

    @pytest.mark.parametrize("text,fields", EXAMPLES)
    def test_round_trips_through_json(self, text, fields):
        ref = parse_asset_ref(text)
        assert AssetRef.from_dict(json.loads(json.dumps(ref.to_dict()))) == ref

    def test_kind_may_be_left_out(self):
        assert AssetRef.from_dict({"name": "gdp"}) == AssetRef(name="gdp")

    def test_null_fields_are_the_same_as_absent(self):
        assert AssetRef.from_dict({"name": "gdp", "rev": None, "scope": None}) == (
            AssetRef(name="gdp")
        )

    def test_needs_a_name(self):
        with pytest.raises(ValueError, match="needs a 'name'"):
            AssetRef.from_dict({"kind": "chart"})

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValueError, match=r"Unknown reference fields: \['version'\]"):
            AssetRef.from_dict({"name": "gdp", "version": "v3"})

    def test_is_checked(self):
        with pytest.raises(ValueError, match="Unknown kind"):
            AssetRef.from_dict({"name": "gdp", "kind": "figure"})
