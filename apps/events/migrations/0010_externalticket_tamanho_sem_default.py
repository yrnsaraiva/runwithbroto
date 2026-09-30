from django.db import migrations, models


class Migration(migrations.Migration):
    """O tamanho da camisete deixa de ter 'M' por omissão: nem todos os eventos
    têm camisetes. Os bilhetes de eventos sem camisetes ficam limpos com
    `sync_tickets --all` (a API diz-nos se o evento tem camisetes)."""

    dependencies = [
        ("events", "0009_externalticket_price_name"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externalticket",
            name="tamanho_camisete",
            field=models.CharField(
                blank=True,
                choices=[
                    ("S", "Pequeno (S)"),
                    ("M", "Médio (M)"),
                    ("L", "Grande (L)"),
                    ("XL", "Extra Grande (XL)"),
                ],
                default="",
                max_length=3,
            ),
        ),
    ]
