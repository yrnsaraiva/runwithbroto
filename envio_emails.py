import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# CONFIGURAÇÕES
smtp_server = "smtp.hostinger.com"
smtp_port = 465  # SSL
email_remetente = "info@runwithbroto.com"
senha = "M1nd3d@brun"

email_destinatario = "yrnsaraiva.office@gmail.com"

# CRIAR MENSAGEM
mensagem = MIMEMultipart()
mensagem["From"] = email_remetente
mensagem["To"] = email_destinatario
mensagem["Subject"] = "Teste de envio com Python"

corpo = "Olá, este é um e-mail enviado com Python usando Hostinger."
mensagem.attach(MIMEText(corpo, "plain"))

# ENVIAR EMAIL
try:
    with smtplib.SMTP_SSL(smtp_server, smtp_port) as servidor:
        servidor.login(email_remetente, senha)
        servidor.send_message(mensagem)
        print("E-mail enviado com sucesso!")

except Exception as e:
    print("Erro ao enviar e-mail:", e)