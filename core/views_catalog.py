"""Catalog-facing views (home, product listing).

These views keep Stripe/checkout/payment flows untouched by separating concerns.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.generic import ListView

from .forms_catalog import CatalogFilterForm
from .models import Item


class CatalogListView(ListView):
    """Product listing with search, filters and sorting.

    - Search: title/description
    - Filters: category, min/max price
    - Sort: price/title/relevance
    """

    model = Item
    paginate_by = 12
    template_name = "catalog/list.html"
    context_object_name = "items"

    def get_queryset(self):
        """Return the filtered/sorted queryset."""
        # Only select fields we need + avoid heavy per-row loads.
        qs = (
            Item.objects.all()
            .only(
                "id",
                "title",
                "price",
                "discount_price",
                "category",
                "label",
                "slug",
                "image",
                "description",
            )
        )

        self.filter_form = CatalogFilterForm(self.request.GET or None)
        if not self.filter_form.is_valid():
            # Invalid params: show unfiltered list but still render form errors.
            return qs.order_by("-id")

        q = (self.filter_form.cleaned_data.get("q") or "").strip()
        category = (self.filter_form.cleaned_data.get("category") or "").strip()
        price_min = self.filter_form.cleaned_data.get("price_min")
        price_max = self.filter_form.cleaned_data.get("price_max")
        sort = (self.filter_form.cleaned_data.get("sort") or "relevance").strip()

        if q:
            # Relevance is approximated with ordering by id after filtering.
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

        if category:
            qs = qs.filter(category=category)

        # Price filter: treat discount_price as effective when present by filtering both.
        if price_min is not None:
            qs = qs.filter(Q(discount_price__gte=price_min) | Q(discount_price__isnull=True, price__gte=price_min))
        if price_max is not None:
            qs = qs.filter(Q(discount_price__lte=price_max) | Q(discount_price__isnull=True, price__lte=price_max))

        if sort == "price_asc":
            qs = qs.order_by("discount_price", "price", "id")
        elif sort == "price_desc":
            qs = qs.order_by("-discount_price", "-price", "-id")
        elif sort == "title_asc":
            qs = qs.order_by("title", "id")
        elif sort == "title_desc":
            qs = qs.order_by("-title", "-id")
        else:
            # "relevance": if q exists keep default (-id) after filtering, else newest
            qs = qs.order_by("-id")

        return qs

    def get_context_data(self, **kwargs):
        """Attach filter form and current query string state."""
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = getattr(self, "filter_form", CatalogFilterForm(self.request.GET or None))
        return ctx


@method_decorator(cache_page(60), name="dispatch")
class HomeLandingView(ListView):
    """Modern landing page: hero + curated sections.

    Safe caching (60s): products are public and change rarely; cart/auth elements are in navbar and not cached here.
    """

    model = Item
    paginate_by = 8
    template_name = "home_modern.html"
    context_object_name = "items"

    def get_queryset(self):
        """Return newest items for the home grid."""
        return (
            Item.objects.all()
            .only("id", "title", "price", "discount_price", "category", "label", "slug", "image")
            .order_by("-id")
        )

    def get_context_data(self, **kwargs):
        """Add 'featured' subsets for additional sections."""
        ctx = super().get_context_data(**kwargs)
        # Simple “featured” sections without extra schema: reuse newest slices.
        # Querysets are evaluated lazily; keep slices small.
        ctx["featured_items"] = ctx["items"][:4]
        ctx["new_arrivals"] = ctx["items"]
        return ctx
