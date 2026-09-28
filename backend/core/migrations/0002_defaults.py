from django.db import migrations


def defaults(apps, schema_editor):
    alias = schema_editor.connection.alias
    Business = apps.get_model("core", "Business")
    Permission = apps.get_model("core", "AgentPermission")
    Role = apps.get_model("core", "AgentRole")
    Business.objects.using(alias).get_or_create(pk=1)
    role, _ = Role.objects.using(alias).get_or_create(
        code="customer_service", defaults={"label": "顧客服務"}
    )
    for code, label, scope in [
        ("business.read", "查詢商家資料", "business"),
        ("customer.profile.read", "查詢自己的顧客資料", "customer"),
        ("customer.profile.write", "更新自己的顯示名稱", "customer"),
    ]:
        permission, _ = Permission.objects.using(alias).get_or_create(
            code=code, defaults={"label": label, "scope": scope}
        )
        role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(defaults, migrations.RunPython.noop)]
