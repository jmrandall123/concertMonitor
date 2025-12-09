"""Email service for sending digests and notifications."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


@dataclass
class EmailConfig:
    """Email service configuration."""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "Concert Monitor"
    use_tls: bool = True


@dataclass
class EmailMessage:
    """Email message to send."""
    to_email: str
    subject: str
    html_content: str
    plain_content: Optional[str] = None
    attachments: list[tuple[str, str, str]] = field(default_factory=list)  # (filename, content, mime_type)


class EmailService:
    """Service for sending emails."""

    def __init__(self, config: Optional[EmailConfig] = None):
        self.config = config or EmailConfig()

    async def send_email(self, message: EmailMessage) -> bool:
        """Send an email message."""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = message.subject
            msg["From"] = f"{self.config.from_name} <{self.config.from_email}>"
            msg["To"] = message.to_email

            # Add plain text version
            if message.plain_content:
                plain_part = MIMEText(message.plain_content, "plain")
                msg.attach(plain_part)

            # Add HTML version
            html_part = MIMEText(message.html_content, "html")
            msg.attach(html_part)

            # Add attachments
            for filename, content, mime_type in message.attachments:
                attachment = MIMEText(content)
                attachment.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=filename
                )
                msg.attach(attachment)

            # Send email
            if self.config.username and self.config.password:
                await aiosmtplib.send(
                    msg,
                    hostname=self.config.smtp_host,
                    port=self.config.smtp_port,
                    username=self.config.username,
                    password=self.config.password,
                    start_tls=self.config.use_tls,
                )
                logger.info(f"Email sent to {message.to_email}")
                return True
            else:
                # Mock mode - just log
                logger.info(f"Would send email to {message.to_email}: {message.subject}")
                return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False


class DigestEmailBuilder:
    """Builder for creating digest email content."""

    def __init__(self):
        self.styles = """
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
            .container { max-width: 600px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; }
            .header h1 { margin: 0; font-size: 24px; }
            .content { background: #f8f9fa; padding: 20px; }
            .event-card { background: white; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .event-title { font-size: 18px; font-weight: 600; color: #1a1a2e; margin: 0 0 8px 0; }
            .event-meta { color: #666; font-size: 14px; margin-bottom: 8px; }
            .event-rating { display: inline-block; background: #667eea; color: white; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }
            .event-rating.high { background: #10b981; }
            .event-rating.medium { background: #f59e0b; }
            .event-explanation { font-size: 13px; color: #555; margin-top: 12px; padding-top: 12px; border-top: 1px solid #eee; }
            .cta-button { display: inline-block; background: #667eea; color: white; padding: 10px 20px; border-radius: 5px; text-decoration: none; margin-top: 10px; }
            .section-title { font-size: 16px; font-weight: 600; color: #1a1a2e; margin: 24px 0 16px 0; padding-bottom: 8px; border-bottom: 2px solid #667eea; }
            .footer { text-align: center; padding: 20px; color: #888; font-size: 12px; }
        </style>
        """

    def build_digest(
        self,
        user_name: str,
        must_see_events: list[dict],
        recommended_events: list[dict],
        might_enjoy_events: list[dict],
        period: str = "This Week",
    ) -> str:
        """Build the complete digest email HTML."""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            {self.styles}
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎵 Your Concert Digest</h1>
                    <p style="margin: 10px 0 0 0; opacity: 0.9;">{period}'s personalized recommendations</p>
                </div>
                <div class="content">
                    <p>Hey {user_name}! 👋</p>
                    <p>We found some amazing events that match your taste. Here's what's coming up:</p>
        """

        # Must See section (8+)
        if must_see_events:
            html += '<div class="section-title">🔥 Must See Events</div>'
            for event in must_see_events:
                html += self._build_event_card(event, "high")

        # Recommended section (7-7.9)
        if recommended_events:
            html += '<div class="section-title">⭐ Recommended For You</div>'
            for event in recommended_events:
                html += self._build_event_card(event, "medium")

        # Might Enjoy section (5-6.9)
        if might_enjoy_events:
            html += '<div class="section-title">💡 You Might Also Enjoy</div>'
            for event in might_enjoy_events[:5]:  # Limit to 5
                html += self._build_event_card(event, "")

        html += """
                </div>
                <div class="footer">
                    <p>You're receiving this because you signed up for Concert Monitor.</p>
                    <p><a href="#">Manage preferences</a> | <a href="#">Unsubscribe</a></p>
                </div>
            </div>
        </body>
        </html>
        """

        return html

    def _build_event_card(self, event: dict, rating_class: str) -> str:
        """Build HTML for a single event card."""
        rating = event.get("rating", 0)
        rating_text = f"{rating}/10"

        return f"""
        <div class="event-card">
            <h3 class="event-title">{event.get('name', 'Unknown Event')}</h3>
            <div class="event-meta">
                📅 {event.get('date', 'Date TBD')}<br>
                📍 {event.get('location', 'Location TBD')}
                {f"<br>💰 {event.get('price', '')}" if event.get('price') else ""}
            </div>
            <span class="event-rating {rating_class}">{rating_text} match</span>
            <div class="event-explanation">
                {event.get('explanation', '')}
            </div>
            <a href="{event.get('ticket_url', '#')}" class="cta-button">Get Tickets</a>
        </div>
        """

    def build_plain_text(
        self,
        user_name: str,
        events: list[dict],
        period: str = "This Week",
    ) -> str:
        """Build plain text version of digest."""
        lines = [
            f"🎵 Your Concert Digest - {period}",
            "=" * 40,
            f"",
            f"Hey {user_name}!",
            f"",
            f"Here are your personalized concert recommendations:",
            f"",
        ]

        for event in events:
            lines.extend([
                f"• {event.get('name', 'Unknown Event')}",
                f"  📅 {event.get('date', 'Date TBD')}",
                f"  📍 {event.get('location', 'Location TBD')}",
                f"  Rating: {event.get('rating', 0)}/10",
                f"  {event.get('ticket_url', '')}",
                f"",
            ])

        lines.extend([
            "=" * 40,
            "Manage preferences or unsubscribe at concertmonitor.com",
        ])

        return "\n".join(lines)
