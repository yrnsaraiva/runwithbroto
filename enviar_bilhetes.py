import smtplib
import time
import os
import sys
import django
from email.utils import formataddr

# ========================
# CONFIGURAR DJANGO
# ========================
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.events.models import ExternalTicket
from apps.events.pdf import build_external_ticket_pdf

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# ========================
# CONFIGURAÇÕES
# ========================
SMTP_SERVER = "smtp.hostinger.com"
SMTP_PORT = 465
EMAIL_REMETENTE = "eventos@runwithbroto.com"
NOME_REMETENTE = "Run With Broto"
SENHA = "M1nd3d@brun"

# Filtrar por evento (deixa None para enviar a todos os paid)
EVENTO = "Beer Run"  # ex: "Hybrid Race"


# ========================
# TEMPLATE HTML
# ========================
def gerar_html(nome, event_name):
    return f"""
    <html>
      <body>
        <p>
          Olá <b>{nome}</b> 👋<br><br>
    
          Está confirmado! 🎉🔥<br><br>
        
          No dia <b>7 de Novembro</b>, vamos voltar em grande com o 
          <b>{event_name}</b> 🏃‍♂️💥 uma manhã especial dedicada à corrida, à conexão 
          e aos bons momentos junto da nossa comunidade.<br><br>
        
          Ficamos muito felizes por teres escolhido fazer parte desta experiência. 
          Prepara-te para uma manhã cheia de energia, movimento, conversas e 
          memórias que vão ficar. ☕✨<br><br>
        
          O teu bilhete segue em anexo 📩. Guarda-o bem e, no dia do evento, basta 
          apresentares o QR Code à entrada para fazeres o teu check-in de forma simples 
          e rápida. 🎟️⚡<br><br>
        
          Agora só falta uma coisa: traz a tua melhor energia, o teu espírito de aventura 
          e vem viver este momento connosco. 😎💛🖤<br><br>
        
          Mal podemos esperar para te receber! 🚀🏅<br><br>
        
          Até amanhã,<br>
          <b>Equipa Run with Broto</b> 🏅💛🖤
        </p>
      </body>
    </html>
    """


# ========================
# ENVIO
# ========================
def enviar_bilhetes():
    qs = ExternalTicket.objects.filter(payment_status__iexact="paid", entered=False)

    if EVENTO:
        qs = qs.filter(event_name__icontains=EVENTO)

    qs = qs.order_by("event_name", "buyer_name")

    total = qs.count()
    print(f"\nTotal de tickets paid: {total}\n")

    if total == 0:
        print("Nenhum ticket encontrado.")
        return

    enviados = 0
    erros = 0
    sem_email = []  # lista para o relatório final

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as servidor:
        servidor.login(EMAIL_REMETENTE, SENHA)

        for ticket in qs:
            nome = ticket.buyer_name or "Participante"
            email = ticket.buyer_email
            event_name = ticket.event_name

            # Sem email — regista e continua
            if not email:
                sem_email.append(f"  • {nome} | {ticket.buyer_phone} | {ticket.external_id}")
                print(f"⚠️  Sem email: {nome} ({ticket.external_id})")
                continue

            try:
                pdf_bytes = build_external_ticket_pdf(ticket)

                msg = MIMEMultipart("mixed")
                msg["From"] = formataddr((NOME_REMETENTE, EMAIL_REMETENTE))
                msg["To"] = email
                msg["Subject"] = f"🎟️ O teu bilhete para {event_name}"

                msg.attach(MIMEText(gerar_html(nome, event_name), "html"))

                pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
                pdf_part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=f"bilhete-{ticket.external_id}.pdf",
                )
                msg.attach(pdf_part)

                servidor.send_message(msg)

                print(f"✅ {nome} ({email})")
                enviados += 1

                time.sleep(2)

            except Exception as e:
                print(f"❌ Erro em {email}: {e}")
                erros += 1

    print("\n========== RESUMO ==========")
    print(f"✅ Enviados:   {enviados}")
    print(f"❌ Erros:      {erros}")
    print(f"⚠️  Sem email:  {len(sem_email)}")

    if sem_email:
        print("\nParticipantes sem email (contactar manualmente):")
        for linha in sem_email:
            print(linha)

    print("=============================\n")


# ========================
# EXECUTAR
# ========================
if __name__ == "__main__":
    enviar_bilhetes()
