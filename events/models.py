from django.db import models


class ExternalTicket(models.Model):
    external_id = models.CharField(max_length=50, unique=True)

    event_id_external = models.CharField(max_length=50)
    event_name = models.CharField(max_length=255)
    event_category = models.CharField(max_length=100, blank=True)

    event_province = models.CharField(max_length=100, blank=True)
    event_location_details = models.TextField(max_length=255, blank=True)
    event_image_url = models.URLField(blank=True)
    event_date = models.DateTimeField(null=True, blank=True)

    price_id_external = models.CharField(max_length=50, blank=True)
    price_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    entered = models.BooleanField(default=False)
    status = models.CharField(max_length=50, blank=True)
    payment_status = models.CharField(max_length=50, blank=True)

    buyer_phone = models.CharField(max_length=20, blank=True)
    buyer_name = models.CharField(max_length=255, blank=True)

    external_created_at = models.DateTimeField(null=True, blank=True)
    external_updated_at = models.DateTimeField(null=True, blank=True)

    raw_payload = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.external_id} - {self.event_name} - {self.buyer_name}"
