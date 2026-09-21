from django.urls import path

from . import views

app_name = "spe_report"

urlpatterns = [
    path("", views.period_list, name="period_list"),
    path("<int:mois_id>/", views.period_detail, name="period_detail"),
    path("<int:mois_id>/soumettre/", views.period_submit, name="period_submit"),
    path("<int:mois_id>/rouvrir/", views.period_reopen, name="period_reopen"),
    path("<int:mois_id>/rapport/", views.period_report, name="period_report"),
    path("<int:mois_id>/emploi/", views.period_emploi, name="period_emploi"),
    path("<int:mois_id>/investissements/", views.period_investissements, name="period_investissements"),
    path("<int:mois_id>/section/<slug:code>/", views.period_section, name="period_section"),
    path("objectifs/<int:annee>/", views.objectifs, name="objectifs"),
]
