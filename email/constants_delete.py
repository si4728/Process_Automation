import yaml


with open("config.yaml") as fp:
    config = yaml.load(fp, yaml.FullLoader)

IMAP_SERVER = config["IMAP_SERVER"]
IMAP_PORT = config["IMAP_PORT"]
SMTP_SERVER = config["SMTP_SERVER"]
SMTP_PORT = config["SMTP_PORT"]


with open("secret.local") as fp:
    secrets = yaml.load(fp, yaml.FullLoader)
MAIL_ID = secrets["MAIL_ID"]
MAIL_PW = secrets["MAIL_PW"]
SENDER_ID = secrets["SENDER_ID"]
