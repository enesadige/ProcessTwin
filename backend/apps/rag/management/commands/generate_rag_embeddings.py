from django.core.management.base import BaseCommand, CommandError

from apps.rag.providers.registry import DESCRIPTORS, PROVIDER_DEFAULT_PROFILES
from apps.rag.services.embeddings import (
    generate_embeddings,
    get_provider,
    selected_documents,
)


class Command(BaseCommand):
    help = "Generate one selected provider embedding set for active RAG chunks."

    def add_arguments(self, parser):
        parser.add_argument("--document-code", action="append", dest="document_codes")
        parser.add_argument("--snapshot-identifier")
        parser.add_argument("--provider", choices=sorted(PROVIDER_DEFAULT_PROFILES))
        parser.add_argument("--embedding-profile", choices=sorted(DESCRIPTORS))
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--validate-only", action="store_true")

    def handle(self, *args, **options):
        try:
            provider = get_provider(
                options["provider"],
                embedding_profile=options["embedding_profile"],
            )
            documents, snapshot = selected_documents(
                document_codes=options["document_codes"],
                snapshot_identifier=options["snapshot_identifier"],
            )
            result = generate_embeddings(
                documents,
                provider=provider,
                force=options["force"],
                data_snapshot=snapshot if options["snapshot_identifier"] else None,
                validate_only=options["validate_only"],
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        if options["validate_only"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Embedding validation passed: "
                    f"chunks={result['chunk_count']}, pending={result['pending_count']}."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                "RAG embeddings ready: "
                f"run={result.pk}, chunks={result.chunk_count}, "
                f"embedded={result.embedding_count}, provider={result.embedding_provider}."
            )
        )
