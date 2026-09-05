"""Pydantic models, generated from the one contract declaration.

Every model here is built by :func:`pydantic.create_model` from a
:class:`~apps.api.contracts.spec.ModelSpec`. None is written out by hand, and
that is the design rather than a shortcut. A hand-written Pydantic layer would
be a second description of the same contract, and the two would agree on the
day they were written and disagree on some later day, in one field, quietly -
which for a request contract means an accepted field somebody meant to refuse.

The generation enforces the §6 requirements uniformly, so none of them can be
forgotten on one model:

- ``extra="forbid"`` on every model, request and response alike.
- Every string bounded, and checked for control characters even when it has no
  pattern - rejected, not stripped, because stripping makes two different
  values equal and a value carrying an escape sequence was constructed on
  purpose.
- Identifiers and digests as constrained strings rather than ``UUID`` and
  bytes. ``pydantic``'s ``UUID`` accepts braces, URNs, uppercase and a bare
  32-character run and normalises them, so a value that arrived malformed
  would be silently repaired and serialised back in a different form than it
  came. A pattern refuses it instead.
- Governed enums as ``Literal`` over the vocabulary, never bare ``str``.
- No ``dict[str, Any]`` anywhere: every object-valued field names a model.

This module imports Pydantic, so it is part of the framework-bound half of
:mod:`apps.api` and is imported by no framework-free module.
``TestGeneratedPydanticLayer`` in :mod:`tests.unit.api.test_contracts` asserts
that the generation covers every entry in
:data:`~apps.api.contracts.spec.MODELS`, forbids extra fields and never falls
back to an untyped mapping. It runs where Pydantic cannot be imported, by
reading this file's declarations rather than executing them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from apps.api.contracts.spec import MODELS, ModelSpec, FieldSpec
from apps.api.contracts.validate import contains_control_character

__all__ = ["MODEL_TYPES", "model_type", "rebuild_models"]

_STRICT = ConfigDict(extra="forbid", strict=False, frozen=True,
                     validate_assignment=True)

_UUID_PATTERN = (r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                 r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class _StrictModel(BaseModel):
    """The base every generated model shares.

    Carries the configuration and the one validator that has to apply to every
    string in the system regardless of which field it is.
    """

    model_config = _STRICT

    @field_validator("*", mode="after")
    @classmethod
    def _reject_control_characters(cls, value: Any) -> Any:
        """Refuse control characters at any depth, in any string field.

        Runs after each field's own validation, over strings and over the
        strings inside lists. A per-field pattern would cover most of them and
        miss the ones whose pattern is permissive by necessity - a phenotype
        token, a display name, an error message - which are exactly the fields
        whose values reach a rendered document.
        """
        if isinstance(value, str):
            if contains_control_character(value):
                raise ValueError("control characters are not accepted")
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and contains_control_character(item):
                    raise ValueError("control characters are not accepted")
        return value


def _scalar_annotation(kind: str, spec: FieldSpec, *,
                       pattern: Optional[str] = None,
                       max_length: Optional[int] = None,
                       enum_values: Tuple[str, ...] = ()) -> Any:
    """The annotation for one scalar, field or array item."""
    if kind == "enum":
        return Literal[tuple(enum_values)]  # type: ignore[valid-type]
    if kind == "boolean":
        return bool
    if kind == "integer":
        return int
    return str


def _constraints(field: FieldSpec) -> Dict[str, Any]:
    """The ``Field()`` keyword arguments for one field's own constraints."""
    constraints: Dict[str, Any] = {}
    if field.kind == "string":
        if field.pattern:
            constraints["pattern"] = field.pattern
        if field.min_length is not None:
            constraints["min_length"] = field.min_length
        if field.max_length is not None:
            constraints["max_length"] = field.max_length
    elif field.kind == "uuid":
        constraints["pattern"] = _UUID_PATTERN
        constraints["max_length"] = 36
    elif field.kind == "digest":
        constraints["pattern"] = _DIGEST_PATTERN
        constraints["max_length"] = 71
    elif field.kind == "integer":
        if field.minimum is not None:
            constraints["ge"] = field.minimum
        if field.maximum is not None:
            constraints["le"] = field.maximum
    elif field.kind == "array":
        if field.min_items is not None:
            constraints["min_length"] = field.min_items
        if field.max_items is not None:
            constraints["max_length"] = field.max_items
    if field.description:
        constraints["description"] = field.description
    return constraints


def _annotation(field: FieldSpec, built: Dict[str, Type[BaseModel]]) -> Any:
    if field.kind == "object":
        annotation: Any = built[field.model]
    elif field.kind == "array":
        if field.item_model:
            item: Any = built[field.item_model]
        else:
            item = _scalar_annotation(
                field.item_kind or "string", field,
                pattern=field.item_pattern, max_length=field.item_max_length,
                enum_values=field.item_enum_values)
            if field.item_kind in ("uuid", "digest") or field.item_pattern \
                    or field.item_max_length is not None:
                # Item constraints ride on the item annotation rather than the
                # list's, so a bad element is reported at its own index.
                from typing import Annotated
                item_field = Field(
                    pattern=(_UUID_PATTERN if field.item_kind == "uuid"
                             else _DIGEST_PATTERN
                             if field.item_kind == "digest"
                             else field.item_pattern),
                    max_length=(36 if field.item_kind == "uuid"
                                else 71 if field.item_kind == "digest"
                                else field.item_max_length))
                item = Annotated[item, item_field]
        annotation = List[item]  # type: ignore[valid-type]
    else:
        annotation = _scalar_annotation(
            field.kind, field, pattern=field.pattern,
            max_length=field.max_length, enum_values=field.enum_values)

    if field.nullable:
        annotation = Optional[annotation]
    return annotation


def _build(model: ModelSpec, built: Dict[str, Type[BaseModel]]
           ) -> Type[BaseModel]:
    definitions: Dict[str, Any] = {}
    for field in model.fields:
        annotation = _annotation(field, built)
        constraints = _constraints(field)
        if field.required and not field.nullable:
            default: Any = ...
        elif field.required:
            default = ...
        else:
            default = None
        definitions[field.name] = (annotation,
                                   Field(default, **constraints))
    return create_model(  # type: ignore[call-overload]
        model.name, __base__=_StrictModel, __doc__=model.description,
        **definitions)


def _dependency_order() -> Tuple[ModelSpec, ...]:
    """Models sorted so every referenced model is built before its user.

    A topological sort rather than a fixed list: the contract declares which
    models reference which, and maintaining a second hand-ordered list would
    be one more thing to forget when a field is added.
    """
    remaining = dict(MODELS)
    ordered: list = []
    placed: set = set()
    while remaining:
        progressed = False
        for name in sorted(remaining):
            model = remaining[name]
            needs = {field.model or field.item_model for field in model.fields
                     if field.model or field.item_model}
            if needs <= placed:
                ordered.append(model)
                placed.add(name)
                del remaining[name]
                progressed = True
        if not progressed:  # pragma: no cover - defensive
            raise ValueError(
                "the contract models reference each other in a cycle: "
                + ", ".join(sorted(remaining)))
    return tuple(ordered)


def rebuild_models() -> Dict[str, Type[BaseModel]]:
    """Generate every model. Called once at import; re-callable in tests."""
    built: Dict[str, Type[BaseModel]] = {}
    for model in _dependency_order():
        built[model.name] = _build(model, built)
    return built


MODEL_TYPES: Dict[str, Type[BaseModel]] = rebuild_models()


def model_type(name: str) -> Type[BaseModel]:
    """The generated model class for one contract model name."""
    try:
        return MODEL_TYPES[name]
    except KeyError:  # pragma: no cover - defensive
        raise KeyError("no contract model named %r" % name) from None
