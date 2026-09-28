import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Business, Membership
from core.permissions import human_actor
from core.services import audit, check_password


class Command(BaseCommand):
    help = "Create the first owner. Password is entered privately, never a command argument."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        Business.current()
        Business.objects.select_for_update().get(pk=1)
        if Membership.objects.filter(role="owner", user__is_active=True).exists():
            raise CommandError("已有擁有者，請由後台管理成員。")
        User = get_user_model()
        if User.objects.filter(username=options["username"]).exists():
            raise CommandError("帳號已存在。")
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            raise CommandError("兩次密碼不同。")
        user = User(username=options["username"])
        try:
            check_password(password, user)
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        user.set_password(password)
        user.full_clean()
        user.save()
        Membership.objects.create(user=user, role="owner")
        audit(human_actor(user), "owner.initialized", user)
        self.stdout.write(self.style.SUCCESS("Owner created."))
