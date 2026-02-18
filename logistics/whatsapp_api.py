from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass
from urllib import request, error

from django.conf import settings


@dataclass
class WhatsAppSendResult:
    ok: bool
    message_id: str | None = None
    error: str | None = None


def _api_version() -> str:
    return str(getattr(settings, 'WHATSAPP_API_VERSION', 'v21.0')).strip() or 'v21.0'


def _base_url() -> str:
    custom = str(getattr(settings, 'WHATSAPP_API_BASE_URL', '') or '').strip()
    if custom:
        return custom.rstrip('/')
    return f"https://graph.facebook.com/{_api_version()}"


def _phone_number_id() -> str:
    return str(getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '') or '').strip()


def _token() -> str:
    return str(getattr(settings, 'WHATSAPP_API_TOKEN', '') or '').strip()


def _is_enabled() -> bool:
    return bool(_phone_number_id() and _token())


def _auth_headers(content_type: str | None = None) -> dict:
    headers = {
        'Authorization': f"Bearer {_token()}",
    }
    if content_type:
        headers['Content-Type'] = content_type
    return headers


def _multipart_form_data(fields: dict[str, str], file_field: str, filename: str, file_bytes: bytes, mime_type: str):
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode('utf-8'))
        body.extend((value or '').encode('utf-8'))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode('utf-8'))
    body.extend(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode('utf-8')
    )
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode('utf-8'))
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode('utf-8'))

    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _upload_media(*, filename: str, file_bytes: bytes, mime_type: str) -> tuple[bool, str | None, str | None]:
    if not _is_enabled():
        return False, None, 'WhatsApp API is not configured.'

    upload_url = f"{_base_url()}/{_phone_number_id()}/media"
    payload, content_type = _multipart_form_data(
        fields={'messaging_product': 'whatsapp'},
        file_field='file',
        filename=filename,
        file_bytes=file_bytes,
        mime_type=mime_type,
    )

    req = request.Request(upload_url, data=payload, method='POST', headers=_auth_headers(content_type))

    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            data = json.loads(raw or '{}')
            media_id = data.get('id')
            if media_id:
                return True, str(media_id), None
            return False, None, 'No media id returned by WhatsApp API.'
    except error.HTTPError as exc:
        try:
            details = exc.read().decode('utf-8')
        except Exception:
            details = str(exc)
        return False, None, f"HTTP {exc.code}: {details}"
    except Exception as exc:
        return False, None, str(exc)


def send_whatsapp_document(*, to_phone: str, caption: str, filename: str, file_bytes: bytes, mime_type: str):
    if not _is_enabled():
        return WhatsAppSendResult(ok=False, error='WhatsApp API is not configured.')

    safe_filename = filename or 'document.pdf'
    safe_mime = mime_type or mimetypes.guess_type(safe_filename)[0] or 'application/octet-stream'

    uploaded, media_id, upload_error = _upload_media(
        filename=safe_filename,
        file_bytes=file_bytes,
        mime_type=safe_mime,
    )
    if not uploaded or not media_id:
        return WhatsAppSendResult(ok=False, error=upload_error or 'Failed to upload media.')

    send_url = f"{_base_url()}/{_phone_number_id()}/messages"
    payload = {
        'messaging_product': 'whatsapp',
        'to': str(to_phone or '').strip(),
        'type': 'document',
        'document': {
            'id': media_id,
            'caption': caption or '',
            'filename': safe_filename,
        },
    }

    req = request.Request(
        send_url,
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers=_auth_headers('application/json'),
    )

    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            data = json.loads(raw or '{}')
            message_id = None
            messages = data.get('messages') or []
            if messages and isinstance(messages, list):
                message_id = messages[0].get('id')
            return WhatsAppSendResult(ok=True, message_id=message_id)
    except error.HTTPError as exc:
        try:
            details = exc.read().decode('utf-8')
        except Exception:
            details = str(exc)
        return WhatsAppSendResult(ok=False, error=f"HTTP {exc.code}: {details}")
    except Exception as exc:
        return WhatsAppSendResult(ok=False, error=str(exc))
