"""
Standard SMTP Email Service for Basketball Portrait Studio Pro
Sends invitation and login activation emails with dev preview fallback.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "noreply@portraitstudio.pro")
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "false").lower() in ("1", "true", "yes")


def is_smtp_configured() -> bool:
    """Returns True if SMTP environment credentials are set."""
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


def send_invitation_email(
    recipient_email: str,
    recipient_name: str,
    company_name: str,
    invite_token: str,
    base_url: str = "http://localhost:8080"
) -> dict:
    """
    Sends an account invitation email with a secure password setup link.
    If SMTP is not configured, logs the activation link in console and returns simulated=True.
    """
    clean_base = base_url.rstrip("/")
    activation_url = f"{clean_base}/#activate?token={invite_token}"

    subject = f"You're invited to join {company_name} on VeloRoster AI"
    display_name = recipient_name.strip() or "Team Member"

    # HTML Email Template
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #090d16; color: #f3f4f6; margin: 0; padding: 24px; }}
        .card {{ max-width: 540px; margin: 0 auto; background: #111827; border: 1px solid #1f293d; border-radius: 8px; padding: 36px 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        .badge {{ display: inline-block; background: rgba(255, 87, 34, 0.15); border: 1px solid rgba(255, 87, 34, 0.35); color: #ff7043; padding: 4px 12px; border-radius: 4px; font-size: 12px; font-weight: 700; margin-bottom: 20px; text-transform: uppercase; letter-spacing: 0.05em; }}
        h1 {{ font-size: 20px; font-weight: 800; color: #ffffff; margin-top: 0; margin-bottom: 12px; }}
        p {{ font-size: 14px; line-height: 1.6; color: #9ca3af; margin-bottom: 24px; }}
        .btn {{ display: inline-block; background: linear-gradient(135deg, #ff5722 0%, #ea580c 100%); color: #ffffff !important; text-decoration: none; padding: 13px 32px; border-radius: 6px; font-weight: 700; font-size: 14px; box-shadow: 0 4px 14px rgba(255,87,34,0.35); }}
        .btn:hover {{ opacity: 0.95; }}
        .url-box {{ margin-top: 24px; padding: 12px; background: #060911; border: 1px solid #1e293b; border-radius: 4px; font-family: monospace; font-size: 12px; color: #38bdf8; word-break: break-all; }}
        .footer {{ margin-top: 32px; font-size: 12px; color: #6b7280; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="badge">VeloRoster AI &bull; Ecstaticloud Technologies</div>
        <h1>Welcome, {display_name}!</h1>
        <p>
          You have been invited by <strong>{company_name}</strong> to access <strong>VeloRoster AI</strong>.
          You can now search athletic player portraits, ingest team rosters, assign player numbers, and standardize photos into 180×180 transparent headshots.
        </p>
        <div style="text-align: center; margin: 32px 0;">
          <a href="{activation_url}" class="btn" target="_blank">Set Password & Activate Account</a>
        </div>
        <p style="font-size: 13px; color: #6b7280;">
          If the button above does not work, copy and paste this link into your browser:
        </p>
        <div class="url-box">{activation_url}</div>
        <div class="footer">
          This invitation link expires in 7 days.<br>
          &copy; 2026 Ecstaticloud Technologies. VeloRoster AI&trade; is proprietary commercial software. All rights reserved.
        </div>
      </div>
    </body>
    </html>
    """

    plain_body = f"""Hello {display_name},

You have been invited by {company_name} to access VeloRoster AI (Commercial Athletic Media & Roster Studio).

To activate your account and choose your password, please open the following link:
{activation_url}

This invitation link expires in 7 days.
&copy; 2026 Ecstaticloud Technologies. VeloRoster AI is proprietary commercial software.
"""

    if not is_smtp_configured():
        print("=" * 70)
        print(f"[VeloRoster AI Email Engine] To: {recipient_email}")
        print(f"Activation Link: {activation_url}")
        print("=" * 70)
        return {
            "status": "ok",
            "sent": False,
            "simulated": True,
            "recipient": recipient_email,
            "activation_url": activation_url,
            "note": "SMTP credentials not configured. Invitation link generated and logged."
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"VeloRoster AI by Ecstaticloud Technologies <{SMTP_FROM}>"
        msg["To"] = recipient_email

        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        if SMTP_USE_SSL or SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, [recipient_email], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, [recipient_email], msg.as_string())

        print(f"[SaaS Email] ✅ Successfully sent invitation email to {recipient_email} via SMTP ({SMTP_HOST}).")
        return {
            "status": "ok",
            "sent": True,
            "simulated": False,
            "recipient": recipient_email,
            "activation_url": activation_url
        }
    except Exception as e:
        print(f"[SaaS Email Error] Failed to send email via SMTP ({e}). Falling back to manual link.")
        return {
            "status": "warning",
            "sent": False,
            "simulated": True,
            "error": str(e),
            "recipient": recipient_email,
            "activation_url": activation_url
        }
