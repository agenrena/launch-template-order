from django.db import migrations


def defaults(apps, schema_editor):
    alias = schema_editor.connection.alias
    Permission = apps.get_model("core", "AgentPermission")
    Role = apps.get_model("core", "AgentRole")
    role = Role.objects.using(alias).get(pk="customer_service")
    for code, label, scope in [
        ("menu.read", "查詢菜單", "business"),
        ("order.read", "查詢自己的訂單", "customer"),
        ("order.create", "為自己準備訂單確認連結", "customer"),
        ("order.cancel", "取消自己尚未接單的訂單", "customer"),
    ]:
        permission, _ = Permission.objects.using(alias).get_or_create(
            code=code, defaults={"label": label, "scope": scope}
        )
        role.permissions.add(permission)
    apps.get_model("ordering", "OrderingSettings").objects.using(alias).get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("ordering", "0001_initial"), ("core", "0002_defaults")]
    operations = [migrations.RunPython(defaults, migrations.RunPython.noop)]
