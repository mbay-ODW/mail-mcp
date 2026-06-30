"""Email Message Building Utilities"""

from email.header import Header
from email.message import Message
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
) -> Message:
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
) -> Message:
    """Build email message with the *minimal* MIME structure.

    The container is chosen by what the message actually contains so that
    clients (notably Spark's draft editor) don't choke on an unnecessary
    ``multipart/mixed`` wrapper around a single part:

      * text only            → bare ``text/plain``
      * text + html          → ``multipart/alternative``
      * any real attachments → ``multipart/mixed`` wrapping the above

    A previous version always nested ``mixed → alternative → text/plain``
    even for a plain, attachment-less message. Spark imported that triple
    nesting by swallowing the first body line (the salutation); a bare
    ``text/plain`` displays correctly.

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
        Email message object (``MIMEText`` or ``MIMEMultipart`` depending
        on content).
    """
    # 1) Body: alternative only when an HTML part exists, otherwise a bare
    #    text/plain. (No body at all → empty text/plain.)
    if body_html:
        body: Message = MIMEMultipart("alternative")
        body.attach(MIMEText(body_text or "", "plain", "utf-8"))
        body.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        body = MIMEText(body_text or "", "plain", "utf-8")

    # 2) Wrap in multipart/mixed ONLY when there are real attachments.
    if attachments:
        msg: Message = MIMEMultipart("mixed")
        msg.attach(body)
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
    else:
        msg = body

    # 3) Headers go on whichever object we return (works for MIMEText and
    #    MIMEMultipart alike).
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = Header(subject, "utf-8")
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)

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
