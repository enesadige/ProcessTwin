from django.urls import path

from apps.rag import internal_views

app_name = "rag_internal"

urlpatterns = [
    path("search/", internal_views.search_documents, name="search-documents"),
]
