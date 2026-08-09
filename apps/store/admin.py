from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Order, Product, ProductVariant, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("image", "order")
    ordering = ("order", "id")


class ProductVariantInline(TabularInline):
    model = ProductVariant
    extra = 1
    fields = ("size", "price_override", "stock_qty", "is_active")


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ("name", "category", "price", "total_stock", "sold_out", "is_active", "order")
    list_editable = ("sold_out", "is_active", "order")
    list_filter = ("category", "sold_out", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline, ProductVariantInline]


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ("order_id", "customer_name", "customer_phone", "subtotal", "status", "created_at")
    list_editable = ("status",)
    list_filter = ("status", "created_at")
    search_fields = ("order_id", "customer_name", "customer_phone")
    readonly_fields = ("order_id", "items_snapshot", "subtotal", "created_at")