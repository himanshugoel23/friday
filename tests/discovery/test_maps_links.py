import pytest

from friday.discovery.geo import is_indian_mobile, is_toll_free, names_match, phone_key
from friday.discovery.maps_links import is_maps_link, parse_maps_link


@pytest.mark.parametrize(
    "url,lat,query",
    [
        (
            "https://www.google.com/maps/place/Looks+Salon/@12.9719,77.6412,17z/data=x",
            12.9719,
            "Looks Salon",
        ),
        ("https://maps.google.com/?q=12.97,77.64", 12.97, None),
        ("https://www.google.com/maps/search/?api=1&query=18.5,73.8", 18.5, None),
        ("https://www.google.com/maps/dir/?api=1&destination=24.5,73.7", 24.5, None),
        ("https://www.google.com/maps/place/X/data=!3d12.5!4d77.5", 12.5, "X"),
        ("geo:12.1,77.2", 12.1, None),
    ],
)
def test_parse_points(url, lat, query):
    p = parse_maps_link(url)
    assert p.point.lat == lat and p.query == query


def test_parse_queries_and_short():
    assert (
        parse_maps_link("https://www.google.com/maps/search/?api=1&query=Looks+Salon").query
        == "Looks Salon"
    )
    assert parse_maps_link("https://www.google.com/maps/place/Looks+Salon").query == "Looks Salon"
    assert parse_maps_link("https://maps.app.goo.gl/xyz").is_short
    assert parse_maps_link("https://example.com/?q=1,2") is None
    assert is_maps_link("https://maps.app.goo.gl/xyz") and not is_maps_link("hello")


def test_phone_helpers():
    assert phone_key("+91 1800 000 121") == phone_key("1800000121")
    assert phone_key("09876543210") == phone_key("+919876543210") == "9876543210"
    assert is_indian_mobile("+919000011111") and not is_indian_mobile("+918040000001")
    assert (
        is_toll_free("1800-202-6161") and is_toll_free("121") and not is_toll_free("+918040000001")
    )
    assert names_match("Looks Salon", "Looks Unisex Salon") and not names_match(
        "Looks", "Frosty Air"
    )
