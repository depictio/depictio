"""The JSON encoder skips the per-element recursion for lists that need none."""

from __future__ import annotations

import json
import math

from bson import ObjectId

from depictio.api.v1.json_response import CustomJSONResponse, custom_jsonable_encoder


def test_plain_columns_come_back_untouched() -> None:
    frame = {"s": ["a", "b", None], "n": [1, 2, 3], "x": [0.5, None, 2.0], "f": [True, False]}
    assert custom_jsonable_encoder(frame) == frame


def test_plain_list_is_not_copied() -> None:
    column = ["a"] * 1000
    assert custom_jsonable_encoder(column) is column


def test_nan_and_inf_still_become_null() -> None:
    assert custom_jsonable_encoder([1.0, math.nan, math.inf, 2.0]) == [1.0, None, None, 2.0]
    assert custom_jsonable_encoder({"x": [-math.inf, 1.5]}) == {"x": [None, 1.5]}


def test_huge_ints_do_not_overflow_the_finite_check() -> None:
    assert custom_jsonable_encoder([10**400, 1]) == [10**400, 1]


def test_object_ids_in_a_list_are_still_stringified() -> None:
    oid = ObjectId()
    assert custom_jsonable_encoder([oid, "a"]) == [str(oid), "a"]


def test_mixed_nested_content_is_still_encoded() -> None:
    oid = ObjectId()
    assert custom_jsonable_encoder({"rows": [{"id": oid, "v": [math.nan]}]}) == {
        "rows": [{"id": str(oid), "v": [None]}]
    }


def test_response_body_is_valid_json() -> None:
    body = CustomJSONResponse({"v": [1.0, math.nan], "s": ["a"]}).body
    assert json.loads(body) == {"v": [1.0, None], "s": ["a"]}
