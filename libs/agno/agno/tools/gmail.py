"""
Gmail Toolkit for interacting with Gmail API

Required Environment Variables:
-----------------------------
- GOOGLE_CLIENT_ID: Google OAuth client ID
- GOOGLE_CLIENT_SECRET: Google OAuth client secret
- GOOGLE_PROJECT_ID: Google Cloud project ID
- GOOGLE_REDIRECT_URI: Google OAuth redirect URI (default: http://localhost)

How to Get These Credentials:
---------------------------
1. Go to Google Cloud Console (https://console.cloud.google.com)
2. Create a new project or select an existing one
3. Enable the Gmail API:
   - Go to "APIs & Services" > "Enable APIs and Services"
   - Search for "Gmail API"
   - Click "Enable"

4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Go through the OAuth consent screen setup
   - Give it a name and click "Create"
   - You'll receive:
     * Client ID (GOOGLE_CLIENT_ID)
     * Client Secret (GOOGLE_CLIENT_SECRET)
   - The Project ID (GOOGLE_PROJECT_ID) is visible in the project dropdown at the top of the page

5. Add auth redirect URI:
   - Go to https://console.cloud.google.com/auth/clients and add the redirect URI as http://127.0.0.1/

6. Set up environment variables:
   Create a .envrc file in your project root with:
   ```
   export GOOGLE_CLIENT_ID=your_client_id_here
   export GOOGLE_CLIENT_SECRET=your_client_secret_here
   export GOOGLE_PROJECT_ID=your_project_id_here
   export GOOGLE_REDIRECT_URI=http://127.0.0.1/  # Default value
   ```

Note: The first time you run the application, it will open a browser window for OAuth authentication.
A token.json file will be created to store the authentication credentials for future use.
"""

import base64
import json
import mimetypes
import re
import tempfile
from datetime import datetime, timedelta
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "Google client libraries not found, install: "
        "`pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")

_BATCH_MAX = 100
_BATCH_MODIFY_MAX = 1000
_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024


def validate_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


def authenticate(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(self: "GmailTools", *args: Any, **kwargs: Any) -> Any:
        if not self.creds or not self.creds.valid:
            self._auth()
        if not self.service:
            self.service = build("gmail", "v1", credentials=self.creds)
        return func(self, *args, **kwargs)

    return wrapper


class GmailTools(Toolkit):
    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.compose",
    ]

    COMPOSE_TOOLS = {"create_draft_email", "send_email", "send_email_reply", "update_draft", "send_draft"}
    READ_TOOLS = {
        "get_latest_emails",
        "get_emails_from_user",
        "get_unread_emails",
        "get_starred_emails",
        "get_emails_by_context",
        "get_emails_by_date",
        "get_emails_by_thread",
        "search_emails",
        "list_custom_labels",
        "get_message",
        "get_messages_batch",
        "get_thread",
        "search_threads",
        "get_threads_batch",
        "get_draft",
        "list_drafts",
        "download_attachment",
        "get_profile",
    }
    MODIFY_TOOLS = {
        "mark_email_as_read",
        "mark_email_as_unread",
        "apply_label",
        "remove_label",
        "delete_custom_label",
        "trash_message",
        "untrash_message",
        "modify_thread_labels",
        "trash_thread",
        "batch_modify_labels",
    }

    def __init__(
        self,
        creds: Optional[Credentials] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        port: Optional[int] = None,
        include_html: bool = False,
        max_body_length: Optional[int] = None,
        attachment_dir: Optional[str] = None,
        **kwargs: Any,
    ):
        self.creds = creds
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service: Optional[Resource] = None
        self.scopes = scopes or self.DEFAULT_SCOPES
        self.port = port
        self.include_html = include_html
        self.max_body_length = max_body_length
        self.attachment_dir = attachment_dir
        self._label_cache: Optional[Dict[str, str]] = None
        # Stable dir for batch downloads within a single session
        self._temp_dir: Optional[str] = None

        super().__init__(
            name="gmail_tools",
            tools=[
                self.get_latest_emails,
                self.get_emails_from_user,
                self.get_unread_emails,
                self.get_starred_emails,
                self.get_emails_by_context,
                self.get_emails_by_date,
                self.get_emails_by_thread,
                self.search_emails,
                self.mark_email_as_read,
                self.mark_email_as_unread,
                self.create_draft_email,
                self.send_email,
                self.send_email_reply,
                self.list_custom_labels,
                self.apply_label,
                self.remove_label,
                self.delete_custom_label,
                self.get_message,
                self.get_messages_batch,
                self.trash_message,
                self.untrash_message,
                self.download_attachment,
                self.get_thread,
                self.search_threads,
                self.get_threads_batch,
                self.modify_thread_labels,
                self.trash_thread,
                self.batch_modify_labels,
                self.get_draft,
                self.list_drafts,
                self.update_draft,
                self.send_draft,
                self.get_profile,
            ],
            **kwargs,
        )

        self._validate_scopes()

    def _validate_scopes(self) -> None:
        if any(m in self.functions for m in self.COMPOSE_TOOLS):
            if "https://www.googleapis.com/auth/gmail.compose" not in self.scopes:
                raise ValueError(
                    "The scope https://www.googleapis.com/auth/gmail.compose is required for email composition operations"
                )

        if any(m in self.functions for m in self.READ_TOOLS):
            read_scope = "https://www.googleapis.com/auth/gmail.readonly"
            write_scope = "https://www.googleapis.com/auth/gmail.modify"
            if read_scope not in self.scopes and write_scope not in self.scopes:
                raise ValueError(f"The scope {read_scope} is required for email reading operations")

        if any(m in self.functions for m in self.MODIFY_TOOLS):
            modify_scope = "https://www.googleapis.com/auth/gmail.modify"
            if modify_scope not in self.scopes:
                raise ValueError(f"The scope {modify_scope} is required for email modification operations")

    def _auth(self) -> None:
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": getenv("GOOGLE_CLIENT_ID"),
                        "client_secret": getenv("GOOGLE_CLIENT_SECRET"),
                        "project_id": getenv("GOOGLE_PROJECT_ID"),
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [getenv("GOOGLE_REDIRECT_URI", "http://localhost")],
                    }
                }
                if creds_file.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
                else:
                    flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
                self.creds = flow.run_local_server(port=self.port)

            if self.creds and self.creds.valid:
                token_file.write_text(self.creds.to_json())
                log_debug("Gmail credentials saved")

    def _get_header(self, headers: List[Dict[str, str]], name: str) -> Optional[str]:
        lower = name.lower()
        for h in headers:
            if h["name"].lower() == lower:
                return h["value"]
        return None

    def _strip_html(self, html: str) -> str:
        text = _HTML_TAG_RE.sub("", html)
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)

    def _decode_body_data(self, data: str) -> str:
        try:
            raw_bytes = base64.urlsafe_b64decode(data)
        except Exception:
            return ""
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1")

    def _truncate(self, text: str) -> str:
        if self.max_body_length and len(text) > self.max_body_length:
            return text[: self.max_body_length] + "... [truncated]"
        return text

    def _resolve_label_ids(self, label_names: List[str]) -> List[str]:
        if self._label_cache is None:
            service = cast(Resource, self.service)
            raw = service.users().labels().list(userId="me").execute()
            self._label_cache = {lbl["name"].lower(): lbl["id"] for lbl in raw.get("labels", [])}
            log_debug(f"Cached {len(self._label_cache)} Gmail labels")

        resolved = []
        for name in label_names:
            label_id = self._label_cache.get(name.lower()) or name
            resolved.append(label_id)
        return resolved

    def _invalidate_label_cache(self) -> None:
        self._label_cache = None

    def _get_attachment_dir(self) -> Path:
        if self.attachment_dir:
            dest = Path(self.attachment_dir)
        else:
            if self._temp_dir is None:
                self._temp_dir = tempfile.mkdtemp()
            dest = Path(self._temp_dir)
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    def _batch_get(
        self,
        ids: List[str],
        request_builder: Callable,
    ) -> List[Dict]:
        service = cast(Resource, self.service)
        results: List[Dict] = []

        def callback(request_id: str, response: Any, exception: Any) -> None:
            if exception:
                log_error(f"Batch request {request_id} failed: {exception}")
                results.append({"id": request_id, "error": str(exception)})
            else:
                results.append(response)

        for i in range(0, len(ids), _BATCH_MAX):
            chunk = ids[i : i + _BATCH_MAX]
            batch = service.new_batch_http_request(callback=callback)
            for item_id in chunk:
                batch.add(request_builder(item_id), request_id=item_id)
            batch.execute()
        return results

    def _download_attachment_file(self, message_id: str, attachment_id: str, filename: str) -> str:
        service = cast(Resource, self.service)
        att = (
            service.users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id).execute()
        )
        data = base64.urlsafe_b64decode(att["data"])
        dest_dir = self._get_attachment_dir()
        file_path = dest_dir / filename
        file_path.write_bytes(data)
        log_debug(f"Downloaded attachment: {file_path}")
        return str(file_path)

    def _format_message_json(self, msg_data: Dict, include_body: bool = True) -> Dict:
        headers = msg_data.get("payload", {}).get("headers", [])
        result: Dict[str, Any] = {
            "id": msg_data["id"],
            "threadId": msg_data.get("threadId"),
            "labelIds": msg_data.get("labelIds", []),
            "snippet": msg_data.get("snippet", ""),
            "subject": self._get_header(headers, "Subject"),
            "from": self._get_header(headers, "From"),
            "to": self._get_header(headers, "To"),
            "date": self._get_header(headers, "Date"),
            "cc": self._get_header(headers, "Cc"),
            "inReplyTo": self._get_header(headers, "In-Reply-To"),
            "references": self._get_header(headers, "References"),
        }
        if include_body and "payload" in msg_data:
            body, attachments = self._extract_body(msg_data["payload"])
            result["body"] = body
            if attachments:
                result["attachments"] = attachments
        return result

    def _extract_body(self, payload: Dict) -> Tuple[str, List[Dict]]:
        mime_type = payload.get("mimeType", "")

        if "parts" not in payload:
            data = payload.get("body", {}).get("data")
            if not data:
                return "", []
            decoded = self._decode_body_data(data)
            if mime_type == "text/html" and not self.include_html:
                decoded = self._strip_html(decoded)
            return self._truncate(decoded), []

        plain_parts: List[str] = []
        html_parts: List[str] = []
        attachments: List[Dict] = []

        for part in payload["parts"]:
            part_mime = part.get("mimeType", "")
            filename = part.get("filename", "")

            if filename:
                attachments.append(
                    {
                        "filename": filename,
                        "mimeType": part_mime,
                        "size": part.get("body", {}).get("size", 0),
                        "attachmentId": part.get("body", {}).get("attachmentId"),
                    }
                )
                continue

            if part_mime.startswith("multipart/") and "parts" in part:
                for subpart in part["parts"]:
                    sub_mime = subpart.get("mimeType", "")
                    sub_data = subpart.get("body", {}).get("data")
                    sub_filename = subpart.get("filename", "")
                    if sub_filename:
                        attachments.append(
                            {
                                "filename": sub_filename,
                                "mimeType": sub_mime,
                                "size": subpart.get("body", {}).get("size", 0),
                                "attachmentId": subpart.get("body", {}).get("attachmentId"),
                            }
                        )
                    elif sub_data and sub_mime == "text/plain":
                        plain_parts.append(self._decode_body_data(sub_data))
                    elif sub_data and sub_mime == "text/html":
                        html_parts.append(self._decode_body_data(sub_data))
                continue

            data = part.get("body", {}).get("data")
            if not data:
                continue

            if part_mime == "text/plain":
                plain_parts.append(self._decode_body_data(data))
            elif part_mime == "text/html":
                html_parts.append(self._decode_body_data(data))

        if plain_parts:
            body = "\n".join(plain_parts)
        elif html_parts:
            html = "\n".join(html_parts)
            body = html if self.include_html else self._strip_html(html)
        else:
            body = ""

        return self._truncate(body), attachments

    def _validate_attachments(self, attachments: Optional[Union[str, List[str]]]) -> List[str]:
        if not attachments:
            return []
        file_list = [attachments] if isinstance(attachments, str) else list(attachments)
        for file_path in file_list:
            if not Path(file_path).exists():
                raise ValueError(f"Attachment file not found: {file_path}")
        return file_list

    def _create_mime_message(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        thread_id: Optional[str] = None,
        message_id: Optional[str] = None,
        attachments: Optional[List[str]] = None,
    ) -> dict:
        body = body.replace("\\n", "\n")

        msg: Union[MIMEMultipart, MIMEText]
        if attachments:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "html"))
            for file_path in attachments:
                fp = Path(file_path)
                content_type, encoding = mimetypes.guess_type(str(fp))
                if content_type is None or encoding is not None:
                    content_type = "application/octet-stream"
                _, sub_type = content_type.split("/", 1)
                with open(fp, "rb") as f:
                    att = MIMEApplication(f.read(), _subtype=sub_type)
                att.add_header("Content-Disposition", "attachment", filename=fp.name)
                msg.attach(att)
        else:
            msg = MIMEText(body, "html")

        msg["to"] = ", ".join(to)
        msg["from"] = "me"
        msg["subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)

        if thread_id and message_id:
            msg["In-Reply-To"] = message_id
            msg["References"] = message_id

        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        email_data: Dict[str, str] = {"raw": raw_message}
        if thread_id:
            email_data["threadId"] = thread_id
        return email_data

    def _validate_email_params(self, to: str, subject: str, body: str) -> None:
        if not to:
            raise ValueError("Recipient email cannot be empty")
        for email_addr in to.split(","):
            if not validate_email(email_addr.strip()):
                raise ValueError(f"Invalid recipient email format: {email_addr}")
        if not subject or not subject.strip():
            raise ValueError("Subject cannot be empty")
        if body is None:
            raise ValueError("Email body cannot be None")

    def _format_emails(self, emails: List[dict]) -> str:
        if not emails:
            return "No emails found"

        formatted_emails = []
        for email_data in emails:
            formatted_email = (
                f"From: {email_data['from']}\n"
                f"Subject: {email_data['subject']}\n"
                f"Date: {email_data['date']}\n"
                f"Body: {email_data['body']}\n"
                f"Message ID: {email_data['id']}\n"
                f"In-Reply-To: {email_data['in-reply-to']}\n"
                f"References: {email_data['references']}\n"
                f"Thread ID: {email_data['thread_id']}\n"
                "----------------------------------------"
            )
            formatted_emails.append(formatted_email)

        return "\n\n".join(formatted_emails)

    def _get_message_details(self, messages: List[dict]) -> List[dict]:
        if not messages:
            return []

        service = cast(Resource, self.service)
        details = []
        for msg in messages:
            msg_data = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            headers = msg_data.get("payload", {}).get("headers", [])
            body, att_info = self._extract_body(msg_data.get("payload", {}))
            att_filenames = [a["filename"] for a in att_info if a.get("filename")]
            body_with_attachments = body
            if att_filenames:
                body_with_attachments = f"{body}\n\nAttachments: {', '.join(att_filenames)}"

            details.append(
                {
                    "id": msg_data["id"],
                    "thread_id": msg_data.get("threadId"),
                    "subject": self._get_header(headers, "Subject"),
                    "from": self._get_header(headers, "From"),
                    "date": self._get_header(headers, "Date"),
                    "in-reply-to": self._get_header(headers, "In-Reply-To"),
                    "references": self._get_header(headers, "References"),
                    "body": body_with_attachments,
                }
            )
        return details

    def _search_and_format(self, query: str, max_results: int, error_context: str) -> str:
        try:
            service = cast(Resource, self.service)
            results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except Exception as e:
            return f"Error retrieving {error_context}: {e}"

    def _find_label_id(self, label_name: str) -> Optional[str]:
        service = cast(Resource, self.service)
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        lower = label_name.lower()
        for label in labels:
            if label["name"].lower() == lower:
                return label["id"]
        return None

    @authenticate
    def get_latest_emails(self, count: int) -> str:
        """Get the latest X emails from the user's inbox.

        Args:
            count (int): Number of latest emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        try:
            service = cast(Resource, self.service)
            results = service.users().messages().list(userId="me", maxResults=count).execute()
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except Exception as e:
            return f"Error retrieving latest emails: {e}"

    @authenticate
    def get_emails_from_user(self, user: str, count: int) -> str:
        """Get X number of emails from a specific user (name or email).

        Args:
            user (str): Name or email address of the sender
            count (int): Maximum number of emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        query = f"from:{user}" if "@" in user else f"from:{user}*"
        return self._search_and_format(query, count, f"emails from {user}")

    @authenticate
    def get_unread_emails(self, count: int) -> str:
        """Get the X number of latest unread emails from the user's inbox.

        Args:
            count (int): Maximum number of unread emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        return self._search_and_format("is:unread", count, "unread emails")

    @authenticate
    def get_emails_by_thread(self, thread_id: str) -> str:
        """Retrieve all emails from a specific thread.

        Args:
            thread_id (str): The ID of the email thread.

        Returns:
            str: Formatted string containing email thread details.
        """
        try:
            service = cast(Resource, self.service)
            thread = service.users().threads().get(userId="me", id=thread_id).execute()
            messages = thread.get("messages", [])
            emails = self._get_message_details(messages)
            return self._format_emails(emails)
        except Exception as e:
            return f"Error retrieving emails from thread {thread_id}: {e}"

    @authenticate
    def get_starred_emails(self, count: int) -> str:
        """Get X number of starred emails from the user's inbox.

        Args:
            count (int): Maximum number of starred emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        return self._search_and_format("is:starred", count, "starred emails")

    @authenticate
    def get_emails_by_context(self, context: str, count: int) -> str:
        """Get X number of emails matching a specific context or search term.

        Args:
            context (str): Search term or context to match in emails
            count (int): Maximum number of emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        return self._search_and_format(context, count, f"emails by context '{context}'")

    @authenticate
    def get_emails_by_date(
        self, start_date: int, range_in_days: Optional[int] = None, num_emails: Optional[int] = 10
    ) -> str:
        """Get emails based on date range. start_date is an integer representing a unix timestamp

        Args:
            start_date (datetime): Start date for the query
            range_in_days (Optional[int]): Number of days to include in the range (default: None)
            num_emails (Optional[int]): Maximum number of emails to retrieve (default: 10)

        Returns:
            str: Formatted string containing email details
        """
        try:
            start_date_dt = datetime.fromtimestamp(start_date)
            if range_in_days:
                end_date = start_date_dt + timedelta(days=range_in_days)
                query = f"after:{start_date_dt.strftime('%Y/%m/%d')} before:{end_date.strftime('%Y/%m/%d')}"
            else:
                query = f"after:{start_date_dt.strftime('%Y/%m/%d')}"

            service = cast(Resource, self.service)
            results = service.users().messages().list(userId="me", q=query, maxResults=num_emails).execute()
            emails = self._get_message_details(results.get("messages", []))
            return self._format_emails(emails)
        except Exception as e:
            return f"Error retrieving emails by date: {e}"

    @authenticate
    def create_draft_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[Union[str, List[str]]] = None,
    ) -> str:
        """Create and save a draft email. to and cc are comma separated string of email ids
        Args:
            to (str): Comma separated string of recipient email addresses
            subject (str): Email subject
            body (str): Email body content
            cc (Optional[str]): Comma separated string of CC email addresses (optional)
            attachments (Optional[Union[str, List[str]]]): File path(s) for attachments (optional)

        Returns:
            str: Stringified dictionary containing draft email details including id
        """
        self._validate_email_params(to, subject, body)
        attachment_files = self._validate_attachments(attachments)

        message = self._create_mime_message(
            to.split(","), subject, body, cc.split(",") if cc else None, attachments=attachment_files or None
        )
        draft = {"message": message}
        service = cast(Resource, self.service)
        draft = service.users().drafts().create(userId="me", body=draft).execute()
        return str(draft)

    @authenticate
    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[Union[str, List[str]]] = None,
    ) -> str:
        """Send an email immediately. to and cc are comma separated string of email ids
        Args:
            to (str): Comma separated string of recipient email addresses
            subject (str): Email subject
            body (str): Email body content
            cc (Optional[str]): Comma separated string of CC email addresses (optional)
            attachments (Optional[Union[str, List[str]]]): File path(s) for attachments (optional)

        Returns:
            str: Stringified dictionary containing sent email details including id
        """
        self._validate_email_params(to, subject, body)
        attachment_files = self._validate_attachments(attachments)

        body = body.replace("\n", "<br>")
        message = self._create_mime_message(
            to.split(","), subject, body, cc.split(",") if cc else None, attachments=attachment_files or None
        )
        service = cast(Resource, self.service)
        result = service.users().messages().send(userId="me", body=message).execute()
        return str(result)

    @authenticate
    def send_email_reply(
        self,
        thread_id: str,
        message_id: str,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        attachments: Optional[Union[str, List[str]]] = None,
    ) -> str:
        """Respond to an existing email thread.

        Args:
            thread_id (str): The ID of the email thread to reply to.
            message_id (str): The ID of the email being replied to.
            to (str): Comma-separated recipient email addresses.
            subject (str): Email subject (prefixed with "Re:" if not already).
            body (str): Email body content.
            cc (Optional[str]): Comma-separated CC email addresses (optional).
            attachments (Optional[Union[str, List[str]]]): File path(s) for attachments (optional)

        Returns:
            str: Stringified dictionary containing sent email details including id.
        """
        self._validate_email_params(to, subject, body)
        attachment_files = self._validate_attachments(attachments)

        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        body = body.replace("\n", "<br>")
        message = self._create_mime_message(
            to.split(","),
            subject,
            body,
            cc.split(",") if cc else None,
            thread_id=thread_id,
            message_id=message_id,
            attachments=attachment_files or None,
        )
        service = cast(Resource, self.service)
        result = service.users().messages().send(userId="me", body=message).execute()
        return str(result)

    @authenticate
    def search_emails(self, query: str, count: int) -> str:
        """Get X number of emails based on a given natural text query.
        Searches in to, from, cc, subject and email body contents.

        Args:
            query (str): Natural language query to search for
            count (int): Number of emails to retrieve

        Returns:
            str: Formatted string containing email details
        """
        return self._search_and_format(query, count, f"emails with query '{query}'")

    @authenticate
    def mark_email_as_read(self, message_id: str) -> str:
        """Mark a specific email as read by removing the 'UNREAD' label.
        This is crucial for long polling scenarios to prevent processing the same email multiple times.

        Args:
            message_id (str): The ID of the message to mark as read

        Returns:
            str: Success message or error description
        """
        try:
            service = cast(Resource, self.service)
            service.users().messages().modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()
            return f"Successfully marked email {message_id} as read. Labels removed: UNREAD"
        except Exception as e:
            return f"Error marking email {message_id} as read: {e}"

    @authenticate
    def mark_email_as_unread(self, message_id: str) -> str:
        """Mark a specific email as unread by adding the 'UNREAD' label.
        This is useful for flagging emails that need attention or re-processing.

        Args:
            message_id (str): The ID of the message to mark as unread

        Returns:
            str: Success message or error description
        """
        try:
            service = cast(Resource, self.service)
            service.users().messages().modify(userId="me", id=message_id, body={"addLabelIds": ["UNREAD"]}).execute()
            return f"Successfully marked email {message_id} as unread. Labels added: UNREAD"
        except Exception as e:
            return f"Error marking email {message_id} as unread: {e}"

    @authenticate
    def list_custom_labels(self) -> str:
        """List only user-created custom labels (filters out system labels) in a numbered format.

        Returns:
            str: A numbered list of custom labels only
        """
        try:
            service = cast(Resource, self.service)
            results = service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])

            custom_labels = [label["name"] for label in labels if label.get("type") == "user"]

            if not custom_labels:
                return "No custom labels found.\nCreate labels using apply_label function!"

            numbered_labels = [f"{i}. {name}" for i, name in enumerate(custom_labels, 1)]
            return f"Your Custom Labels ({len(custom_labels)} total):\n\n" + "\n".join(numbered_labels)

        except HttpError as e:
            return f"Error fetching labels: {e}"

    @authenticate
    def apply_label(self, context: str, label_name: str, count: int = 10) -> str:
        """Find emails matching a context (search query) and apply a label, creating it if necessary.

        Args:
            context (str): Gmail search query (e.g., 'is:unread category:promotions')
            label_name (str): Name of the label to apply
            count (int): Maximum number of emails to process
        Returns:
            str: Summary of labeled emails
        """
        try:
            service = cast(Resource, self.service)
            results = service.users().messages().list(userId="me", q=context, maxResults=count).execute()

            messages = results.get("messages", [])
            if not messages:
                return f"No emails found matching: '{context}'"

            label_id = self._find_label_id(label_name)

            if not label_id:
                label = (
                    service.users()
                    .labels()
                    .create(
                        userId="me",
                        body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
                    )
                    .execute()
                )
                label_id = label["id"]
                self._invalidate_label_cache()

            for msg in messages:
                service.users().messages().modify(userId="me", id=msg["id"], body={"addLabelIds": [label_id]}).execute()

            return f"Applied label '{label_name}' to {len(messages)} emails matching '{context}'."

        except HttpError as e:
            return f"Error applying label '{label_name}': {e}"

    @authenticate
    def remove_label(self, context: str, label_name: str, count: int = 10) -> str:
        """Remove a label from emails matching a context (search query).

        Args:
            context (str): Gmail search query (e.g., 'is:unread category:promotions')
            label_name (str): Name of the label to remove
            count (int): Maximum number of emails to process
        Returns:
            str: Summary of emails with label removed
        """
        try:
            service = cast(Resource, self.service)
            label_id = self._find_label_id(label_name)

            if not label_id:
                return f"Label '{label_name}' not found."

            results = (
                service.users()
                .messages()
                .list(userId="me", q=f"{context} label:{label_name}", maxResults=count)
                .execute()
            )

            messages = results.get("messages", [])
            if not messages:
                return f"No emails found matching: '{context}' with label '{label_name}'"

            for msg in messages:
                service.users().messages().modify(
                    userId="me", id=msg["id"], body={"removeLabelIds": [label_id]}
                ).execute()

            return f"Removed label '{label_name}' from {len(messages)} emails matching '{context}'."

        except HttpError as e:
            return f"Error removing label '{label_name}': {e}"

    @authenticate
    def delete_custom_label(self, label_name: str, confirm: bool = False) -> str:
        """Delete a custom label (with safety confirmation).

        Args:
            label_name (str): Name of the label to delete
            confirm (bool): Must be True to actually delete the label
        Returns:
            str: Confirmation message or warning
        """
        if not confirm:
            return (
                f"LABEL DELETION REQUIRES CONFIRMATION. This will permanently delete the label "
                f"'{label_name}' from all emails. Set confirm=True to proceed."
            )

        try:
            service = cast(Resource, self.service)
            labels = service.users().labels().list(userId="me").execute().get("labels", [])
            target_label = None

            lower = label_name.lower()
            for label in labels:
                if label["name"].lower() == lower:
                    target_label = label
                    break

            if not target_label:
                return f"Label '{label_name}' not found."

            if target_label.get("type") != "user":
                return f"Cannot delete system label '{label_name}'. Only user-created labels can be deleted."

            service.users().labels().delete(userId="me", id=target_label["id"]).execute()
            self._invalidate_label_cache()
            return f"Successfully deleted label '{label_name}'. This label has been removed from all emails."

        except HttpError as e:
            return f"Error deleting label '{label_name}': {e}"

    @authenticate
    def get_message(self, message_id: str, download_attachments: bool = False) -> str:
        """Get a single email message by its ID with full content including headers, body, and attachment metadata.

        Args:
            message_id: The Gmail message ID.
            download_attachments: If True, download attachments to disk and include file paths in the response.

        Returns:
            JSON string with message content including id, threadId, subject, from, to, date, body, and attachments.
        """
        try:
            service = cast(Resource, self.service)
            raw = service.users().messages().get(userId="me", id=message_id, format="full").execute()
            result = self._format_message_json(raw)

            if download_attachments and result.get("attachments"):
                for att in result["attachments"]:
                    if att.get("attachmentId"):
                        att["localPath"] = self._download_attachment_file(
                            message_id, att["attachmentId"], att["filename"]
                        )

            return json.dumps(result)
        except HttpError as e:
            log_error(f"Failed to get message {message_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def get_messages_batch(self, message_ids: str, download_attachments: bool = False) -> str:
        """Get multiple email messages by their IDs in a single batch request. Much faster than fetching one at a time.

        Args:
            message_ids: Comma-separated list of Gmail message IDs (max 100).
            download_attachments: If True, download attachments to disk.

        Returns:
            JSON string with list of messages.
        """
        try:
            ids = [mid.strip() for mid in message_ids.split(",") if mid.strip()]
            if len(ids) > _BATCH_MAX:
                return json.dumps({"error": f"Maximum {_BATCH_MAX} messages per batch request"})

            service = cast(Resource, self.service)
            raw_messages = self._batch_get(
                ids, lambda msg_id: service.users().messages().get(userId="me", id=msg_id, format="full")
            )
            messages = []
            for m in raw_messages:
                if "error" in m:
                    messages.append(m)
                    continue
                formatted = self._format_message_json(m)
                if download_attachments and formatted.get("attachments"):
                    for att in formatted["attachments"]:
                        if att.get("attachmentId"):
                            att["localPath"] = self._download_attachment_file(
                                m["id"], att["attachmentId"], att["filename"]
                            )
                messages.append(formatted)

            return json.dumps({"messages": messages})
        except HttpError as e:
            log_error(f"Batch get messages failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def trash_message(self, message_id: str) -> str:
        """Move a message to the trash. The message can be restored with untrash_message within 30 days.

        Args:
            message_id: The Gmail message ID to trash.

        Returns:
            JSON string confirming the message was trashed.
        """
        try:
            service = cast(Resource, self.service)
            service.users().messages().trash(userId="me", id=message_id).execute()
            return json.dumps({"id": message_id, "action": "trashed"})
        except HttpError as e:
            log_error(f"Failed to trash message {message_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def untrash_message(self, message_id: str) -> str:
        """Restore a message from the trash back to the inbox.

        Args:
            message_id: The Gmail message ID to restore.

        Returns:
            JSON string confirming the message was restored.
        """
        try:
            service = cast(Resource, self.service)
            service.users().messages().untrash(userId="me", id=message_id).execute()
            return json.dumps({"id": message_id, "action": "untrashed"})
        except HttpError as e:
            log_error(f"Failed to untrash message {message_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def download_attachment(self, message_id: str, attachment_id: str, filename: str) -> str:
        """Download an email attachment to disk. Use get_message first to find attachment IDs.

        Args:
            message_id: The Gmail message ID containing the attachment.
            attachment_id: The attachment ID from the message's attachment metadata.
            filename: The filename to save the attachment as.

        Returns:
            JSON string with the local file path where the attachment was saved.
        """
        try:
            local_path = self._download_attachment_file(message_id, attachment_id, filename)
            return json.dumps({"localPath": local_path, "filename": filename, "messageId": message_id})
        except HttpError as e:
            log_error(f"Failed to download attachment from {message_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def get_thread(self, thread_id: str) -> str:
        """Get all messages in a Gmail thread as structured JSON. Unlike get_emails_by_thread which returns formatted text, this returns full structured data for each message.

        Args:
            thread_id: The Gmail thread ID.

        Returns:
            JSON string with thread metadata and all messages in chronological order.
        """
        try:
            service = cast(Resource, self.service)
            thread = service.users().threads().get(userId="me", id=thread_id).execute()
            messages = [self._format_message_json(m) for m in thread.get("messages", [])]
            return json.dumps(
                {
                    "threadId": thread_id,
                    "messages": messages,
                    "messageCount": len(messages),
                }
            )
        except HttpError as e:
            log_error(f"Failed to get thread {thread_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def search_threads(self, query: str, count: int = 10) -> str:
        """Search Gmail threads using Gmail query syntax. Returns thread IDs and snippets, not full message content.

        Args:
            query: Gmail search query string. Supports all Gmail operators like from:, to:, subject:, is:unread, has:attachment, etc.
            count: Maximum number of threads to return (default 10, max 500).

        Returns:
            JSON string with list of matching threads with their IDs and snippets.
        """
        try:
            service = cast(Resource, self.service)
            max_results = min(count, 500)
            results = service.users().threads().list(userId="me", q=query, maxResults=max_results).execute()
            threads = results.get("threads", [])
            return json.dumps(
                {
                    "threads": threads,
                    "resultSizeEstimate": results.get("resultSizeEstimate", len(threads)),
                }
            )
        except HttpError as e:
            log_error(f"Thread search failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def get_threads_batch(self, thread_ids: str) -> str:
        """Get multiple threads by their IDs in a single batch request. Each thread includes all its messages.

        Args:
            thread_ids: Comma-separated list of Gmail thread IDs (max 100).

        Returns:
            JSON string with list of threads, each containing all their messages.
        """
        try:
            ids = [tid.strip() for tid in thread_ids.split(",") if tid.strip()]
            if len(ids) > _BATCH_MAX:
                return json.dumps({"error": f"Maximum {_BATCH_MAX} threads per batch request"})

            service = cast(Resource, self.service)
            raw_threads = self._batch_get(
                ids, lambda tid: service.users().threads().get(userId="me", id=tid)
            )
            threads = []
            for t in raw_threads:
                if "error" in t:
                    threads.append(t)
                    continue
                messages = [self._format_message_json(m) for m in t.get("messages", [])]
                threads.append(
                    {
                        "threadId": t["id"],
                        "messages": messages,
                        "messageCount": len(messages),
                    }
                )
            return json.dumps({"threads": threads})
        except HttpError as e:
            log_error(f"Batch get threads failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def modify_thread_labels(
        self,
        thread_id: str,
        add_labels: Optional[str] = None,
        remove_labels: Optional[str] = None,
    ) -> str:
        """Add or remove labels from an entire thread (all messages in the conversation).

        Args:
            thread_id: The Gmail thread ID.
            add_labels: Comma-separated label names to add (e.g. 'STARRED,Important').
            remove_labels: Comma-separated label names to remove (e.g. 'UNREAD,INBOX').

        Returns:
            JSON string with updated thread label state.
        """
        try:
            body: Dict[str, List[str]] = {}
            if add_labels:
                names = [n.strip() for n in add_labels.split(",") if n.strip()]
                body["addLabelIds"] = self._resolve_label_ids(names)
            if remove_labels:
                names = [n.strip() for n in remove_labels.split(",") if n.strip()]
                body["removeLabelIds"] = self._resolve_label_ids(names)

            if not body:
                return json.dumps({"error": "Must specify add_labels or remove_labels"})

            service = cast(Resource, self.service)
            result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()
            return json.dumps({"threadId": result["id"], "labelIds": result.get("labelIds", [])})
        except HttpError as e:
            log_error(f"Failed to modify labels on thread {thread_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def trash_thread(self, thread_id: str) -> str:
        """Move an entire thread to the trash. All messages in the conversation will be trashed.

        Args:
            thread_id: The Gmail thread ID to trash.

        Returns:
            JSON string confirming the thread was trashed.
        """
        try:
            service = cast(Resource, self.service)
            service.users().threads().trash(userId="me", id=thread_id).execute()
            return json.dumps({"threadId": thread_id, "action": "trashed"})
        except HttpError as e:
            log_error(f"Failed to trash thread {thread_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def batch_modify_labels(
        self,
        message_ids: str,
        add_labels: Optional[str] = None,
        remove_labels: Optional[str] = None,
    ) -> str:
        """Apply label changes to multiple messages at once using Gmail's batchModify API. Much more efficient than modifying one message at a time.

        Args:
            message_ids: Comma-separated list of Gmail message IDs (max 1000).
            add_labels: Comma-separated label names to add.
            remove_labels: Comma-separated label names to remove.

        Returns:
            JSON string confirming the batch operation.
        """
        try:
            ids = [mid.strip() for mid in message_ids.split(",") if mid.strip()]
            if len(ids) > _BATCH_MODIFY_MAX:
                return json.dumps({"error": f"Maximum {_BATCH_MODIFY_MAX} messages per batch modify"})

            body: Dict[str, Any] = {"ids": ids}
            if add_labels:
                names = [n.strip() for n in add_labels.split(",") if n.strip()]
                body["addLabelIds"] = self._resolve_label_ids(names)
            if remove_labels:
                names = [n.strip() for n in remove_labels.split(",") if n.strip()]
                body["removeLabelIds"] = self._resolve_label_ids(names)

            if "addLabelIds" not in body and "removeLabelIds" not in body:
                return json.dumps({"error": "Must specify add_labels or remove_labels"})

            service = cast(Resource, self.service)
            service.users().messages().batchModify(userId="me", body=body).execute()
            return json.dumps(
                {
                    "modified": len(ids),
                    "addedLabels": body.get("addLabelIds", []),
                    "removedLabels": body.get("removeLabelIds", []),
                }
            )
        except HttpError as e:
            log_error(f"Batch modify labels failed: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def get_draft(self, draft_id: str) -> str:
        """Get a draft email by its ID with full content.

        Args:
            draft_id: The Gmail draft ID.

        Returns:
            JSON string with draft details including the message content.
        """
        try:
            service = cast(Resource, self.service)
            draft = service.users().drafts().get(userId="me", id=draft_id, format="full").execute()
            msg_data = draft.get("message", {})
            result: Dict[str, Any] = {
                "draftId": draft["id"],
                "message": self._format_message_json(msg_data) if msg_data else {},
            }
            return json.dumps(result)
        except HttpError as e:
            log_error(f"Failed to get draft {draft_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def list_drafts(self, count: int = 20) -> str:
        """List draft emails in the user's mailbox.

        Args:
            count: Maximum number of drafts to return (default 20, max 500).

        Returns:
            JSON string with list of drafts including their IDs and message snippets.
        """
        try:
            service = cast(Resource, self.service)
            max_results = min(count, 500)
            results = service.users().drafts().list(userId="me", maxResults=max_results).execute()
            drafts = results.get("drafts", [])
            return json.dumps({"drafts": drafts, "resultSizeEstimate": results.get("resultSizeEstimate", len(drafts))})
        except HttpError as e:
            log_error(f"Failed to list drafts: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def update_draft(
        self,
        draft_id: str,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
        bcc: Optional[str] = None,
        attachments: Optional[str] = None,
    ) -> str:
        """Update an existing draft email with new content.

        Args:
            draft_id: The Gmail draft ID to update.
            to: Comma-separated recipient email addresses.
            subject: Email subject line.
            body: Email body content (supports HTML).
            cc: Comma-separated CC email addresses.
            bcc: Comma-separated BCC email addresses.
            attachments: Comma-separated file paths for attachments (max 25MB each).

        Returns:
            JSON string with updated draft details.
        """
        try:
            att_list = None
            if attachments:
                att_list = [a.strip() for a in attachments.split(",") if a.strip()]
                for fp in att_list:
                    if not Path(fp).exists():
                        return json.dumps({"error": f"Attachment not found: {fp}"})
                    if Path(fp).stat().st_size > _ATTACHMENT_MAX_BYTES:
                        return json.dumps({"error": f"Attachment exceeds 25MB: {fp}"})

            mime = self._create_mime_message(
                to=[t.strip() for t in to.split(",")],
                subject=subject,
                body=body.replace("\n", "<br>"),
                cc=[c.strip() for c in cc.split(",")] if cc else None,
                bcc=[b.strip() for b in bcc.split(",")] if bcc else None,
                attachments=att_list,
            )

            service = cast(Resource, self.service)
            result = service.users().drafts().update(userId="me", id=draft_id, body={"message": mime}).execute()
            return json.dumps({"draftId": result["id"], "action": "updated"})
        except HttpError as e:
            log_error(f"Failed to update draft {draft_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def send_draft(self, draft_id: str) -> str:
        """Send an existing draft email immediately.

        Args:
            draft_id: The Gmail draft ID to send.

        Returns:
            JSON string with sent message details including id and threadId.
        """
        try:
            service = cast(Resource, self.service)
            result = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
            return json.dumps(
                {
                    "id": result.get("id"),
                    "threadId": result.get("threadId"),
                    "labelIds": result.get("labelIds", []),
                    "action": "sent",
                }
            )
        except HttpError as e:
            log_error(f"Failed to send draft {draft_id}: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})

    @authenticate
    def get_profile(self) -> str:
        """Get the authenticated user's Gmail profile including email address, total messages, and history ID.

        Returns:
            JSON string with profile details: emailAddress, messagesTotal, threadsTotal, historyId.
        """
        try:
            service = cast(Resource, self.service)
            profile = service.users().getProfile(userId="me").execute()
            return json.dumps(profile)
        except HttpError as e:
            log_error(f"Failed to get profile: {e}")
            return json.dumps({"error": f"Gmail API error: {e}"})
