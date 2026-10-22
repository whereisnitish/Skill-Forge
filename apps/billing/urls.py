from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.index, name="index"),
    path("checkout/<slug:plan>/", views.checkout, name="checkout"),
    path("portal/", views.portal, name="portal"),
    path("dev/checkout/<slug:plan>/", views.dev_checkout, name="dev_checkout"),
    path("dev/cancel/", views.dev_cancel, name="dev_cancel"),
    path("webhooks/stripe/", views.stripe_webhook, name="stripe_webhook"),
]
