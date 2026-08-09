from django.db import models
from django.utils.text import slugify

CATEGORY_CHOICES = [
    ("vestuario", "Vestuário"),
    ("acessorios", "Acessórios"),
    ("packs", "Packs"),
]


class Product(models.Model):
    name = models.CharField("Nome", max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    category = models.CharField("Categoria", max_length=20, choices=CATEGORY_CHOICES)
    price = models.DecimalField(
        "Preço base (MZN)",
        max_digits=10,
        decimal_places=2,
        help_text="Usado como fallback quando uma variação não tem preço próprio",
    )
    description = models.TextField("Descrição", blank=True)
    badge = models.CharField(
        "Badge", max_length=40, blank=True, help_text="Ex: Novo, Poupa 15%"
    )
    sold_out = models.BooleanField(
        "Esgotado (manual)",
        default=False,
        help_text="Marca manual — se ligada, esconde o produto independentemente do stock das variações",
    )
    is_active = models.BooleanField("Ativo", default=True)
    order = models.PositiveIntegerField("Ordem de exibição", default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"
        ordering = ["order", "-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            i = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base_slug}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    def is_sold_out(self):
        """Esgotado se marcado manualmente, ou se não existe nenhuma variação ativa com stock."""
        if self.sold_out:
            return True
        if not self.pk:
            return False
        return not self.variants.filter(is_active=True, stock_qty__gt=0).exists()

    def total_stock(self):
        return self.variants.aggregate(total=models.Sum("stock_qty"))["total"] or 0
    total_stock.short_description = "Stock total"


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField("Imagem", upload_to="loja/produtos/galeria/")
    order = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        verbose_name = "Imagem do produto"
        verbose_name_plural = "Imagens do produto"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.product.name} — imagem {self.order}"


class ProductVariant(models.Model):
    class Size(models.TextChoices):
        UNICO = "UNICO", "Único"
        XS = "XS", "XS"
        S = "S", "S"
        M = "M", "M"
        L = "L", "L"
        XL = "XL", "XL"
        XXL = "XXL", "XXL"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    size = models.CharField("Tamanho", max_length=6, choices=Size.choices, default=Size.UNICO)
    price_override = models.DecimalField(
        "Preço específico (MZN)",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Deixa em branco para usar o preço base do produto",
    )
    stock_qty = models.PositiveIntegerField("Stock", default=0)
    is_active = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Variação"
        verbose_name_plural = "Variações"
        ordering = ["size"]
        constraints = [
            models.UniqueConstraint(fields=["product", "size"], name="uniq_product_size"),
        ]

    def get_final_price(self):
        """Retorna o preço específico da variação ou usa o preço base do produto."""
        if self.price_override is not None:
            return self.price_override
        return self.product.price

    def is_in_stock(self):
        return self.is_active and self.stock_qty > 0

    def __str__(self):
        return f"{self.product.name} — {self.get_size_display()}"


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pendente"),
        ("confirmed", "Confirmado"),
        ("delivered", "Entregue"),
        ("cancelled", "Cancelado"),
    ]

    order_id = models.CharField(
        "Nº do pedido",
        max_length=20,
        unique=True,
        editable=False,
        help_text="Gerado automaticamente, ex: RWB-00001",
    )
    customer_name = models.CharField("Nome do cliente", max_length=120, blank=True)
    customer_phone = models.CharField("Telefone", max_length=30, blank=True)
    items_snapshot = models.JSONField("Itens", help_text="Cópia dos itens no momento da encomenda")
    subtotal = models.DecimalField("Subtotal (MZN)", max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Encomenda"
        verbose_name_plural = "Encomendas"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Encomenda {self.order_id} — {self.subtotal} MT"

    def save(self, *args, **kwargs):
        if not self.order_id:
            self.order_id = self._generate_order_id()

        became_cancelled = False
        if self.pk:
            previous_status = Order.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            became_cancelled = bool(previous_status) and previous_status != "cancelled" and self.status == "cancelled"

        super().save(*args, **kwargs)

        if became_cancelled:
            self._restock_items()

    def _restock_items(self):
        """Devolve ao stock as unidades desta encomenda quando ela é cancelada."""
        for item in self.items_snapshot or []:
            slug = item.get("productId")
            size = item.get("size")
            qty = item.get("qty") or 0
            if not slug or not size or not qty:
                continue
            ProductVariant.objects.filter(product__slug=slug, size=size).update(
                stock_qty=models.F("stock_qty") + qty
            )

    def _generate_order_id(self):
        """Ex: RWB-00001, RWB-00002... sequencial, fácil de citar no WhatsApp/telefone."""
        last = Order.objects.exclude(order_id="").order_by("-id").first()
        next_n = 1
        if last:
            try:
                next_n = int(last.order_id.split("-")[-1]) + 1
            except (IndexError, ValueError):
                next_n = Order.objects.count() + 1

        candidate = f"RWB-{next_n:05d}"
        while Order.objects.filter(order_id=candidate).exists():
            next_n += 1
            candidate = f"RWB-{next_n:05d}"
        return candidate