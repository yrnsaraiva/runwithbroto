from django.shortcuts import render


def contact(request):
    return render(request, "core/contact.html")


def our_story(request):
    return render(request, "core/our-story.html")
