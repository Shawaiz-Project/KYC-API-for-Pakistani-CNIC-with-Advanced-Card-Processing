from django.urls import path

from .views import LegacyDetectorView, ProcessView


urlpatterns = [
    path("kyc/process", ProcessView.as_view(), name="kyc-process-v1"),
    # The exact historical no-trailing-slash route is retained.
    path("card/detector", LegacyDetectorView.as_view(), name="id_detector"),
]
