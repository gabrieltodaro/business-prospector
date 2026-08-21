import pytest

from business_prospector.application.config import ProspectingConfig


def test_filter_defaults_are_explicit() -> None:
    config = ProspectingConfig()
    assert (config.minimum_rating, config.minimum_reviews) == (4.7, 40)
    assert (config.target_leads, config.max_businesses, config.minimum_website_issues) == (10, 25, 2)
    assert config.first_website.compatible_category_groups == (("dentist", "dental_clinic"),)


def test_rejects_inconsistent_limits() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        ProspectingConfig(target_leads=26, max_businesses=25)
