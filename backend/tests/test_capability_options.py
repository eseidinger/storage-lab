import pytest
from pydantic import ValidationError

from storage_lab.schemas import CapabilityOptions


def test_capability_options_validate_bounds_and_fields():
    assert CapabilityOptions(vector_size=768, distance="Dot").model_dump(exclude_none=True) == {
        "vector_size": 768, "distance": "Dot"}
    for values in ({"vector_size": 0}, {"distance": "Wrong"}, {"stream_max_bytes": 1},
                   {"stream_max_bytes": 10737418241}, {"unexpected": True}):
        with pytest.raises(ValidationError):
            CapabilityOptions.model_validate(values)
