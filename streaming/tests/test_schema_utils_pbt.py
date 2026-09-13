import os
import sys
import pytest
from hypothesis import given, strategies as st

# Asegurar que streaming/src/jobs esté en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "jobs")))

from schema_utils import avro_type_to_flink_sql_type, build_port_filter_sql

PRIMITIVE_MAPPINGS = {
    "string": "STRING",
    "int": "INT",
    "long": "BIGINT",
    "float": "FLOAT",
    "double": "DOUBLE",
    "boolean": "BOOLEAN",
    "bytes": "BYTES",
}


@given(st.sampled_from(list(PRIMITIVE_MAPPINGS.keys())))
def test_avro_type_to_flink_sql_type_primitive_mappings(avro_type):
    assert avro_type_to_flink_sql_type(avro_type) == PRIMITIVE_MAPPINGS[avro_type]


@given(
    st.text(min_size=1, max_size=30).filter(
        lambda s: s not in PRIMITIVE_MAPPINGS and not isinstance(s, list)
    )
)
def test_avro_type_to_flink_sql_type_unknown_fallback(unknown_type):
    assert avro_type_to_flink_sql_type(unknown_type) == "STRING"


@given(st.sampled_from(list(PRIMITIVE_MAPPINGS.keys())))
def test_avro_type_to_flink_sql_type_nullable_unions(non_null_type):
    union = ["null", non_null_type]
    assert avro_type_to_flink_sql_type(union) == PRIMITIVE_MAPPINGS[non_null_type]


@given(st.just(["null"]))
def test_avro_type_to_flink_sql_type_null_only_union(union):
    assert avro_type_to_flink_sql_type(union) == "STRING"


@given(st.just([]))
def test_avro_type_to_flink_sql_type_empty_union(union):
    assert avro_type_to_flink_sql_type(union) == "STRING"


_port_name = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=1,
    max_size=20,
)
_alias = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=1,
    max_size=10,
)

_port_dict = st.fixed_dictionaries(
    {
        "name": _port_name,
        "aliases": st.lists(_alias, min_size=1, max_size=5),
    }
)


@given(st.lists(_port_dict, min_size=1, max_size=10))
def test_build_port_filter_sql_clause_count_and_syntax(ports):
    result = build_port_filter_sql(ports)

    total_aliases = sum(len(p["aliases"]) for p in ports)
    assert result.count("LIKE") == total_aliases

    for p in ports:
        for alias in p["aliases"]:
            assert f"UPPER(destination) LIKE '%{alias}%'" in result

    if total_aliases > 1:
        assert " OR " in result


def test_build_port_filter_sql_empty_list_raises_value_error():
    with pytest.raises(ValueError, match="TARGET_PORTS está vacío"):
        build_port_filter_sql([])
