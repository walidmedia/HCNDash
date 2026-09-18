from django.urls import path

from . import views

app_name = "archive"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("datasets/upload/", views.upload_dataset, name="dataset_upload"),
    path("datasets/new/", views.add_dataset_manual, name="dataset_manual_new"),
    path("datasets/<int:pk>/", views.dataset_detail, name="dataset_detail"),
    path("datasets/<int:pk>/rows/add/", views.add_row, name="row_add"),
    path("datasets/<int:pk>/rows/<int:row_id>/edit/", views.edit_row, name="row_edit"),
    path("datasets/<int:pk>/rows/<int:row_id>/delete/", views.delete_row, name="row_delete"),
]
