from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("skills/", views.skills, name="skills"),
    path("skills/<slug:slug>/", views.skill_detail, name="skill_detail"),
    path("paths/", views.paths, name="paths"),
    path("paths/<slug:slug>/", views.path_detail, name="path_detail"),
]
