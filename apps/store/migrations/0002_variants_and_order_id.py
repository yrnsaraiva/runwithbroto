import django.db.models.deletion
from django.db import migrations, models


VALID_SIZES = {"UNICO", "XS", "S", "M", "L", "XL", "XXL"}


def migrate_sizes_to_variants(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    ProductVariant = apps.get_model("store", "ProductVariant")

    for product in Product.objects.all():
        raw_sizes = [s.strip().upper() for s in (product.sizes or "").split(",") if s.strip()]
        sizes = [s for s in raw_sizes if s in VALID_SIZES] or ["UNICO"]
        for size in sizes:
            # stock_qty=100 por omissão para não esconder produtos já publicados —
            # ajusta os valores reais de stock no admin depois de correr esta migração.
            ProductVariant.objects.get_or_create(
                product=product,
                size=size,
                defaults={"stock_qty": 100, "is_active": True},
            )


def assign_order_ids(apps, schema_editor):
    Order = apps.get_model("store", "Order")
    for i, order in enumerate(Order.objects.order_by("created_at", "id"), start=1):
        order.order_id = f"RWB-{i:05d}"
        order.save(update_fields=["order_id"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0001_initial"),
    ]

    operations = [
        # 1) order_id sem unique ainda, para poder popular linhas existentes primeiro
        migrations.AddField(
            model_name="order",
            name="order_id",
            field=models.CharField(
                blank=True,
                default="",
                editable=False,
                help_text="Gerado automaticamente, ex: RWB-00001",
                max_length=20,
                verbose_name="Nº do pedido",
            ),
        ),
        migrations.CreateModel(
            name="ProductVariant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "size",
                    models.CharField(
                        choices=[
                            ("UNICO", "Único"),
                            ("XS", "XS"),
                            ("S", "S"),
                            ("M", "M"),
                            ("L", "L"),
                            ("XL", "XL"),
                            ("XXL", "XXL"),
                        ],
                        default="UNICO",
                        max_length=6,
                        verbose_name="Tamanho",
                    ),
                ),
                (
                    "price_override",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Deixa em branco para usar o preço base do produto",
                        max_digits=10,
                        null=True,
                        verbose_name="Preço específico (MZN)",
                    ),
                ),
                ("stock_qty", models.PositiveIntegerField(default=0, verbose_name="Stock")),
                ("is_active", models.BooleanField(default=True, verbose_name="Ativo")),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="variants",
                        to="store.product",
                    ),
                ),
            ],
            options={
                "verbose_name": "Variação",
                "verbose_name_plural": "Variações",
                "ordering": ["size"],
            },
        ),
        migrations.AddConstraint(
            model_name="productvariant",
            constraint=models.UniqueConstraint(fields=("product", "size"), name="uniq_product_size"),
        ),
        # 2) migrar dados: sizes (CSV) -> ProductVariant, e atribuir order_id às encomendas antigas
        migrations.RunPython(migrate_sizes_to_variants, noop),
        migrations.RunPython(assign_order_ids, noop),
        # 3) já não precisamos do campo de texto livre
        migrations.RemoveField(
            model_name="product",
            name="sizes",
        ),
        migrations.AlterField(
            model_name="product",
            name="sold_out",
            field=models.BooleanField(
                default=False,
                help_text="Marca manual — se ligada, esconde o produto independentemente do stock das variações",
                verbose_name="Esgotado (manual)",
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="price",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=10,
                verbose_name="Preço base (MZN)",
                help_text="Usado como fallback quando uma variação não tem preço próprio",
            ),
        ),
        # 4) só agora tornamos order_id único e obrigatório, com todas as linhas já preenchidas
        migrations.AlterField(
            model_name="order",
            name="order_id",
            field=models.CharField(
                editable=False,
                help_text="Gerado automaticamente, ex: RWB-00001",
                max_length=20,
                unique=True,
                verbose_name="Nº do pedido",
            ),
        ),
    ]
