from django.urls import path

from . import views

app_name = "archive"

urlpatterns = [
    path("", views.period_list, name="period_list"),
    path("dashboard/", views.period_list, name="dashboard"),
    path("periods/<int:mois_id>/", views.period_detail, name="period_detail"),
    path("periods/<int:mois_id>/soumettre/", views.period_submit, name="period_submit"),
    path("periods/<int:mois_id>/rouvrir/", views.period_reopen, name="period_reopen"),
    path("periods/<int:mois_id>/supprimer/", views.period_delete, name="period_delete"),
    path("periods/<int:mois_id>/export/<str:fmt>/", views.period_export, name="period_export"),
    path("periods/<int:mois_id>/upload/", views.upload_dataset, name="dataset_upload"),
    path("periods/<int:mois_id>/new/", views.add_dataset_manual, name="dataset_manual_new"),
    path("datasets/<int:pk>/", views.dataset_detail, name="dataset_detail"),
    path("datasets/<int:pk>/delete/", views.dataset_delete, name="dataset_delete"),
    path("datasets/<int:pk>/export/<str:fmt>/", views.dataset_export, name="dataset_export"),
    path("datasets/<int:pk>/rows/add/", views.add_row, name="row_add"),
    path("datasets/<int:pk>/rows/<int:row_id>/edit/", views.edit_row, name="row_edit"),
    path("datasets/<int:pk>/rows/<int:row_id>/delete/", views.delete_row, name="row_delete"),
]
