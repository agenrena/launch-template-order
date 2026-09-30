import getpass

from django.core.management.base import BaseCommand, CommandError

from core.services import create_first_owner


class Command(BaseCommand):
    help = "Create the first owner. Password is entered privately, never a command argument."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            raise CommandError("兩次密碼不同。")
        try:
            create_first_owner(options["username"], password)
        except Exception as exc:
            raise CommandError(str(getattr(exc, "detail", exc))) from exc
        self.stdout.write(self.style.SUCCESS("Owner created."))
