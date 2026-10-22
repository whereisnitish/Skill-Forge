from django.urls import path

from . import settings_views as views

app_name = "accounts_settings"

urlpatterns = [
    path("", views.index, name="index"),
    path("profile/", views.update_profile, name="profile"),
    path("learning/", views.update_learning, name="learning"),
    path("notifications/", views.update_notifications, name="notifications"),
    path("appearance/", views.update_appearance, name="appearance"),
    path("theme/", views.set_theme, name="theme"),
    path("email/", views.change_email, name="email"),
    path("password/", views.change_password, name="password"),
    path("delete/", views.delete_account, name="delete"),
]
