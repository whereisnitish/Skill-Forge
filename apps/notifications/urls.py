from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.index, name="index"),
    path("<int:pk>/read/", views.read, name="read"),
    path("read-all/", views.read_all, name="read_all"),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
]
