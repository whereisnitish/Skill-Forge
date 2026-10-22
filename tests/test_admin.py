import pytest
from django.contrib import admin
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_every_admin_changelist_loads(client, catalog, learner):
    from apps.accounts.models import User
    from apps.learning.services.attempts import submit_attempt
    from tests.learning.helpers import correct_answer, version

    submit_attempt(learner, version("basics-mcq"), correct_answer("basics-mcq"))
    staff = User.objects.create_superuser("root@example.com", "root-pass-phrase-123")
    client.force_login(staff)
    for model in admin.site._registry:
        url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
        assert client.get(url).status_code == 200, url


def test_learning_records_are_read_only_in_admin(client, learner):
    from apps.accounts.models import User
    from apps.learning.models import LearningAttempt
    from apps.learning.services.attempts import submit_attempt
    from tests.learning.helpers import correct_answer, version

    submit_attempt(learner, version("basics-mcq"), correct_answer("basics-mcq"))
    attempt = LearningAttempt.objects.get()
    client.force_login(User.objects.create_superuser("root2@example.com", "root-pass-phrase-123"))
    assert client.get(reverse("admin:learning_learningattempt_add")).status_code == 403
    page = client.get(reverse("admin:learning_learningattempt_change", args=[attempt.pk]))
    assert page.status_code == 200 and "Save" not in page.content.decode().split('<div class="submit-row">')[-1][:200]
