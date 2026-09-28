from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views as v

router = SimpleRouter()
router.register("categories", v.CategoryViewSet)
router.register("menu-items", v.MenuItemViewSet)
router.register("tables", v.TableViewSet)
router.register("option-groups", v.OptionGroupViewSet)
router.register("options", v.OptionViewSet)

urlpatterns = [
    # Public QR ordering
    path("api/web/store/", v.StoreView.as_view()),
    path("api/web/tabs/", v.JoinTableView.as_view()),
    path("api/web/orders/", v.TakeoutView.as_view()),
    path("api/web/tabs/<str:token>/", v.TabView.as_view()),
    path("api/web/tabs/<str:token>/rounds/", v.RoundsView.as_view()),
    path("api/web/order-drafts/<str:token>/", v.DraftView.as_view()),
    path("api/web/order-drafts/<str:token>/confirm/", v.ConfirmDraftView.as_view()),
    # Console
    path("api/console/ordering-settings/", v.OrderingSettingsView.as_view()),
    path("api/console/hours/", v.HoursView.as_view()),
    path("api/console/ordering-status/", v.OrderingStatusView.as_view()),
    path("api/console/sales/today/", v.TodayView.as_view()),
    path("api/console/tabs/", v.TabsView.as_view()),
    path("api/console/tabs/<uuid:pk>/close/", v.CloseTabView.as_view()),
    path("api/console/rounds/<uuid:pk>/<str:action>/", v.RoundActionView.as_view()),
    path("api/console/", include(router.urls)),
    # Agent
    path("api/agent-api/shop/", v.AgentShopView.as_view()),
    path("api/agent-api/menu/", v.AgentMenuView.as_view()),
    path("api/agent-api/order-drafts/", v.AgentDraftsView.as_view()),
    path("api/agent-api/orders/", v.AgentOrdersView.as_view()),
    path("api/agent-api/orders/<uuid:pk>/", v.AgentOrderView.as_view()),
    path("api/agent-api/orders/<uuid:pk>/cancel/", v.AgentCancelView.as_view()),
]
