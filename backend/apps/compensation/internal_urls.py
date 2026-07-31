from django.urls import path

from apps.compensation import internal_views

app_name = "compensation_internal"

urlpatterns = [
    path("eligibility/", internal_views.evaluate_refund_eligibility, name="eligibility"),
    path("amount/", internal_views.calculate_refund_amount, name="amount"),
    path("options/", internal_views.evaluate_compensation_options, name="options"),
    path("campaigns/check/", internal_views.check_campaign_eligibility, name="campaign-check"),
    path("options/rank/", internal_views.rank_compensation_options, name="rank-options"),
    path("evidence/", internal_views.get_compensation_evidence, name="evidence"),
]
