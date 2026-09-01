from depictio.api.v1.services.notebook_export.names import RESERVED_NAMES, NameAllocator, slug


def test_slug_normalises_titles():
    assert slug("Bill Shape — Length vs Depth") == "bill_shape_length_vs_depth"
    assert slug("Espèce (bill > 50 mm)") == "espece_bill_50_mm"
    assert slug("2024 season") == "item_2024_season"
    assert slug("") == "item"
    assert slug(None, fallback="dc") == "dc"
    assert len(slug("x" * 100)) <= 40


def test_allocator_dedupes_and_avoids_reserved():
    names = NameAllocator()
    assert names.claim("fig", "Bill shape") == "fig_bill_shape"
    assert names.claim("fig", "Bill shape") == "fig_bill_shape_2"
    assert names.claim("fig", "bill-shape") == "fig_bill_shape_3"
    # A bare hint that collides with a reserved name is suffixed.
    assert names.claim("", "df") == "df_2"
    assert names.claim("", "print") == "print_2"


def test_reserved_covers_notebook_scaffolding_and_code_mode_globals():
    for name in ("mo", "pl", "px", "go", "pd", "np", "df", "fig", "client", "depictio_state"):
        assert name in RESERVED_NAMES
