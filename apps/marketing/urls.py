from django.urls import path

from . import views

app_name = "marketing"

urlpatterns = [
    path("", views.home, name="home"),
    path("features/", views.features, name="features"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("tracks/", views.tracks, name="tracks"),
    path("pricing/", views.pricing, name="pricing"),
    path("about/", views.about, name="about"),
    path("faq/", views.faq, name="faq"),
    path("contact/", views.contact, name="contact"),
    path("legal/privacy/", views.privacy, name="privacy"),
    path("legal/terms/", views.terms, name="terms"),
]
