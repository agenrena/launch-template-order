"""Runtime's optional django_admin bootstrap; never reset existing credentials."""

import os

from django.core.management.base import BaseCommand, CommandError

from core.services import Conflict, create_first_owner, has_owner


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        if has_owner():
            return
        name, password = (
            os.getenv("BOOTSTRAP_ADMIN_USERNAME"),
            os.getenv("BOOTSTRAP_ADMIN_PASSWORD"),
        )
        if not name or not password:
            raise CommandError("Runtime must supply bootstrap credentials.")
        try:
            create_first_owner(name, password)
        except Conflict as exc:
            if has_owner():  # Another process initialized it first.
                return
            raise CommandError("Refusing to take over an existing account.") from exc
        self.stdout.write("Owner initialized.")
