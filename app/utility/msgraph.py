import requests
from app.config import Config


def get_access_token():
    Config.validate()
    print(Config.AAD_ENDPOINT, Config.TENANT_ID, Config.CLIENT_ID)
    url = f"{Config.AAD_ENDPOINT}/{Config.TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": Config.CLIENT_ID,
        "scope": "https://graph.microsoft.com/.default",
        "client_secret": Config.CLIENT_SECRET,
        "grant_type": "client_credentials",
    }
    resp = requests.post(url, data=data, timeout = 20)
    resp.raise_for_status()
    return resp.json()["access_token"]

def send_mail(to_email, subject, body):
    token = get_access_token()
    url = f"{Config.GRAPH_ENDPOINT}/v1.0/users/{Config.FROM_EMAIL}/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body
            },
            "toRecipients": [
                {"emailAddress": {"address": to_email}}
            ]
        }
    }
    resp = requests.post(url, headers=headers, json=message)
    resp.raise_for_status()
    return resp.status_code == 202