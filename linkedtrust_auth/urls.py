from django.urls import path
from . import views

app_name = "linkedtrust_auth"

urlpatterns = [
    path("redirect", views.RedirectView.as_view(), name="redirect"),
    path("callback", views.CallbackView.as_view(), name="callback"),
]
