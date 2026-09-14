from django.urls import include, path

from detector.views import LivenessView, ReadinessView


urlpatterns = [
    path("health/live", LivenessView.as_view(), name="health-live"),
    path("health/ready", ReadinessView.as_view(), name="health-ready"),
    path("api/v1/", include("detector.urls")),
]
