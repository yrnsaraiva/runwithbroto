from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Order, Product


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    list_display = ("name", "category", "price", "sold_out", "is_active", "order")
    list_editable = ("sold_out", "is_active", "order")
    list_filter = ("category", "sold_out", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ("id", "customer_name", "customer_phone", "subtotal", "status", "created_at")
    list_editable = ("status",)
    list_filter = ("status", "created_at")
    readonly_fields = ("items_snapshot", "subtotal", "created_at")
