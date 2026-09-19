from django.core.management.base import BaseCommand, CommandError

from detector.authentication import issue_organization_api_key
from detector.models import Organization


class Command(BaseCommand):
    help = "Create an organization-scoped API key. The plaintext is printed exactly once."

    def add_arguments(self, parser):
        parser.add_argument("organization_slug")
        parser.add_argument("name")
        parser.add_argument("--scopes", default="applications:read,applications:write")

    def handle(self, *args, **options):
        try:
            organization = Organization.objects.get(slug=options["organization_slug"], is_active=True)
        except Organization.DoesNotExist as exc:
            raise CommandError("Organization not found") from exc
        scopes = [item.strip() for item in options["scopes"].split(",") if item.strip()]
        record, plaintext = issue_organization_api_key(organization, options["name"], scopes)
        self.stdout.write(f"Key ID: {record.pk}")
        self.stdout.write(f"API key (store now): {plaintext}")
