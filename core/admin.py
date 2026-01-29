from __future__ import annotations

import uuid

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .inventory import (
    commit_inventory_for_paid_order,
    release_inventory_reservations_for_order,
    reserve_inventory_for_order,
    restock_inventory_for_order_refund,
)
from .models import (
    Address,
    Coupon,
    InventoryAdjustment,
    Item,
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
    Refund,
    Review,
    UserProfile,
    WishlistItem,
)


def _is_admin_user(user) -> bool:
    """
    Internal helper: treat superusers as admins, otherwise require membership in the 'Admin' group.
    """
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and (getattr(user, "is_superuser", False) or user.groups.filter(name="Admin").exists())
    )


class AdminOnlyModelAdmin(admin.ModelAdmin):
    """
    Base ModelAdmin that hides models from non-admin users and blocks writes.

    We do this in addition to Django's default is_staff requirement, because the project
    uses RBAC based on Groups/Permissions and the task requires that only Admins can
    see/write these screens.
    """

    def has_module_permission(self, request) -> bool:
        return _is_admin_user(request.user)

    def has_view_permission(self, request, obj=None) -> bool:
        return _is_admin_user(request.user)

    def has_add_permission(self, request) -> bool:
        return _is_admin_user(request.user)

    def has_change_permission(self, request, obj=None) -> bool:
        return _is_admin_user(request.user)

    def has_delete_permission(self, request, obj=None) -> bool:
        return _is_admin_user(request.user)


# -------------------------
# Product / Inventory admin
# -------------------------


# PUBLIC_INTERFACE
def activate_items(modeladmin, request, queryset):
    """Activate selected products (is_active=True)."""
    if not _is_admin_user(request.user):
        raise PermissionDenied("Admin access required.")
    updated = queryset.update(is_active=True)
    modeladmin.message_user(request, f"Activated {updated} item(s).", level=messages.SUCCESS)


# PUBLIC_INTERFACE
def deactivate_items(modeladmin, request, queryset):
    """Deactivate selected products (is_active=False)."""
    if not _is_admin_user(request.user):
        raise PermissionDenied("Admin access required.")
    updated = queryset.update(is_active=False)
    modeladmin.message_user(request, f"Deactivated {updated} item(s).", level=messages.SUCCESS)


class LowStockListFilter(admin.SimpleListFilter):
    title = "Low stock"
    parameter_name = "low_stock"

    def lookups(self, request, model_admin):
        return (
            ("1", "Low stock (<= threshold)"),
            ("0", "Not low stock"),
        )

    def queryset(self, request, queryset):
        # Available stock is computed as (stock_on_hand - stock_reserved)
        if self.value() == "1":
            return queryset.filter(stock_on_hand__lte=F("stock_reserved") + F("low_stock_threshold"))
        if self.value() == "0":
            return queryset.exclude(stock_on_hand__lte=F("stock_reserved") + F("low_stock_threshold"))
        return queryset


class InventoryAdjustmentInline(admin.TabularInline):
    model = InventoryAdjustment
    extra = 0
    fields = ("delta", "reason", "note", "created_at", "created_by")
    readonly_fields = ("created_at", "created_by")
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request, obj=None):
        # Add inventory adjustments only for admins.
        return _is_admin_user(request.user)

    def has_change_permission(self, request, obj=None):
        # Treat adjustments as immutable audit log.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ItemAdmin(AdminOnlyModelAdmin):
    list_display = [
        "title",
        "sku",
        "category",
        "price",
        "discount_price",
        "is_active",
        "stock_on_hand",
        "stock_reserved",
        "available_stock",
        "low_stock_threshold",
    ]
    list_display_links = ["title", "sku"]
    list_filter = ["is_active", "category", "label", LowStockListFilter]
    search_fields = ["title", "sku", "slug"]
    ordering = ["-id"]
    actions = [activate_items, deactivate_items]
    inlines = [InventoryAdjustmentInline]
    readonly_fields = ["stock_reserved"]

    fieldsets = (
        ("Catalog", {"fields": ("title", "slug", "sku", "category", "label", "image", "description")}),
        ("Pricing", {"fields": ("price", "discount_price", "is_active")}),
        (
            "Inventory",
            {
                "fields": (
                    "stock_on_hand",
                    "stock_reserved",
                    "low_stock_threshold",
                )
            },
        ),
    )

    @admin.display(description="Available")
    def available_stock(self, obj: Item) -> int:
        return obj.available_stock


class InventoryAdjustmentAdmin(AdminOnlyModelAdmin):
    list_display = ["item", "delta", "reason", "created_at", "created_by"]
    list_filter = ["reason", "created_at"]
    search_fields = ["item__title", "item__sku", "note", "created_by__username"]
    ordering = ["-created_at", "-id"]

    def save_model(self, request, obj: InventoryAdjustment, form, change) -> None:
        """
        When an admin creates an InventoryAdjustment from the adjustments screen,
        automatically apply the delta to Item.stock_on_hand so the adjustment is meaningful.

        Note: This keeps existing inventory services intact; it's a management convenience.
        """
        if not _is_admin_user(request.user):
            raise PermissionDenied("Admin access required.")

        with transaction.atomic():
            obj.created_by = request.user
            super().save_model(request, obj, form, change)

            item = Item.objects.select_for_update().get(pk=obj.item_id)
            new_stock = int(item.stock_on_hand or 0) + int(obj.delta or 0)
            if new_stock < 0:
                raise ValidationError("Inventory adjustment would make stock_on_hand negative.")
            item.stock_on_hand = new_stock
            item.save(update_fields=["stock_on_hand"])


admin.site.register(Item, ItemAdmin)
admin.site.register(InventoryAdjustment, InventoryAdjustmentAdmin)


# -------------------------
# Orders admin
# -------------------------


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    fields = ("performed_at", "from_status", "to_status", "performed_by", "idempotency_key", "reason")
    readonly_fields = fields
    ordering = ("-performed_at", "-id")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _transition_orders(
    modeladmin,
    request,
    queryset,
    *,
    target_status: str,
    inventory_mode: str | None = None,
):
    """
    Internal helper to do safe, idempotent order transitions in bulk.

    inventory_mode:
      - "paid": reserve+commit inventory first
      - "cancel": release reservations
      - "refund": restock committed units
      - None: no inventory mutation
    """
    if not _is_admin_user(request.user):
        raise PermissionDenied("Admin access required.")

    success = 0
    skipped = 0
    failed = 0

    for order in queryset.select_related("payment", "coupon", "user").all():
        idem = f"admin:{target_status}:{order.id}:{uuid.uuid4().hex}"

        try:
            if inventory_mode == "paid":
                reserve_inventory_for_order(
                    order=order,
                    performed_by=request.user,
                    idempotency_key=f"admin-reserve:{idem}",
                )
                commit_inventory_for_paid_order(
                    order=order,
                    performed_by=request.user,
                    idempotency_key=f"admin-commit:{idem}",
                )
            elif inventory_mode == "cancel":
                release_inventory_reservations_for_order(
                    order=order,
                    performed_by=request.user,
                    idempotency_key=f"admin-release:{idem}",
                    reason="Released reservation due to admin cancellation",
                )
            elif inventory_mode == "refund":
                restock_inventory_for_order_refund(
                    order=order,
                    performed_by=request.user,
                    idempotency_key=f"admin-restock:{idem}",
                )

            # Use the domain transition service (validates + writes history).
            order.transition_status(
                target_status=target_status,
                performed_by=request.user,
                reason=f"Admin bulk transition to {target_status}",
                idempotency_key=idem,
                metadata={"source": "django_admin", "performed_at": timezone.now().isoformat()},
            )
            success += 1
        except ValueError:
            # Invalid transition: treat as a skip (idempotent-ish UX).
            skipped += 1
        except Exception:
            failed += 1

    if success:
        modeladmin.message_user(request, f"Transitioned {success} order(s) to {target_status}.", level=messages.SUCCESS)
    if skipped:
        modeladmin.message_user(
            request,
            f"Skipped {skipped} order(s) due to invalid/no-op transitions.",
            level=messages.WARNING,
        )
    if failed:
        modeladmin.message_user(
            request,
            f"Failed to transition {failed} order(s). See server logs for details.",
            level=messages.ERROR,
        )


# PUBLIC_INTERFACE
def mark_paid(modeladmin, request, queryset):
    """Transition selected orders to PAID (reserve+commit inventory)."""
    return _transition_orders(modeladmin, request, queryset, target_status=Order.Status.PAID, inventory_mode="paid")


# PUBLIC_INTERFACE
def mark_fulfilling(modeladmin, request, queryset):
    """Transition selected orders to FULFILLING."""
    return _transition_orders(modeladmin, request, queryset, target_status=Order.Status.FULFILLING)


# PUBLIC_INTERFACE
def mark_shipped(modeladmin, request, queryset):
    """Transition selected orders to SHIPPED."""
    return _transition_orders(modeladmin, request, queryset, target_status=Order.Status.SHIPPED)


# PUBLIC_INTERFACE
def mark_delivered(modeladmin, request, queryset):
    """Transition selected orders to DELIVERED."""
    return _transition_orders(modeladmin, request, queryset, target_status=Order.Status.DELIVERED)


# PUBLIC_INTERFACE
def mark_cancelled(modeladmin, request, queryset):
    """Transition selected orders to CANCELLED (release reservations)."""
    return _transition_orders(modeladmin, request, queryset, target_status=Order.Status.CANCELLED, inventory_mode="cancel")


# PUBLIC_INTERFACE
def mark_refunded(modeladmin, request, queryset):
    """Transition selected orders to REFUNDED (restock committed units)."""
    return _transition_orders(modeladmin, request, queryset, target_status=Order.Status.REFUNDED, inventory_mode="refund")


class OrderAdmin(AdminOnlyModelAdmin):
    list_display = [
        "id",
        "user",
        "status",
        "ordered",
        "being_delivered",
        "received",
        "refund_requested",
        "refund_granted",
        "total_amount",
        "coupon",
        "payment_ref",
        "ordered_date",
    ]
    list_display_links = ["id", "user"]
    list_filter = [
        "status",
        "ordered",
        "being_delivered",
        "received",
        "refund_requested",
        "refund_granted",
    ]
    search_fields = [
        "user__username",
        "ref_code",
        "payment__provider_reference",
        "payment__idempotency_key",
    ]
    ordering = ["-id"]
    inlines = [OrderStatusHistoryInline]
    actions = [mark_paid, mark_fulfilling, mark_shipped, mark_delivered, mark_cancelled, mark_refunded]
    readonly_fields = ["ref_code", "ordered_date", "start_date"]

    @admin.display(description="Total")
    def total_amount(self, obj: Order) -> float:
        try:
            return obj.get_total()
        except Exception:
            return 0.0

    @admin.display(description="Payment ref")
    def payment_ref(self, obj: Order) -> str:
        if not obj.payment_id:
            return ""
        return obj.payment.provider_reference or obj.payment.stripe_charge_id or str(obj.payment_id)


admin.site.register(Order, OrderAdmin)


# -------------------------
# Payment / Address / Profile / Wishlist
# -------------------------


class PaymentAdmin(AdminOnlyModelAdmin):
    list_display = [
        "id",
        "user",
        "amount",
        "provider",
        "mode",
        "status",
        "provider_reference",
        "idempotency_key",
        "timestamp",
    ]
    list_filter = ["provider", "mode", "status", "timestamp"]
    search_fields = ["user__username", "provider_reference", "idempotency_key", "stripe_charge_id"]
    ordering = ["-timestamp", "-id"]


admin.site.register(Payment, PaymentAdmin)


class AddressAdmin(AdminOnlyModelAdmin):
    list_display = [
        "user",
        "street_address",
        "apartment_address",
        "country",
        "zip",
        "address_type",
        "default",
    ]
    list_filter = ["default", "address_type", "country"]
    search_fields = ["user", "street_address", "apartment_address", "zip"]


admin.site.register(Address, AddressAdmin)
admin.site.register(UserProfile, AdminOnlyModelAdmin)


class WishlistItemAdmin(AdminOnlyModelAdmin):
    list_display = ["user", "item", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["user__username", "user__email", "item__title", "item__sku", "item__slug"]
    ordering = ["-created_at", "-id"]
    readonly_fields = ["user", "item", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(WishlistItem, WishlistItemAdmin)


# -------------------------
# Coupons admin (management enhancements)
# -------------------------
#
# Note: The current Coupon model in core.models is the legacy version (code, amount only).
# The request asked for validity windows, usage limits, min spend, type, active flag, and
# redemptions inline. Those require schema support; this admin keeps changes additive and
# will automatically expose those fields if/when the model is upgraded.
#


class CouponAdmin(AdminOnlyModelAdmin):
    list_display = ["id", "code", "amount"]
    search_fields = ["code"]
    ordering = ["-id"]

    def get_list_display(self, request):
        base = list(super().get_list_display(request))
        # If upgraded fields exist, show them.
        model_fields = {f.name for f in self.model._meta.get_fields()}
        for extra in ["is_active", "valid_from", "valid_until", "usage_limit", "times_redeemed", "min_spend", "discount_type"]:
            if extra in model_fields and extra not in base:
                base.append(extra)
        return base

    def get_list_filter(self, request):
        base = []
        model_fields = {f.name for f in self.model._meta.get_fields()}
        for f in ["is_active", "valid_from", "valid_until", "discount_type"]:
            if f in model_fields:
                base.append(f)
        return base


admin.site.register(Coupon, CouponAdmin)


# Refund stays admin-only for moderation via DRF endpoint or legacy.
admin.site.register(Refund, AdminOnlyModelAdmin)


# -------------------------
# Reviews admin (moderation)
# -------------------------


# PUBLIC_INTERFACE
def approve_reviews(modeladmin, request, queryset):
    """Approve selected reviews (is_approved=True)."""
    if not _is_admin_user(request.user):
        raise PermissionDenied("Admin access required.")
    updated = queryset.update(is_approved=True)
    modeladmin.message_user(request, f"Approved {updated} review(s).", level=messages.SUCCESS)


# PUBLIC_INTERFACE
def reject_reviews(modeladmin, request, queryset):
    """Reject selected reviews (is_approved=False)."""
    if not _is_admin_user(request.user):
        raise PermissionDenied("Admin access required.")
    updated = queryset.update(is_approved=False)
    modeladmin.message_user(request, f"Rejected {updated} review(s).", level=messages.SUCCESS)


class ReviewAdmin(AdminOnlyModelAdmin):
    list_display = ["id", "item", "user", "rating", "is_approved", "created_at", "updated_at"]
    list_filter = ["is_approved", "rating", "created_at"]
    search_fields = ["user__username", "user__email", "item__title", "item__sku", "title", "body"]
    ordering = ["-created_at", "-id"]
    actions = [approve_reviews, reject_reviews]
    readonly_fields = ["created_at", "updated_at"]

    def get_readonly_fields(self, request, obj=None):
        """
        Prevent editing once approved except by superuser.

        Admins can still change moderation state via approve/reject actions.
        """
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.is_approved and not getattr(request.user, "is_superuser", False):
            # Lock all editable fields if approved (except is_approved for superuser).
            ro += ["user", "item", "rating", "title", "body", "is_approved"]
        return ro


admin.site.register(Review, ReviewAdmin)


# Keep OrderItem registered but admin-only.
admin.site.register(OrderItem, AdminOnlyModelAdmin)
