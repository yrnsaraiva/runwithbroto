# Run With Broto

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SECRET_KEY` | sim (produção) | chave secreta do Django |
| `DATABASE_URL` | sim (produção) | URL do Postgres; sem ela usa SQLite local |
| `ETICKETS_BEARER_TOKEN` | sim | token da API ETickets |
| `ETICKETS_WEBHOOK_SECRET` | recomendada | `webhook_secret` do organizador na API; valida `X-ETK-Signature` |
| `ETICKETS_BASE_URL` | não | default `https://etk-api.up.railway.app` |
| `REDIS_URL` | não | cache Redis; sem ela usa cache em memória |
| `ALLOWED_HOSTS` | não | hosts extra, separados por vírgula |
| `MEDIA_ROOT` | não | default `/app/media` em produção |
| `DEBUG` | não | `1` para desenvolvimento |

Testes: `DEBUG=1 SECRET_KEY=x python manage.py test`

## Integração com a API ETickets

- **Webhook:** configure na API `webhook_url = https://<site>/events/webhooks/etk/`. O site atualiza o pagamento assim que o bilhete é pago.
- **Rede de segurança (cron, a cada 5 min):** `python manage.py sync_tickets` (apanha webhooks perdidos).
- A página de sucesso sonda `GET /tickets/{id}` até o pagamento confirmar.
- O formulário envia `externalReference`, por isso um duplo clique não cobra duas vezes.
- O scanner valida QRs assinados (`TCKT…|assinatura`) via `POST /tickets/check-in`; QRs antigos `RWB|id` continuam a funcionar localmente.
