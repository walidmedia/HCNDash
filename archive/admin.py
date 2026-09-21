from django.contrib import admin

from .models import Dataset, Periode, Row


@admin.register(Periode)
class PeriodeAdmin(admin.ModelAdmin):
    list_display = ("libelle", "statut", "soumis_par", "soumis_at")
    list_filter = ("statut",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("name", "periode", "created_by", "created_at")
    list_filter = ("periode",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Row)
class RowAdmin(admin.ModelAdmin):
    list_display = ("dataset", "id", "created_at")
    list_filter = ("dataset",)
    readonly_fields = ("created_at", "updated_at")
