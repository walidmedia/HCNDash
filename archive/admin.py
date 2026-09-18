from django.contrib import admin

from .models import Dataset, Row


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "created_by", "created_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Row)
class RowAdmin(admin.ModelAdmin):
    list_display = ("dataset", "id", "created_at")
    list_filter = ("dataset",)
    readonly_fields = ("created_at", "updated_at")
