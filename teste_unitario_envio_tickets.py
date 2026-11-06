import smtplib
import os
import sys
import django

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
EMAIL_REMETENTE = "info@config.com"
SENHA = "M1nd3d@brun"

# Email onde queres receber o teste
EMAIL_TESTE = "yrnsaraiva.office@gmail.com"


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
    
      No dia <b>1 de agosto</b>, vamos fechar esta temporada em grande com o 
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
    
      Até breve,<br>
      <b>Equipa Run with Broto</b> 🏅💛🖤
    </p>

  </body>
</html>

    """


# ========================
# TESTES
# ========================
def teste_ligacao_smtp():
    print("1️⃣  A testar ligação SMTP...", end=" ")
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as s:
            s.login(EMAIL_REMETENTE, SENHA)
        print("✅ OK")
        return True
    except Exception as e:
        print(f"❌ FALHOU — {e}")
        return False


def teste_ticket_na_base_de_dados():
    print("2️⃣  A procurar ticket paid na base de dados...", end=" ")
    ticket = ExternalTicket.objects.filter(payment_status__iexact="paid").first()
    if ticket:
        print(f"✅ Encontrado: {ticket.external_id} — {ticket.buyer_name}")
        return ticket
    else:
        print("❌ Nenhum ticket paid encontrado")
        return None


def teste_geracao_pdf(ticket):
    print("3️⃣  A gerar PDF do bilhete...", end=" ")
    try:
        pdf_bytes = build_external_ticket_pdf(ticket)
        tamanho_kb = len(pdf_bytes) / 1024
        print(f"✅ OK ({tamanho_kb:.1f} KB)")
        return pdf_bytes
    except Exception as e:
        print(f"❌ FALHOU - {e}")
        return None


def teste_envio_email(ticket, pdf_bytes):
    print(f"4️⃣  A enviar email de teste para {EMAIL_TESTE}...", end=" ")
    try:
        msg = MIMEMultipart("mixed")
        msg["From"] = EMAIL_REMETENTE
        msg["To"] = EMAIL_TESTE
        msg["Subject"] = f"[TESTE] 🎟️ Bilhete para {ticket.event_name}"

        msg.attach(MIMEText(gerar_html(ticket.buyer_name or "Participante", ticket.event_name), "html"))

        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"bilhete-{ticket.external_id}.pdf",
        )
        msg.attach(pdf_part)

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as servidor:
            servidor.login(EMAIL_REMETENTE, SENHA)
            servidor.send_message(msg)

        print("✅ Enviado!")
        return True
    except Exception as e:
        print(f"❌ FALHOU — {e}")
        return False


# ========================
# EXECUTAR
# ========================
if __name__ == "__main__":
    print("\n========== TESTE DE ENVIO DE BILHETES ==========\n")

    resultados = []

    ok_smtp = teste_ligacao_smtp()
    resultados.append(("Ligação SMTP", ok_smtp))
    if not ok_smtp:
        print("\n⛔ SMTP falhou. Verifica credenciais e tenta novamente.\n")
        exit(1)

    ticket = teste_ticket_na_base_de_dados()
    resultados.append(("Ticket na BD", ticket is not None))
    if not ticket:
        print("\n⛔ Sem tickets para testar. Cria um ticket paid primeiro.\n")
        exit(1)

    pdf_bytes = teste_geracao_pdf(ticket)
    resultados.append(("Geração de PDF", pdf_bytes is not None))
    if not pdf_bytes:
        print("\n⛔ PDF falhou. Verifica o build_external_ticket_pdf.\n")
        exit(1)

    ok_email = teste_envio_email(ticket, pdf_bytes)
    resultados.append(("Envio de email", ok_email))

    print("\n========== RESULTADO ==========")
    todos_ok = True
    for nome, ok in resultados:
        estado = "✅" if ok else "❌"
        print(f"  {estado}  {nome}")
        if not ok:
            todos_ok = False

    print()
    if todos_ok:
        print("🎉 Tudo OK! Podes correr o enviar_bilhetes.py\n")
    else:
        print("⚠️  Há erros. Corrige antes de enviar a todos.\n")