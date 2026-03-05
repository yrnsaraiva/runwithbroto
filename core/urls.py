from django.urls import path
from . import views
from events import views as ev__views

app_name = "core"


urlpatterns = [
    path("", ev__views.event_list, name="home"),
    path("contact/", views.contact, name="contact"),
    path("our-story/", views.our_story, name="our_story"),
]
