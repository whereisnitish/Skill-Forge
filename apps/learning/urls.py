from django.urls import path

from .views import challenges, goals, progress, today

app_name = "learning"

urlpatterns = [
    path("", today.today, name="today"),
    path("plan/more/", today.more, name="practice_more"),
    path("plan/<int:pk>/skip/", today.skip, name="skip"),
    path("reviews/", today.reviews, name="reviews"),
    path("reviews/<slug:slug>/start/", today.start_review, name="start_review"),
    path("challenges/<slug:slug>/", challenges.workspace, name="challenge"),
    path("challenges/<slug:slug>/submit/", challenges.submit, name="submit"),
    path("challenges/<slug:slug>/hint/", challenges.hint, name="hint"),
    path("challenges/<slug:slug>/solution/", challenges.reveal_solution, name="reveal_solution"),
    path("challenges/<slug:slug>/autosave/", challenges.autosave, name="autosave"),
    path("challenges/<slug:slug>/syntax/", challenges.check_syntax, name="check_syntax"),
    path("attempts/<int:pk>/", challenges.attempt_detail, name="attempt"),
    path("attempts/<int:pk>/status/", challenges.attempt_status, name="attempt_status"),
    path("goals/", goals.goal_list, name="goals"),
    path("goals/new/", goals.goal_create, name="goal_create"),
    path("goals/<int:pk>/", goals.goal_detail, name="goal_detail"),
    path("goals/<int:pk>/edit/", goals.goal_edit, name="goal_edit"),
    path("goals/<int:pk>/status/", goals.goal_status, name="goal_status"),
    path("mastery/", progress.mastery, name="mastery"),
    path("mastery/<slug:slug>/", progress.mastery_detail, name="mastery_detail"),
    path("progress/", progress.progress, name="progress"),
    path("history/", progress.history, name="history"),
]
