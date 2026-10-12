"""The reference grammar: one parser from text to a structured address.

An asset is addressed by a *reference*::

    [registry/][scope/]pipeline : [kind/]name [#part] [@rev]

Each separator asks a different question, read left to right:

``/``
    One level down: registry, then scope, then pipeline; kind, then name.
``:``
    "From this pipeline, take...". Everything before it says *which
    pipeline*; everything after says *what inside it*. A reference with no
    colon is local: it names an asset of the pipeline you are in.
``#``
    "...this part of it": a column of a dataframe, a file inside a model.
``@``
    "...at this revision": a version of the asset.

The kind defaults to ``dataframe``, because data is what gets passed
around; every other kind says what it is. So ``treasury_rates`` is a
dataframe, ``chart/gdp`` a chart and ``model/rate_forecaster`` a model.

This module only *parses and formats*. It accepts the whole grammar, and
knows nothing about which parts of it can be resolved yet; that is
:mod:`chartbook.resolve`'s business. Everything inside ChartBook should
carry an :class:`AssetRef`, not a string, once a reference has been read.

The specification, with the reasoning and the prior art, is
``docs_src/design/references.md``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional, Union

from chartbook.identity import (
    ID_COMPONENT_PATTERN,
    looks_like_registry,
    split_registry,
)

#: Every kind of asset, in the singular, as it is written in a reference.
#: The first is the default. ``model`` is recognized so that references to
#: models parse; nothing resolves one yet.
KINDS = ("dataframe", "chart", "notebook", "note", "model")

#: The kind a reference names when it does not say.
DEFAULT_KIND = "dataframe"

#: The ``chartbook.toml`` table that declares assets of each kind.
KIND_TABLES = {
    "dataframe": "dataframes",
    "chart": "charts",
    "notebook": "notebooks",
    "note": "notes",
    "model": "models",
}

# A part may be a path inside the asset, so it may contain "/"
_PART_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
# A revision may be an algorithm-qualified hash, so it may contain ":"
_REV_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
# A registry is a host, which may carry a port
_REGISTRY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


class KindMismatchError(ValueError):
    """Raised when a reference names one kind of asset and another was expected.

    Attributes:
        found: The kind the reference names.
        expected: The kind the caller asked for.
    """

    def __init__(self, text: str, found: str, expected: str, hint: str = ""):
        self.found = found
        self.expected = expected
        message = f"Reference {text!r} names a {found}, but a {expected} was expected."
        super().__init__(f"{message} {hint}".strip())


@dataclass(frozen=True, kw_only=True)
class AssetRef:
    """A parsed reference to an asset: the address as named fields.

    This is the form to pass around in code and to write as JSON. The text
    form is for people, command lines and ``chartbook.toml``; ``str()`` of
    an ``AssetRef`` gives it back, and :func:`parse_asset_ref` reads it.

    The fields are in the order they are written. An ``AssetRef`` is checked
    when it is made, so one that exists is well-formed.

    Attributes:
        registry: The registry that resolves the pipeline, if given.
        scope: The pipeline's scope (its organization), if given.
        pipeline: The name of the pipeline that declares the asset, or None
            for a local reference (an asset of the pipeline you are in).
        kind: What kind of asset it is; one of :data:`KINDS`.
        name: The asset's name: its key in its table of ``chartbook.toml``.
        part: A part inside the asset, if one is addressed.
        rev: The revision of the asset, if one is pinned.
    """

    registry: Optional[str] = None
    scope: Optional[str] = None
    pipeline: Optional[str] = None
    kind: str = DEFAULT_KIND
    name: str
    part: Optional[str] = None
    rev: Optional[str] = None

    def __post_init__(self):
        _check_kind(self.kind)
        if not isinstance(self.name, str) or not ID_COMPONENT_PATTERN.match(self.name):
            raise ValueError(
                f"Invalid asset name {self.name!r}. A name is a key of "
                f"chartbook.toml, matching [A-Za-z0-9._-]+."
            )
        for label, value in (("pipeline", self.pipeline), ("scope", self.scope)):
            if value is not None and not ID_COMPONENT_PATTERN.match(value):
                raise ValueError(
                    f"Invalid {label} {value!r} in a reference. Expected a name "
                    f"matching [A-Za-z0-9._-]+."
                )
        if self.scope is not None and self.pipeline is None:
            raise ValueError("A reference with a scope needs a pipeline.")
        if self.registry is not None:
            if self.scope is None:
                raise ValueError(
                    "A reference with a registry needs a scope and a pipeline: "
                    "'registry/scope/pipeline:asset'."
                )
            if not _REGISTRY_PATTERN.match(self.registry) or not looks_like_registry(
                self.registry
            ):
                raise ValueError(
                    f"Invalid registry {self.registry!r} in a reference. A "
                    f"registry is a host name: it contains '.' or ':', or is "
                    f"'localhost'."
                )
        if self.part is not None and not _PART_PATTERN.match(self.part):
            raise ValueError(
                f"Invalid part {self.part!r} after '#' in a reference. A part "
                f"is a name made of letters, digits, '.', '_', '-' and '/'."
            )
        if self.rev is not None and not _REV_PATTERN.match(self.rev):
            raise ValueError(
                f"Invalid revision {self.rev!r} after '@' in a reference. A "
                f"revision is a version name, tag or hash, e.g. '@v3'."
            )

    @property
    def is_local(self) -> bool:
        """True if the reference names no pipeline, so means the current one."""
        return self.pipeline is None

    @property
    def pipeline_id(self) -> Optional[str]:
        """The pipeline's ID, ``scope/name`` or a bare ``name``; None if local."""
        if self.pipeline is None:
            return None
        return f"{self.scope}/{self.pipeline}" if self.scope else self.pipeline

    @property
    def table(self) -> str:
        """The ``chartbook.toml`` table that declares assets of this kind."""
        return KIND_TABLES[self.kind]

    @property
    def local_name(self) -> str:
        """The asset within its pipeline: ``name``, or ``kind/name``."""
        return self.name if self.kind == DEFAULT_KIND else f"{self.kind}/{self.name}"

    def __str__(self) -> str:
        """The canonical text of the reference.

        The default kind is left out, so a dataframe is written without a
        prefix. Parsing the result gives back an equal ``AssetRef``.
        """
        text = self.local_name
        if self.pipeline is not None:
            prefix = self.pipeline_id
            if self.registry:
                prefix = f"{self.registry}/{prefix}"
            text = f"{prefix}:{text}"
        if self.part:
            text += f"#{self.part}"
        if self.rev:
            text += f"@{self.rev}"
        return text

    def to_dict(self) -> dict:
        """The reference as a plain dictionary, for JSON.

        ``kind`` and ``name`` are always present; the other fields only when
        set. Keys are in the order the address is written.
        """
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None or key in ("kind", "name")
        }

    @classmethod
    def from_dict(cls, fields: dict) -> "AssetRef":
        """Build a reference from :meth:`to_dict`'s form, checking it."""
        unknown = set(fields) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown reference fields: {sorted(unknown)}")
        if "name" not in fields:
            raise ValueError("A reference needs a 'name'.")
        return cls(**{k: v for k, v in fields.items() if v is not None})


def _check_kind(kind: str, text: Optional[str] = None) -> str:
    """Validate a kind word, suggesting the singular if a plural was given."""
    if kind in KINDS:
        return kind
    where = f" in reference {text!r}" if text else ""
    hint = ""
    if isinstance(kind, str) and kind.endswith("s") and kind[:-1] in KINDS:
        hint = f" Did you mean {kind[:-1]!r}? Kinds are written in the singular."
    raise ValueError(
        f"Unknown kind {kind!r}{where}. The kinds are: {', '.join(KINDS)}.{hint}"
    )


def _split_asset(text: str, original: str, has_pipeline: bool) -> tuple:
    """Split the asset half of a reference, ``[kind/]name``, into its two parts."""
    segments = text.split("/")
    if len(segments) == 1:
        return None, segments[0]
    if len(segments) == 2:
        first, name = segments
        if first in KINDS:
            return first, name
        plural = first.endswith("s") and first[:-1] in KINDS
        if not has_pipeline and not plural:
            # Most likely scope/pipeline, written where an asset was wanted
            raise ValueError(
                f"Reference {original!r} does not name an asset. With no ':', "
                f"the word before '/' must be a kind ({', '.join(KINDS)}). If "
                f"{text!r} is a pipeline, name an asset in it: '{text}:<asset>'."
            )
        _check_kind(first, original)
    raise ValueError(
        f"Reference {original!r} is not an asset reference. An asset is 'name' "
        f"or 'kind/name'; one in another pipeline is 'scope/pipeline:name'."
    )


def parse_asset_ref(
    text: Union[str, AssetRef], kind: Optional[str] = None
) -> AssetRef:
    """Parse the text of a reference to an asset.

    The whole grammar is accepted. Whether a given reference can be
    *resolved* yet is a separate question, answered by
    :func:`chartbook.resolve.resolve`.

    :param text: The reference, e.g. ``"treasury_rates"``,
        ``"chart/gdp"`` or ``"ftsfr/fed_yield_curve:model/forecaster@v3"``.
        An ``AssetRef`` is checked against *kind* and returned.
    :param kind: The kind the caller expects. A reference that names no kind
        takes this one; a reference that names a different kind is an error.
        When None, a reference that names no kind is a dataframe.
    :returns: The parsed reference.
    :raises KindMismatchError: If the reference names a kind other than *kind*.
    :raises ValueError: If the text does not follow the grammar.
    """
    if kind is not None:
        _check_kind(kind)

    if isinstance(text, AssetRef):
        if kind is not None and text.kind != kind:
            raise KindMismatchError(str(text), text.kind, kind)
        return text

    original = text
    text = text.strip()
    if not text:
        raise ValueError("A reference cannot be empty.")

    # Right to left: the revision, then the part, then pipeline : asset
    rev = None
    if "@" in text:
        text, rev = text.rsplit("@", 1)
        if not _REV_PATTERN.match(rev):
            raise ValueError(
                f"Reference {original!r} has an invalid revision after '@'. "
                f"A revision is a version name, tag or hash, e.g. '@v3'."
            )

    part = None
    if "#" in text:
        text, part = text.split("#", 1)
        if not _PART_PATTERN.match(part):
            raise ValueError(
                f"Reference {original!r} has an invalid part after '#'. A part "
                f"is a name made of letters, digits, '.', '_', '-' and '/'."
            )

    # The asset never contains a colon, so the last one divides the two. (A
    # registry may: localhost:5000/acme/rates:treasury_rates.)
    pipeline_text = None
    if ":" in text:
        pipeline_text, text = text.rsplit(":", 1)

    explicit_kind, name = _split_asset(text, original, pipeline_text is not None)
    if not ID_COMPONENT_PATTERN.match(name):
        raise ValueError(
            f"Invalid asset name {name!r} in reference {original!r}. A name is "
            f"a key of chartbook.toml, matching [A-Za-z0-9._-]+."
        )

    if explicit_kind is None:
        resolved_kind = kind or DEFAULT_KIND
    elif kind is not None and explicit_kind != kind:
        raise KindMismatchError(original, explicit_kind, kind)
    else:
        resolved_kind = explicit_kind

    registry = scope = pipeline = None
    if pipeline_text is not None:
        registry, unqualified = split_registry(pipeline_text)
        components = unqualified.split("/")
        if len(components) > 2 or not all(
            ID_COMPONENT_PATTERN.match(c) for c in components
        ):
            raise ValueError(
                f"Reference {original!r} has an invalid pipeline "
                f"{pipeline_text!r} before the ':'. A pipeline is 'name', "
                f"'scope/name' or 'registry/scope/name'."
            )
        pipeline = components[-1]
        scope = components[0] if len(components) == 2 else None

    return AssetRef(
        registry=registry,
        scope=scope,
        pipeline=pipeline,
        kind=resolved_kind,
        name=name,
        part=part,
        rev=rev,
    )
