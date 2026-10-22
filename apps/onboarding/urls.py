from django.urls import path

from . import views

app_name = "onboarding"

urlpatterns = [
    path("", views.start, name="start"),
    path("<slug:step>/", views.step, name="step"),
]
