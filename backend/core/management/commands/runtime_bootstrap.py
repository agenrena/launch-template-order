"""Runtime's optional django_admin bootstrap; never reset existing credentials."""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Business, Membership
from core.permissions import human_actor
from core.services import audit, check_password


class Command(BaseCommand):
    @transaction.atomic
    def handle(self, *args, **kwargs):
        Business.current()
        Business.objects.select_for_update().get(pk=1)
        if Membership.objects.filter(role="owner", user__is_active=True).exists():
            return
        name, password = (
            os.getenv("BOOTSTRAP_ADMIN_USERNAME"),
            os.getenv("BOOTSTRAP_ADMIN_PASSWORD"),
        )
        if not name or not password:
            raise CommandError("Runtime must supply bootstrap credentials.")
        User = get_user_model()
        if User.objects.filter(username=name).exists():
            raise CommandError("Refusing to take over an existing account.")
        user = User(username=name)
        check_password(password, user)
        user.set_password(password)
        user.full_clean()
        user.save()
        Membership.objects.create(user=user, role="owner")
        audit(human_actor(user), "owner.initialized", user)
        self.stdout.write("Owner initialized.")
