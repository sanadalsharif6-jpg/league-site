from __future__ import annotations

import os
from typing import Iterable, Tuple

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction


def _is_cloudinary_url(url: str) -> bool:
    return "res.cloudinary.com" in (url or "")


def _iter_file_fields(model) -> Iterable[Tuple[str, object]]:
    for f in model._meta.get_fields():
        if hasattr(f, "upload_to") and hasattr(f, "storage"):
            yield f.name, f


class Command(BaseCommand):
    help = "Upload existing local media files to Cloudinary and update DB fields automatically."

    def add_arguments(self, parser):
        parser.add_argument("--app", default="league", help="App label to scan (default: league)")
        parser.add_argument(
            "--models",
            nargs="*",
            default=[],
            help="Optional model names to include (e.g. Player Team). If empty, scans all models in the app.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Show what would happen without uploading.")

    @transaction.atomic
    def handle(self, *args, **opts):
        app_label = opts["app"]
        model_names = set(m.lower() for m in (opts["models"] or []))
        dry = bool(opts["dry_run"])

        cloud_url = os.environ.get("CLOUDINARY_URL") or getattr(settings, "CLOUDINARY_URL", "")
        if not cloud_url:
            self.stderr.write("ERROR: CLOUDINARY_URL is not set. Add it in Render env vars first.")
            return

        app_config = apps.get_app_config(app_label)
        models = list(app_config.get_models())
        if model_names:
            models = [m for m in models if m.__name__.lower() in model_names]

        total = uploaded = missing = skipped = 0

        for model in models:
            file_fields = list(_iter_file_fields(model))
            if not file_fields:
                continue

            qs = model.objects.all()
            self.stdout.write(f"\nScanning {model.__name__} ({qs.count()} rows) ...")

            for obj in qs.iterator(chunk_size=200):
                changed = False
                changed_fields = []

                for field_name, _field in file_fields:
                    ff = getattr(obj, field_name, None)
                    if not ff or not getattr(ff, "name", ""):
                        continue

                    total += 1

                    try:
                        url = ff.url
                    except Exception:
                        url = ""

                    if _is_cloudinary_url(url):
                        skipped += 1
                        continue

                    try:
                        local_path = ff.path
                    except Exception:
                        local_path = ""

                    if not local_path or not os.path.exists(local_path):
                        missing += 1
                        continue

                    if dry:
                        self.stdout.write(f"DRY: Would upload {model.__name__}#{obj.pk}.{field_name} from {local_path}")
                        continue

                    with open(local_path, "rb") as f:
                        data = f.read()

                    basename = os.path.basename(local_path)
                    ff.save(basename, ContentFile(data), save=False)
                    changed = True
                    changed_fields.append(field_name)
                    uploaded += 1

                if changed and not dry:
                    obj.save(update_fields=changed_fields)
                    self.stdout.write(f"Updated {model.__name__}#{obj.pk}: {', '.join(changed_fields)}")

        self.stdout.write("\nDone.")
        self.stdout.write(f"Total file fields seen: {total}")
        self.stdout.write(f"Uploaded to Cloudinary: {uploaded}")
        self.stdout.write(f"Skipped (already Cloudinary): {skipped}")
        self.stdout.write(f"Missing local files: {missing}")
        if missing:
            self.stdout.write(
                "NOTE: Missing local files means the original media files are not accessible on the machine you ran this on."
            )
