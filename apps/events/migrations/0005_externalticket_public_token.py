import uuid

from django.db import migrations, models


def fill_tokens(apps, schema_editor):
    ExternalTicket = apps.get_model("events", "ExternalTicket")
    for ticket in ExternalTicket.objects.all().iterator():
        ticket.public_token = uuid.uuid4()
        ticket.save(update_fields=["public_token"])


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0004_externalticket_events_exte_payment_1d6c33_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="externalticket",
            name="public_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.RunPython(fill_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="externalticket",
            name="public_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="externalticket",
            name="event_location_details",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
