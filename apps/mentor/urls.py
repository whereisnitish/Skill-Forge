from django.urls import path

from . import views

app_name = "mentor"

urlpatterns = [
    path("", views.index, name="index"),
    path("ask/", views.ask, name="ask"),
    path("<int:pk>/", views.detail, name="detail"),
]
