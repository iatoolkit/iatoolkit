"""BL-034 R9: every column that holds who someone is says what erasing them does."""

import pytest

from iatoolkit.repositories.models import Base
from iatoolkit.services.privacy import personal_data


def test_every_personal_looking_column_is_declared():
    missing = personal_data.undeclared_columns(Base.metadata)
    assert missing == [], (
        "Declare these columns in iatoolkit/services/privacy/personal_data.py "
        f"(or the extension's registry): {missing}")


def test_declarations_name_real_columns():
    assert personal_data.unknown_declarations(Base.metadata) == []


def test_keep_needs_a_reason_and_retention_needs_a_date():
    with pytest.raises(ValueError):
        personal_data.PersonalColumn("t", "c", personal_data.KEEP)
    with pytest.raises(ValueError):
        personal_data.PersonalColumn("t", "c", personal_data.DELETE, retention="conversations")
    with pytest.raises(ValueError):
        personal_data.PersonalColumn("t", "c", "shred")
