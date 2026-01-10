import pytest

from cmdorc.exceptions import VariableResolutionError
from cmdorc.runtime_vars import resolve_double_brace_vars


# ---------------------------------------------------------
# Basic replacements
# ---------------------------------------------------------
def test_simple_replacement():
    vars_dict = {"a": "hello"}
    assert resolve_double_brace_vars("{{ a }}", vars_dict) == "hello"


def test_simple_replacement_no_spaces():
    vars_dict = {"a": "hello"}
    assert resolve_double_brace_vars("{{a}}", vars_dict) == "hello"


def test_replacement_with_surrounding_text():
    vars_dict = {"name": "world"}
    assert resolve_double_brace_vars("hello {{ name }}!", vars_dict) == "hello world!"


# ---------------------------------------------------------
# Whitespace tolerance
# ---------------------------------------------------------
def test_internal_whitespace():
    vars_dict = {"var_x": "value"}
    assert resolve_double_brace_vars("{{   var_x   }}", vars_dict) == "value"


# ---------------------------------------------------------
# Missing variables
# ---------------------------------------------------------
def test_missing_variable_raises():
    vars_dict = {"a": "1"}
    with pytest.raises(VariableResolutionError):
        resolve_double_brace_vars("{{ missing }}", vars_dict)


# ---------------------------------------------------------
# Nested resolution
# ---------------------------------------------------------
def test_nested_resolution():
    vars_dict = {
        "a": "hello",
        "b": "{{ a }} world",
    }
    assert resolve_double_brace_vars("{{ b }}", vars_dict) == "hello world"


def test_multi_level_nested():
    vars_dict = {
        "a": "foo",
        "b": "{{ a }} bar",
        "c": "{{ b }} baz",
    }
    assert resolve_double_brace_vars("{{ c }}", vars_dict) == "foo bar baz"


# ---------------------------------------------------------
# No modification of single braces
# ---------------------------------------------------------
def test_single_braces_are_preserved():
    vars_dict = {"x": "ignored"}
    assert resolve_double_brace_vars("value is {x}", vars_dict) == "value is {x}"


def test_json_like_braces_are_preserved():
    vars_dict = {"something": "ignored"}
    input_str = '{"key": "{not_a_template}"}'
    assert resolve_double_brace_vars(input_str, vars_dict) == input_str


# ---------------------------------------------------------
# Multiple instances
# ---------------------------------------------------------
def test_multiple_vars():
    vars_dict = {"x": "1", "y": "2"}
    assert resolve_double_brace_vars("{{ x }} + {{ y }}", vars_dict) == "1 + 2"


def test_mixed_text_and_vars():
    vars_dict = {"x": "hi", "y": "there"}
    assert resolve_double_brace_vars("Say {{ x }} to {{ y }}!", vars_dict) == "Say hi to there!"


# ---------------------------------------------------------
# Recursive substitution inside string
# ---------------------------------------------------------
def test_value_that_generates_more_placeholders():
    vars_dict = {
        "a": "{{ b }}",
        "b": "x",
    }
    assert resolve_double_brace_vars("{{ a }}", vars_dict) == "x"


# ---------------------------------------------------------
# No-op input
# ---------------------------------------------------------
def test_no_placeholders():
    assert resolve_double_brace_vars("plain text", {"a": "1"}) == "plain text"


# ---------------------------------------------------------
# Infinite loop / unresolved
# ---------------------------------------------------------
def test_unresolved_after_max_depth_raises():
    # Variable refers to itself -> infinite loop
    vars_dict = {"a": "{{ a }}"}
    with pytest.raises(VariableResolutionError):
        resolve_double_brace_vars("{{ a }}", vars_dict)


def test_unresolvable_nested_after_max_depth_raises():
    # 'a' resolves to something containing unresolved placeholder
    vars_dict = {
        "a": "{{ b }}",
        # missing b
    }
    with pytest.raises(VariableResolutionError):
        resolve_double_brace_vars("{{ a }}", vars_dict)
