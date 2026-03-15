"""Email Message Building Utilities"""

from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .. import Attachment


def build_email_message(
    sender: str,
    to: list[str],
    subject: str,
    body_text: str | None = None,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[Attachment] | None = None,
) -> MIMEMultipart:
    """Build a basic email message.

    This is a convenience function that wraps the more complete build_message
    from the send module.

    Args:
        sender: Sender email address
        to: List of recipient addresses
        subject: Email subject
        body_text: Plain text body
        body_html: HTML body
        cc: CC recipients
        bcc: BCC recipients
        attachments: List of attachments

    Returns:
        MIMEMultipart message object
    """
    return build_message(
        sender=sender,
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        cc=cc,
        bcc=bcc,
        attachments=attachments,
    )


def build_message(
    sender: str,
    to: list[str],
    subject: str,
    body_text: str | None = None,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[Attachment] | None = None,
) -> MIMEMultipart:
    """Build email message.

    Args:
        sender: Sender email address
        to: List of recipient addresses
        subject: Email subject
        body_text: Plain text body
        body_html: HTML body
        cc: CC recipients
        bcc: BCC recipients
        attachments: List of attachments

    Returns:
        MIMEMultipart message object
    """
    # Combine all recipients
    all_recipients = to.copy()
    if cc:
        all_recipients.extend(cc)
    if bcc:
        all_recipients.extend(bcc)

    # Create message
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = Header(subject, "utf-8")

    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)

    # Add body parts
    if body_text or body_html:
        body_container = MIMEMultipart("alternative")

        if body_text:
            text_part = MIMEText(body_text, "plain", "utf-8")
            body_container.attach(text_part)

        if body_html:
            html_part = MIMEText(body_html, "html", "utf-8")
            body_container.attach(html_part)

        msg.attach(body_container)

    # Add attachments
    if attachments:
        for att in attachments:
            if att.content_type.startswith("image/"):
                part = MIMEImage(att.data, name=att.filename)
            elif att.content_type == "application/pdf":
                part = MIMEApplication(att.data, name=att.filename, _subtype="pdf")
            else:
                part = MIMEApplication(att.data, name=att.filename)

            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=att.filename,
            )
            part.add_header("Content-Type", att.content_type)
            msg.attach(part)

    return msg


def create_plain_text_message(
    sender: str,
    to: list[str],
    subject: str,
    body: str,
) -> MIMEText:
    """Create a simple plain text message.

    Args:
        sender: Sender email address
        to: List of recipient addresses
        subject: Email subject
        body: Plain text body

    Returns:
        MIMEText message object
    """
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = Header(subject, "utf-8")
    return msg


def create_html_message(
    sender: str,
    to: list[str],
    subject: str,
    html_body: str,
    plain_text_fallback: str | None = None,
) -> MIMEMultipart:
    """Create an HTML message with optional plain text fallback.

    Args:
        sender: Sender email address
        to: List of recipient addresses
        subject: Email subject
        html_body: HTML body
        plain_text_fallback: Optional plain text version

    Returns:
        MIMEMultipart message object
    """
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = Header(subject, "utf-8")

    if plain_text_fallback:
        msg.attach(MIMEText(plain_text_fallback, "plain", "utf-8"))

    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


__all__ = [
    "build_email_message",
    "create_plain_text_message",
    "create_html_message",
]
