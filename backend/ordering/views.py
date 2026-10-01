import json

from core.permissions import agent_actor, authorize, human_actor
from core.serializers import CustomerRefInput
from core.services import audit
from core.views import AgentView, validated
from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from . import hours, payloads, services
from .models import (
    Category,
    MenuItem,
    MenuPhoto,
    Option,
    OptionGroup,
    OrderingSettings,
    Round,
    Tab,
    Table,
)
from .serializers import (
    AmendInput,
    CategorySerializer,
    ConfirmDraftInput,
    DraftInput,
    MenuItemSerializer,
    OptionAvailabilitySerializer,
    OptionGroupSerializer,
    OrderingSettingsSerializer,
    PauseInput,
    RejectInput,
    RoundInput,
    TableSerializer,
    TakeoutInput,
)


def tabs():
    return Tab.objects.select_related("table", "customer").prefetch_related(
        Prefetch("rounds", queryset=Round.objects.prefetch_related("items__choices"))
    )


# ---- Public QR ordering: nobody signs in; the table or the link is the credential ----


class OrderingThrottle(AnonRateThrottle):
    scope = "ordering"


class PublicView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class WriteView(PublicView):
    throttle_classes = [OrderingThrottle]


class StoreView(PublicView):
    def get(self, request):
        return Response(payloads.web_menu())


class MenuPhotoView(PublicView):
    def get(self, request, pk, variant):
        if variant not in {"image", "thumbnail"}:
            raise Http404
        photo = get_object_or_404(MenuPhoto, pk=pk)
        try:
            file = getattr(photo, variant).open("rb")
        except FileNotFoundError as exc:
            raise Http404 from exc
        response = FileResponse(file, content_type="image/webp")
        response["Cache-Control"] = "public, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class JoinTableView(WriteView):
    def post(self, request):
        return Response(
            payloads.web_tab(services.join_table(request.data.get("table"))), status=201
        )


class TakeoutView(WriteView):
    def post(self, request):
        data = validated(TakeoutInput, request.data)
        tab = services.place_takeout(
            services.parse_lines(data["items"]),
            phone=services.clean_phone(data.get("phone")),
            note=services.clean_note(data.get("note")),
        )
        return Response(payloads.web_tab(tabs().get(pk=tab.pk)), status=201)


class TabView(PublicView):
    def get(self, request, token):
        return Response(payloads.web_tab(get_object_or_404(tabs(), access_token=token)))


class RoundsView(WriteView):
    def post(self, request, token):
        tab = get_object_or_404(Tab, access_token=token)
        data = validated(RoundInput, request.data)
        services.place_round(
            tab, services.parse_lines(data["items"]), note=services.clean_note(data.get("note"))
        )
        return Response(payloads.web_tab(tabs().get(pk=tab.pk)), status=201)


class DraftView(PublicView):
    """The customer sees the prepared cart; the customer reference stays server-side."""

    def get(self, request, token):
        draft = services.draft_for(token)
        if draft is None:
            raise services.OrderError("not_found", "找不到這個連結。", "請回原對話取得新連結。")
        payload = {
            "status": "submitted"
            if draft.submitted_tab_id
            else "expired"
            if draft.is_expired
            else "pending",
            "expires_at": draft.expires_at,
            "items": draft.items,
            "note": draft.customer_note,
            "store": payloads.web_menu(),
        }
        if draft.submitted_tab_id:
            payload["order"] = payloads.web_tab(tabs().get(pk=draft.submitted_tab_id))
        return Response(payload)


class ConfirmDraftView(WriteView):
    def post(self, request, token):
        data = validated(ConfirmDraftInput, request.data)
        tab, created = services.confirm_draft(
            token, phone=data.get("phone"), items=data.get("items"), note=data.get("note")
        )
        return Response(payloads.web_tab(tabs().get(pk=tab.pk)), status=201 if created else 200)


# ---- Console ----


def public_base(request):
    """Where customers open the ordering pages, or "" when their phones cannot
    reach this App yet (on this computer, before docs/publish.md)."""
    if settings.ORDER_PUBLIC_BASE_URL or settings.LOCAL_APP:
        return settings.ORDER_PUBLIC_BASE_URL
    return request.build_absolute_uri("/").rstrip("/")


class OrderingSettingsView(APIView):
    def get(self, request):
        authorize(human_actor(request.user), "orders.read")
        data = OrderingSettingsSerializer(OrderingSettings.current()).data
        return Response({**data, "public_url": public_base(request)})

    def patch(self, request):
        serializer = OrderingSettingsSerializer(
            OrderingSettings.current(), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        services.save_settings(human_actor(request.user), serializer)
        return Response(serializer.data)


class HoursView(APIView):
    def get(self, request):
        authorize(human_actor(request.user), "orders.read")
        return Response(hours.status())

    def put(self, request):
        services.replace_hours(human_actor(request.user), request.data.get("weekly"))
        return Response(hours.status())


class CatalogViewSet(viewsets.ModelViewSet):
    http_method_names = ["get", "post", "patch", "head", "options"]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        read = request.method in {"GET", "HEAD", "OPTIONS"}
        authorize(human_actor(request.user), "menu.read" if read else "menu.write")

    def perform_create(self, serializer):
        services.save_catalog(human_actor(self.request.user), serializer)

    def perform_update(self, serializer):
        services.save_catalog(human_actor(self.request.user), serializer)


class CategoryViewSet(CatalogViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class MenuItemViewSet(CatalogViewSet):
    queryset = MenuItem.objects.prefetch_related("photos")
    serializer_class = MenuItemSerializer

    def get_serializer(self, *args, **kwargs):
        if "data" in kwargs and self.request.content_type.startswith("multipart/form-data"):
            try:
                data = json.loads(self.request.data.get("payload", ""))
            except (ValueError, TypeError) as exc:
                raise serializers.ValidationError("餐點資料格式不正確。") from exc
            if not isinstance(data, dict):
                raise serializers.ValidationError("餐點資料格式不正確。")
            kwargs["data"] = data
        return super().get_serializer(*args, **kwargs)


class OptionGroupViewSet(CatalogViewSet):
    queryset = OptionGroup.objects.prefetch_related("options")
    serializer_class = OptionGroupSerializer


class OptionViewSet(CatalogViewSet):
    """Only the day-to-day switch: 珍珠 ran out. Everything else is edited on the group."""

    http_method_names = ["patch", "options"]
    queryset = Option.objects.all()
    serializer_class = OptionAvailabilitySerializer


class OrderingStatusView(APIView):
    def get(self, request):
        authorize(human_actor(request.user), "orders.read")
        return Response(hours.status())

    def post(self, request):
        actor = human_actor(request.user)
        data = validated(PauseInput, request.data)
        if data["action"] == "resume":
            return Response(services.resume_ordering(actor))
        return Response(
            services.pause_ordering(actor, minutes=data["minutes"], reason=data["reason"])
        )


class TodayView(APIView):
    def get(self, request):
        return Response(services.today_summary(human_actor(request.user)))


class TableViewSet(CatalogViewSet):
    queryset = Table.objects.all()
    serializer_class = TableSerializer


class TabsView(APIView):
    """?view=service: today's bills plus anything still open or unfinished.
    ?date=YYYY-MM-DD: one business day, closed bills included."""

    def get(self, request):
        authorize(human_actor(request.user), "orders.read")
        rows = tabs()
        if "date" in request.query_params:
            day = validated(
                type("DateInput", (serializers.Serializer,), {"date": serializers.DateField()}),
                request.query_params,
            )["date"]
            rows = rows.filter(business_date=day)
        else:
            rows = rows.filter(
                Q(business_date=hours.business_date())
                | Q(closed_at__isnull=True)
                | Q(rounds__status__in=[Round.PENDING, Round.CONFIRMED])
            ).distinct()
        return Response([payloads.console_tab(tab) for tab in rows[:500]])


class CloseTabView(APIView):
    def post(self, request, pk):
        tab = services.close_tab(human_actor(request.user), get_object_or_404(Tab, pk=pk))
        return Response(payloads.console_tab(tabs().get(pk=tab.pk)))


class RoundActionView(APIView):
    def post(self, request, pk, action):
        actor = human_actor(request.user)
        round_ = get_object_or_404(Round, pk=pk)
        if action == "confirm":
            services.confirm_round(actor, round_)
        elif action == "complete":
            services.complete_round(actor, round_)
        elif action == "reject":
            services.reject_round(actor, round_, validated(RejectInput, request.data)["message"])
        elif action == "amend":
            data = validated(AmendInput, request.data)
            services.amend_round(
                actor,
                round_,
                services.parse_lines(data["items"], allow_price=True),
                confirm=data["confirm"],
            )
        else:
            raise services.OrderError("unknown_action", "不支援此操作。")
        return Response(payloads.console_tab(tabs().get(pk=round_.tab_id)))


# ---- Agent (takeout only: a table has its own QR code) ----


class AgentShopView(AgentView):
    @transaction.atomic
    def get(self, request):
        actor = agent_actor(request.auth)
        authorize(actor, "business.read")
        audit(actor, "shop.read")
        return Response({**payloads.store(), "ask_url": payloads.ask_url()})


class AgentMenuView(AgentView):
    @transaction.atomic
    def get(self, request):
        actor = agent_actor(request.auth)
        authorize(actor, "menu.read")
        audit(actor, "menu.read")
        return Response(payloads.agent_menu())


class AgentDraftsView(AgentView):
    def post(self, request):
        data = validated(DraftInput, request.data)
        base = public_base(request)
        if not base:
            raise services.OrderError(
                "not_published",
                "這間店還沒開放線上點餐連結，請顧客直接到店或來電點餐。",
            )
        draft, token = services.create_draft(agent_actor(request.auth), **data)
        return Response(
            {
                "draft_id": str(draft.pk),
                "status": "pending_confirmation",
                "confirmation_url": f"{base}/d/{token}",
                "expires_at": draft.expires_at.astimezone(hours.zone()).isoformat(),
                "customer_name": draft.customer.display_name,
            },
            status=201,
            headers={"Cache-Control": "no-store"},
        )


class AgentOrdersView(AgentView):
    @transaction.atomic
    def get(self, request):
        actor = agent_actor(request.auth)
        ref = validated(CustomerRefInput, request.query_params.dict())["customer_ref"]
        rows = services.customer_orders(actor, "order.read", ref)[: services.RECENT_ORDERS]
        audit(actor, "order.listed", customer=rows[0].customer if rows else None)
        return Response({"orders": [payloads.agent_order(tab) for tab in rows]})


class AgentOrderView(AgentView):
    def get(self, request, pk):
        actor = agent_actor(request.auth)
        ref = validated(CustomerRefInput, request.query_params.dict())["customer_ref"]
        tab = services.customer_orders(actor, "order.read", ref).filter(pk=pk).first()
        if tab is None:
            raise services.OrderError("not_found", "找不到這筆訂單。")
        return Response(payloads.agent_order(tab))


class AgentCancelView(AgentView):
    def post(self, request, pk):
        ref = validated(CustomerRefInput, request.data)["customer_ref"]
        tab = services.cancel_by_customer(agent_actor(request.auth), customer_ref=ref, order_id=pk)
        return Response(payloads.agent_order(tabs().get(pk=tab.pk)))
