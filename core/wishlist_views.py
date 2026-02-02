"""Wishlist views for template-based storefront.

These views are used by regular browser flows (session auth), separate from DRF /api/wishlist.
They are intentionally minimal to avoid changing existing storefront behavior.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Item, WishlistEntry


# PUBLIC_INTERFACE
@login_required
def wishlist_toggle(request, slug: str):
    """Toggle wishlist state for the given item slug for the authenticated user.

    POST-only in intended use, but we accept GET as a convenience because existing
    storefront uses anchor links for cart actions.

    Redirects back to `next` if provided, otherwise to product detail page.
    """
    item = get_object_or_404(Item, slug=slug)
    next_url = request.GET.get("next") or request.POST.get("next") or item.get_absolute_url()

    entry = WishlistEntry.objects.filter(user=request.user, item=item).first()
    if entry:
        entry.delete()
        messages.info(request, "Removed from your wishlist.")
    else:
        # Uniqueness constraint prevents duplicates; create is safe.
        WishlistEntry.objects.get_or_create(user=request.user, item=item)
        messages.success(request, "Added to your wishlist.")

    return redirect(next_url)


# PUBLIC_INTERFACE
@login_required
def wishlist_list(request):
    """Render the authenticated user's wishlist page."""
    entries = (
        WishlistEntry.objects.filter(user=request.user)
        .select_related("item")
        .order_by("-created_at", "id")
    )
    items = [e.item for e in entries]
    return render(request, "wishlist.html", {"items": items, "count": len(items)})
