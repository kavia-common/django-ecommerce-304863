import pytest


@pytest.mark.django_db
def test_products_public_list_only_active(api_client, item_factory):
    active = item_factory(is_active=True, title="Active A")
    inactive = item_factory(is_active=False, title="Inactive B")

    resp = api_client.get("/api/products/")
    assert resp.status_code == 200
    data = resp.json()
    ids = {p["id"] for p in data}
    assert active.id in ids
    assert inactive.id not in ids


@pytest.mark.django_db
def test_products_admin_can_see_inactive_on_list(
    api_client, item_factory, auth_headers_for_admin
):
    active = item_factory(is_active=True)
    inactive = item_factory(is_active=False)

    resp = api_client.get("/api/products/", **auth_headers_for_admin)
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert active.id in ids
    assert inactive.id in ids


@pytest.mark.django_db
def test_products_search_filter_ordering(api_client, item_factory):
    i1 = item_factory(title="Blue Shirt", price=10.0, sku="SKU-BLUE-1", is_active=True)
    i2 = item_factory(title="Red Shirt", price=25.0, sku="SKU-RED-1", is_active=True)
    _i3 = item_factory(
        title="Hidden Shirt", price=99.0, sku="SKU-HIDDEN-1", is_active=False
    )

    # search= should match title (case-insensitive)
    resp = api_client.get("/api/products/?search=blue")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert i1.id in ids
    assert i2.id not in ids

    # filter by sku should work
    resp = api_client.get("/api/products/?sku=SKU-RED-1")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == i2.id

    # ordering by -price
    resp = api_client.get("/api/products/?ordering=-price")
    assert resp.status_code == 200
    items = resp.json()
    assert items[0]["price"] >= items[1]["price"]


@pytest.mark.django_db
def test_products_write_requires_admin(
    api_client,
    item_factory,
    make_test_image_file,
    auth_headers_for_user,
    auth_headers_for_admin,
):
    # Non-admin cannot create
    payload = {
        "title": "New Product",
        "price": 12.5,
        "discount_price": None,
        "category": "S",
        "label": "P",
        "slug": "new-product",
        "description": "desc",
        "sku": "SKU-NEW-1",
        "is_active": True,
        "low_stock_threshold": 0,
        "stock_on_hand": 5,
        "stock_reserved": 0,
        "image": make_test_image_file("p.png"),
    }
    resp = api_client.post(
        "/api/products/", payload, format="multipart", **auth_headers_for_user
    )
    assert resp.status_code in (403, 401)

    # Admin can create
    resp = api_client.post(
        "/api/products/", payload, format="multipart", **auth_headers_for_admin
    )
    assert resp.status_code == 201, resp.content
    created = resp.json()
    assert created["title"] == "New Product"
    created_id = created["id"]

    # Admin can update
    patch = api_client.patch(
        f"/api/products/{created_id}/",
        {"price": 99.0},
        format="json",
        **auth_headers_for_admin,
    )
    assert patch.status_code == 200
    assert patch.json()["price"] == 99.0

    # Admin can delete
    delete = api_client.delete(f"/api/products/{created_id}/", **auth_headers_for_admin)
    assert delete.status_code == 204


@pytest.mark.django_db
def test_products_public_retrieve_blocks_inactive(api_client, item_factory):
    inactive = item_factory(is_active=False)
    resp = api_client.get(f"/api/products/{inactive.id}/")
    assert resp.status_code == 404
