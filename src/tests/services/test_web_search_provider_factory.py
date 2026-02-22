import pytest
from unittest.mock import MagicMock

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services.web_search.provider_factory import WebSearchProviderFactory
from iatoolkit.services.web_search.providers.brave_provider import BraveWebSearchProvider


def test_get_provider_brave():
    brave = MagicMock(spec=BraveWebSearchProvider)
    factory = WebSearchProviderFactory(brave_provider=brave)

    assert factory.get_provider("brave") is brave


def test_get_provider_unknown_raises():
    brave = MagicMock(spec=BraveWebSearchProvider)
    factory = WebSearchProviderFactory(brave_provider=brave)

    with pytest.raises(IAToolkitException) as exc:
        factory.get_provider("unknown")

    assert exc.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
