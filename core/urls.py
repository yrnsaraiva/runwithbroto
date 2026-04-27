from django.urls import path
from . import views

app_name = "core"


urlpatterns = [
    path("", views.home, name="home"),
    path("contact/", views.contact, name="contact"),
    path("our-story/", views.our_story, name="our_story"),
]
