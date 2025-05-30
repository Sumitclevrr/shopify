import os, json, secrets, smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, session
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "c18e6fbc3a24d9f65a9b0e1a3b7d4c5e2a1f9d7b8e3c4f6d7a8b9c0d1e2f3a4b"
app.config.update(SESSION_COOKIE_SECURE=False, SESSION_COOKIE_SAMESITE="Lax")

SHOPIFY_API_KEY      = os.getenv("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET   = os.getenv("SHOPIFY_API_SECRET")
SHOPIFY_REDIRECT_URI = "https://shopify-9yg2.onrender.com/shopify/callback"
SCOPES = ",".join([
    "read_products","read_orders","read_customers","read_all_orders",
    "read_assigned_fulfillment_orders","read_merchant_managed_fulfillment_orders",
    "read_third_party_fulfillment_orders","read_fulfillments","read_locations",
    "read_discounts",
])

SMTP_HOST  = os.getenv("SMTP_HOST")
SMTP_PORT   = 587
SMTP_USER  = os.getenv("SMTP_USER")      # e.g. your-account@gmail.com
SMTP_PASS  = os.getenv("SMTP_PASS")
FROM_EMAIL  = "dev@getclevrr.com"
TO_EMAIL    = "engineering@getclevrr.com"

CREDENTIALS_FILE = "shopify_credentials.json"

def load_credentials():
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_credentials(store_domain, access_token):
    cred = load_credentials()
    cred[store_domain] = {"access_token": access_token, "store_domain": store_domain}
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(cred, f, indent=2)

def notify_engineering(store_domain, access_token):
    msg = EmailMessage()
    msg["Subject"] = f"[Shopify-connect] {store_domain} just connected"
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg.set_content(f"""
Hi team,

A new Shopify store finished OAuth via the public onboarding form.

Store : {store_domain}
Token : {access_token}

regards
Team Clevrr
""".strip())
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
            app.logger.info(f"Notification email sent for {store_domain}")
    except Exception as exc:
        app.logger.error(f"Failed to send notification for {store_domain}: {exc}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/connect", methods=["POST"])
def connect_to_shopify():
    shop = request.form.get("shop", "").strip()
    if not shop:
        return render_template("index.html", error="Please enter a shop domain")
    if "." not in shop:
        shop = f"{shop}.myshopify.com"
    elif shop.endswith(".myshopify"):
        shop = f"{shop}.com"
    elif not shop.endswith(".myshopify.com"):
        shop = f"{shop}.myshopify.com"
    state = secrets.token_hex(16)
    session["shop"] = shop
    session["oauth_state"] = state
    query = {
        "client_id": SHOPIFY_API_KEY,
        "scope": SCOPES,
        "redirect_uri": SHOPIFY_REDIRECT_URI,
        "state": state,
    }
    qs = "&".join(f"{k}={v}" for k, v in query.items())
    return redirect(f"https://{shop}/admin/oauth/authorize?{qs}")

@app.route("/shopify/callback")
def shopify_callback():
    if session.get("oauth_state") != request.args.get("state"):
        return render_template("index.html", error="Invalid state parameter; possible CSRF.")
    shop = session.get("shop")
    code = request.args.get("code")
    if not (shop and code):
        return render_template("index.html", error="Missing shop or code")
    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code,
    }
    r = requests.post(token_url, json=payload, timeout=10)
    if r.status_code != 200:
        return render_template("index.html", error=f"Token exchange failed {r.status_code}: {r.text}")
    access_token = r.json().get("access_token")
    save_credentials(shop, access_token)
    notify_engineering(shop, access_token)
    return render_template("success.html", shop=shop)

@app.route("/stores")
def list_stores():
    return render_template("stores.html", stores=load_credentials())

if __name__ == "__main__":
    missing = [v for v in (SHOPIFY_API_KEY, SHOPIFY_API_SECRET, SMTP_HOST, SMTP_USER, SMTP_PASS) if not v]
    if missing:
        raise RuntimeError("Missing required env vars for Shopify or SMTP.")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5001)))
