from __future__ import annotations

import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from detector.models import Membership, Organization


class Command(BaseCommand):
    help = "Interactively create or update the initial organization administrator without putting a password on the command line."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--organization", default="Shanakht")
        parser.add_argument("--slug", default="shanakht")

    def handle(self, *args, **options):
        password = getpass.getpass("Administrator password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if not password or password != confirmation:
            raise CommandError("Passwords were empty or did not match")
        User = get_user_model()
        with transaction.atomic():
            organization, _ = Organization.objects.get_or_create(slug=options["slug"], defaults={"name": options["organization"]})
            user, created = User.objects.get_or_create(username=options["username"], defaults={"email": options["email"]})
            user.email = options["email"]
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.set_password(password)
            user.save()
            Membership.objects.get_or_create(organization=organization, user=user, role=Membership.Role.ADMIN)
        self.stdout.write(self.style.SUCCESS(f"Administrator {'created' if created else 'updated'} for organization {organization.slug}."))
