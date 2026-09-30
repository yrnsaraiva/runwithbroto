from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("events", "0005_externalticket_public_token")]

    operations = [
        migrations.AddField("externalticket", "qr_value",
                            models.CharField(blank=True, max_length=255)),
        migrations.AddField("externalticket", "checkout_url",
                            models.URLField(blank=True, max_length=500)),
        migrations.AddField("externalticket", "payment_instructions",
                            models.TextField(blank=True)),
    ]
