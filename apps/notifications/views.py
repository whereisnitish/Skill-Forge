from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .models import Notification
from .services import mark_read
from .tasks import UNSUBSCRIBE_SALT

KIND_TO_PREFERENCE = {
    Notification.Kind.DAILY_REMINDER: ("daily_reminder_enabled", "daily practice reminders"),
    Notification.Kind.REVIEW_DUE: ("review_reminder_enabled", "due-review reminders"),
    Notification.Kind.MILESTONE: ("milestone_emails_enabled", "milestone and achievement emails"),
    Notification.Kind.ACHIEVEMENT: ("milestone_emails_enabled", "milestone and achievement emails"),
}


@login_required
def index(request: HttpRequest) -> HttpResponse:
    queryset = Notification.objects.filter(user=request.user)
    page = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(request, "notifications/index.html", {"page": page})


@login_required
@require_POST
def read(request: HttpRequest, pk: int) -> HttpResponse:
    notification = Notification.objects.filter(user=request.user, pk=pk).first()
    if notification is None:
        return HttpResponse(status=404)
    mark_read(request.user, pk)
    if request.htmx:
        notification.refresh_from_db()
        return render(request, "notifications/_item.html", {"notification": notification})
    if notification.url.startswith("/"):
        return redirect(notification.url)
    return redirect("notifications:index")


@login_required
@require_POST
def read_all(request: HttpRequest) -> HttpResponse:
    count = mark_read(request.user)
    if request.htmx:
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    messages.success(request, f"Marked {count} notification{'s' if count != 1 else ''} as read.")
    return redirect("notifications:index")


@csrf_exempt  # Authenticated by the signed token; mail clients POST without a CSRF cookie (RFC 8058).
@require_http_methods(["GET", "POST"])
def unsubscribe(request: HttpRequest, token: str) -> HttpResponse:
    """Signed, login-free unsubscribe link (supports RFC 8058 one-click POST)."""
    try:
        data = signing.loads(token, salt=UNSUBSCRIBE_SALT, max_age=60 * 60 * 24 * 90)
    except signing.BadSignature:
        return render(request, "notifications/unsubscribe.html", {"status": "invalid"}, status=400)
    preference = KIND_TO_PREFERENCE.get(data.get("k"))
    user = get_user_model().objects.filter(pk=data.get("u")).select_related("profile").first()
    if user is None or preference is None:
        return render(request, "notifications/unsubscribe.html", {"status": "invalid"}, status=400)
    field, label = preference
    if request.method == "POST":
        setattr(user.profile, field, False)
        user.profile.save(update_fields=[field, "updated_at"])
        return render(request, "notifications/unsubscribe.html", {"status": "done", "label": label})
    return render(request, "notifications/unsubscribe.html", {"status": "confirm", "label": label, "token": token})
