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
    price = models.DecimalField("Preço (MZN)", max_digits=10, decimal_places=2)
    sizes = models.CharField(
        "Tamanhos",
        max_length=200,
        default="Único",
        help_text="Separados por vírgula, ex: S,M,L,XL",
    )
    description = models.TextField("Descrição", blank=True)
    image = models.ImageField("Imagem", upload_to="loja/produtos/", blank=True, null=True)
    badge = models.CharField(
        "Badge", max_length=40, blank=True, help_text="Ex: Novo, Poupa 15%"
    )
    sold_out = models.BooleanField("Esgotado", default=False)
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

    def sizes_list(self):
        return [s.strip() for s in self.sizes.split(",") if s.strip()]


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pendente"),
        ("confirmed", "Confirmado"),
        ("delivered", "Entregue"),
        ("cancelled", "Cancelado"),
    ]

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
        return f"Encomenda #{self.pk} — {self.subtotal} MT"
