from django.conf import settings
from django.db import models


class Dataset(models.Model):
    """A table of data, either uploaded from a spreadsheet or entered manually.

    Column names are stored as an ordered list rather than as fixed model
    fields, since different datasets can have entirely different columns.
    Each row's values live in Row.data, keyed by these column names.
    """

    name = models.CharField(max_length=255)
    columns = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="datasets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Row(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="rows")
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Row {self.pk} of dataset {self.dataset_id}"
