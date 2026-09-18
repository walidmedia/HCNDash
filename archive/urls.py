from django.urls import path

from . import views

app_name = "archive"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
]
