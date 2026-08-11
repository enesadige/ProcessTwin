from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User, UserRole


class Command(BaseCommand):
    help = "Create or update local-only ProcessTwin demo users."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True)

    def handle(self, *args, **options):
        password = options["password"]
        if len(password) < 8:
            raise CommandError("Demo password must be at least 8 characters.")
        for role in UserRole:
            username = f"demo_{role.value}"
            user, _ = User.objects.get_or_create(username=username)
            user.email = f"{username}@localhost"
            user.role = role.value
            user.is_active = True
            user.set_password(password)
            user.save(update_fields=["email", "role", "is_active", "password"])
            self.stdout.write(self.style.SUCCESS(f"Prepared {username} ({role.label})."))
