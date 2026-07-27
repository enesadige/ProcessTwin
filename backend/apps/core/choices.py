from django.db import models


class ResultStatus(models.TextChoices):
    EXACT = "exact", "Exact"
    LIMITED = "limited", "Limited"
    INSUFFICIENT_DATA = "insufficient_data", "Insufficient data"
    FAILED = "failed", "Failed"
