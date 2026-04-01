import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# CONFIGURAÇÕES
smtp_server = "smtp.hostinger.com"
smtp_port = 465  # SSL
email_remetente = "info@runwithbroto.com"
senha = "M1nd3d@brun"

email_destinatario = "yrnsaraiva.office@gmail.com"

# CRIAR MENSAGEM
mensagem = MIMEMultipart("mixed")
mensagem["From"] = email_remetente
mensagem["To"] = email_destinatario
mensagem["Subject"] = "🏁 Uhuu! Seu certificado da Hybrid Race chegou 🎉"

html = """
<html>
  <body>
    <p>Olá <b>Yuran Saraiva</b> 👋<br><br>
       Yeahh! Missão cumprida 💪🔥<br>
       Encarraste o desafio, deste o teu melhor e fizeste parte de algo grande! A <b>Hybrid Race</b> do dia 28 de Março foi um sucesso, e tu estiveste lá a fazer acontecer 🏃‍♂️💥<br><br>
       Sabemos que o certificado demorou um bocadinho (valeu pela paciência 🙏), mas agora é oficial: já está no anexo, pronto para guardar como recordação dessa conquista incrível 📜<br><br>
       Foi mesmo maningue top te ter connosco! E olha… isto é só o começo 👀 Já estamos a preparar os próximos desafios, e esperamos te ver lá outra vez!<br><br>
       Agora é contigo: celebra, partilha e aproveita esse momento porque tu mereces 🎉🙌<br><br>
       Abraço,<br>
       <b>Equipa Run with Broto</b> 🏅💛🖤
    </p>
  </body>
</html>
"""

mensagem.attach(MIMEText(html, "html"))

path = "Hybrid_Race_Certificado.pdf"

with open(path, "rb") as f:
    pdf = MIMEApplication(f.read(), _subtype="pdf")

pdf.add_header(
    "Content-Disposition",
    "attachment",
    filename="Hybrid_Race_Certificado.pdf"
)

mensagem.attach(pdf)

# ENVIAR EMAIL
try:
    with smtplib.SMTP_SSL(smtp_server, smtp_port) as servidor:
        servidor.login(email_remetente, senha)
        servidor.send_message(mensagem)
        print("E-mail enviado com sucesso!")

except Exception as e:
    print("Erro ao enviar e-mail:", e)