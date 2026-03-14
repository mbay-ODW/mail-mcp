"""
Email fetch operations for IMAP MCP server.

Provides functionality to retrieve emails including:
- Headers only
- Full email (headers + body)
- Specific body parts (text, html)
- Attachments metadata
- Email structure
"""

from typing import Dict, Any, Optional, List, Union
from email.message import Message
from email.parser import BytesParser
from email.policy import default
import base64
import quopri


class EmailFetchError(Exception):
    """Base exception for email fetch operations."""
    pass


class EmailFetch:
    """
    Handles email fetching operations.
    
    Provides methods to retrieve emails with different levels
    of detail from the IMAP server.
    
    Attributes:
        _conn: IMAP connection instance
    """
    
    def __init__(self, connection) -> None:
        """
        Initialize EmailFetch with an IMAP connection.
        
        Args:
            connection: An active IMAP connection
        """
        self._conn = connection
        self._parser = BytesParser(policy=default)
    
    def _select_folder(self, folder: str) -> Dict[str, Any]:
        """
        Select a folder and return its metadata.
        
        Args:
            folder: Folder name
            
        Returns:
            Dictionary with folder metadata
            
        Raises:
            EmailFetchError: If selection fails
        """
        response = self._conn.select(folder)
        status = response[0]
        if status not in ('OK', b'OK') and not isinstance(status, int):
            error_msg = response[1][0].decode('utf-8', errors='replace') if response[1] else 'Unknown error'
            raise EmailFetchError(f"Failed to select folder '{folder}': {error_msg}")
        
        # Parse response data
        data = response[1][0]
        if isinstance(data, bytes):
            data = data.decode('utf-8', errors='replace')
        
        # Parse EXISTS, RECENT, UNSEEN
        metadata = {}
        import re
        
        exists_match = re.search(r'(\d+)\s+EXISTS', data, re.IGNORECASE)
        recent_match = re.search(r'(\d+)\s+RECENT', data, re.IGNORECASE)
        unseen_match = re.search(r'UNSEEN\s+(\d+)', data, re.IGNORECASE)
        
        if exists_match:
            metadata['exists'] = int(exists_match.group(1))
        if recent_match:
            metadata['recent'] = int(recent_match.group(1))
        if unseen_match:
            metadata['unseen'] = int(unseen_match.group(1))
        
        return metadata
    
    def get_email(
        self,
        folder: str,
        uid: int,
        headers_only: bool = False,
        decode_bodies: bool = True
    ) -> Dict[str, Any]:
        """
        Fetch a single email.
        
        Args:
            folder: Folder containing the email
            uid: Email sequence number or UID
            headers_only: If True, fetch only headers (default: False)
            decode_bodies: If True, decode quoted-printable/base64 (default: True)
            
        Returns:
            Dictionary containing:
            - uid: Email UID
            - sequence_number: Sequence number
            - headers: Email headers as dict
            - subject: Subject line
            - from: From address
            - to: To addresses
            - date: Date header
            - message_id: Message-ID
            - body: Body text (if not headers_only)
            - html: HTML body (if available)
            - attachments: List of attachments (if any)
            
        Raises:
            EmailFetchError: If fetch fails
            
        Example:
            >>> fetch = EmailFetch(conn)
            >>> email = fetch.get_email('INBOX', 1)
            >>> print(email['subject'])
            'Test Email'
        """
        if not folder:
            raise EmailFetchError("Folder name is required")
        
        if uid is None or uid < 1:
            raise EmailFetchError("Invalid email UID")
        
        try:
            # Select the folder
            self._select_folder(folder)
            
            # Build fetch command
            if headers_only:
                fetch_items = '(BODY[HEADER])'
            else:
                fetch_items = '(BODY[])'
            
            # Execute fetch
            response = self._conn.fetch(str(uid), fetch_items)
            
            if status not in ('OK', b'OK') and not isinstance(status, int):
                error_msg = response[1][0].decode('utf-8', errors='replace') if response[1] else 'Unknown error'
                
                if 'no message' in error_msg.lower() or 'not found' in error_msg.lower():
                    raise EmailFetchError(f"Email {uid} not found in folder '{folder}'")
                
                raise EmailFetchError(f"Failed to fetch email: {error_msg}")
            
            # Parse response
            return self._parse_fetch_response(response, uid, decode_bodies)
            
        except EmailFetchError:
            raise
        except Exception as e:
            raise EmailFetchError(f"Failed to fetch email: {str(e)}")
    
    def _parse_fetch_response(
        self, 
        response: tuple, 
        uid: int,
        decode_bodies: bool = True
    ) -> Dict[str, Any]:
        """
        Parse IMAP FETCH response.
        
        Args:
            response: Tuple from IMAP fetch command
            uid: Email sequence number
            decode_bodies: Whether to decode body content
            
        Returns:
            Dictionary with email data
        """
        if not response or len(response) < 2:
            return self._empty_email(uid)
        
        # Get the data
        data_items = response[1]
        if not data_items:
            return self._empty_email(uid)
        
        # Find the data portion (contains actual email content)
        raw_data = None
        for item in data_items:
            if isinstance(item, tuple) and len(item) >= 2:
                # Check if second element is bytes with email content
                if isinstance(item[1], bytes):
                    raw_data = item[1]
                    break
        
        if not raw_data:
            return self._empty_email(uid)
        
        # Parse email
        try:
            email_message = self._parser.parsebytes(raw_data)
        except Exception:
            return self._empty_email(uid)
        
        # Extract headers
        headers = {}
        for key, value in email_message.items():
            headers[key.lower()] = value
        
        # Build result
        result = {
            'uid': uid,
            'sequence_number': uid,
            'headers': headers,
            'subject': headers.get('subject', ''),
            'from': headers.get('from', ''),
            'to': headers.get('to', ''),
            'cc': headers.get('cc', ''),
            'bcc': headers.get('bcc', ''),
            'date': headers.get('date', ''),
            'message_id': headers.get('message-id', ''),
            'in_reply_to': headers.get('in-reply-to', ''),
            'references': headers.get('references', ''),
            'reply_to': headers.get('reply-to', ''),
            'mime_type': headers.get('content-type', ''),
        }
        
        # Add body if requested
        if decode_bodies:
            body_result = self._extract_body(email_message)
            result.update(body_result)
        
        return result
    
    def _extract_body(self, email_message: Message) -> Dict[str, Any]:
        """
        Extract body content from email message.
        
        Args:
            email_message: Parsed email message
            
        Returns:
            Dictionary with body, html, and attachments
        """
        result = {
            'body': '',
            'html': '',
            'attachments': [],
        }
        
        # Handle multipart
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = part.get('Content-Disposition', '')
                
                # Handle attachments
                if 'attachment' in content_disposition:
                    attachment = self._extract_attachment(part)
                    if attachment:
                        result['attachments'].append(attachment)
                    continue
                
                # Handle inline parts
                if content_type == 'text/plain':
                    body = self._decode_body(part)
                    if body and not result['body']:
                        result['body'] = body
                        
                elif content_type == 'text/html':
                    html = self._decode_body(part)
                    if html and not result['html']:
                        result['html'] = html
        
        else:
            # Single part email
            content_type = email_message.get_content_type()
            
            if content_type == 'text/plain':
                result['body'] = self._decode_body(email_message)
            elif content_type == 'text/html':
                result['html'] = self._decode_body(email_message)
        
        return result
    
    def _decode_body(self, part: Message) -> str:
        """
        Decode body content from email part.
        
        Args:
            part: Email part
            
        Returns:
            Decoded body string
        """
        try:
            payload = part.get_payload(decode=True)
            if not payload:
                return ''
            
            # Decode based on content transfer encoding
            encoding = part.get('Content-Transfer-Encoding', '').lower()
            
            if encoding == 'base64':
                # Already decoded by get_payload(decode=True)
                pass
            elif encoding == 'quoted-printable':
                # Already decoded by get_payload(decode=True)
                pass
            
            # Try to decode as UTF-8, fallback to latin-1
            try:
                return payload.decode('utf-8')
            except UnicodeDecodeError:
                return payload.decode('latin-1', errors='replace')
                
        except Exception:
            return ''
    
    def _extract_attachment(self, part: Message) -> Optional[Dict[str, Any]]:
        """
        Extract attachment metadata.
        
        Args:
            part: Email part containing attachment
            
        Returns:
            Dictionary with attachment info or None
        """
        try:
            filename = part.get_filename()
            if not filename:
                return None
            
            # Handle encoded filenames
            if filename.startswith('=?'):
                # Try to decode encoded word
                import email.header
                try:
                    filename = str(email.header.make_header(
                        email.header.decode_header(filename)
                    ))
                except Exception:
                    pass
            
            content_type = part.get_content_type()
            
            # Get payload
            payload = part.get_payload(decode=True)
            if payload:
                size = len(payload)
            else:
                size = 0
            
            return {
                'filename': filename,
                'content_type': content_type,
                'size': size,
            }
            
        except Exception:
            return None
    
    def _empty_email(self, uid: int) -> Dict[str, Any]:
        """
        Create empty email result.
        
        Args:
            uid: Email UID
            
        Returns:
            Empty email dictionary
        """
        return {
            'uid': uid,
            'sequence_number': uid,
            'headers': {},
            'subject': '',
            'from': '',
            'to': '',
            'cc': '',
            'bcc': '',
            'date': '',
            'message_id': '',
            'body': '',
            'html': '',
            'attachments': [],
        }
    
    def get_headers(
        self,
        folder: str,
        uid: int
    ) -> Dict[str, str]:
        """
        Fetch only headers for an email.
        
        Convenience method for fetching headers only.
        
        Args:
            folder: Folder containing the email
            uid: Email sequence number
            
        Returns:
            Dictionary of headers
        """
        email = self.get_email(folder, uid, headers_only=True)
        return email.get('headers', {})
    
    def get_attachment_info(
        self,
        folder: str,
        uid: int
    ) -> List[Dict[str, Any]]:
        """
        Get information about attachments in an email.
        
        Args:
            folder: Folder containing the email
            uid: Email sequence number
            
        Returns:
            List of attachment metadata dictionaries
        """
        email = self.get_email(folder, uid, headers_only=False)
        return email.get('attachments', [])


# Convenience functions
def get_email(connection, folder: str, uid: int, **kwargs) -> Dict[str, Any]:
    """
    Fetch an email using connection.
    
    Args:
        connection: IMAP connection
        folder: Folder name
        uid: Email UID
        **kwargs: Additional arguments for get_email
        
    Returns:
        Email data dictionary
    """
    fetcher = EmailFetch(connection)
    return fetcher.get_email(folder, uid, **kwargs)


__all__ = [
    'EmailFetchError',
    'EmailFetch',
    'get_email',
]