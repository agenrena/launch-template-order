from core import views as v
from django.urls import include, path, re_path

urlpatterns = [
    path("health/", v.health),
    path("api/console/session/", v.SessionView.as_view()),
    path("api/console/login/", v.LoginView.as_view()),
    path("api/console/setup/", v.SetupView.as_view()),
    path("api/console/logout/", v.LogoutView.as_view()),
    path("api/console/password/", v.PasswordView.as_view()),
    path("api/console/business/", v.BusinessView.as_view()),
    path("api/console/agenrena/", v.AgenrenaView.as_view()),
    path("api/console/agenrena/connect/", v.AgenrenaConnectView.as_view()),
    path("api/console/agenrena/check/", v.AgenrenaCheckView.as_view()),
    path("api/console/agenrena/disconnect/", v.AgenrenaDisconnectView.as_view()),
    path("api/console/members/", v.MembersView.as_view()),
    path("api/console/members/<int:pk>/", v.MemberView.as_view()),
    path("api/console/agent-roles/", v.RolesView.as_view()),
    path("api/console/keys/", v.KeysView.as_view()),
    path("api/console/keys/<uuid:pk>/revoke/", v.RevokeKeyView.as_view()),
    path("api/console/mcp/", v.McpView.as_view()),
    path("api/console/audit/", v.AuditView.as_view()),
    path("api/agent-api/session/", v.AgentSessionView.as_view()),
    path("api/agent-api/business/", v.AgentBusinessView.as_view()),
    path("api/agent-api/customer-profile/", v.AgentProfileView.as_view()),
    # Everything else is the console (built frontend), except unknown API paths.
    re_path(r"^(?!api/|health/|mcp)(?P<path>.*)$", v.frontend),
]

urlpatterns += [path("", include("ordering.urls"))]
