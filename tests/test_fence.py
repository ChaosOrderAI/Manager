from app.services.fence import haversine_m, inside_fence
from app.models.entities import Fence


def test_haversine():
    d = haversine_m(39.9, 116.4, 39.91, 116.4)
    assert 1000 < d < 1200  # ~1.11km per 0.01 deg lat


def test_circle_fence():
    f = Fence(shape_type="circle", center_lat=39.9, center_lng=116.4,
              radius_m=500, buffer_m=0)
    assert inside_fence(f, 39.9, 116.4)
    assert not inside_fence(f, 39.95, 116.4)


def test_polygon_fence():
    poly = "[[[116.3,39.8],[116.5,39.8],[116.5,40.0],[116.3,40.0],[116.3,39.8]]]"
    f = Fence(shape_type="polygon", polygon=poly, buffer_m=0)
    assert inside_fence(f, 39.9, 116.4)
    assert not inside_fence(f, 40.1, 116.4)
