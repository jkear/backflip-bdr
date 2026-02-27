"""Google Calendar tools for Google ADK agents."""
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _service():
    creds_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)


def get_free_slots(
    duration_minutes: int = 30,
    days_ahead: int = 7,
    calendar_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Get available time slots from Declan's calendar.

    Args:
        duration_minutes: Desired meeting length in minutes.
        days_ahead: How many calendar days ahead to look.
        calendar_id: Google Calendar ID (defaults to env DECLAN_CALENDAR_ID).

    Returns:
        Dict with 'slots' list of available windows.
    """
    cal_id = calendar_id or os.environ["DECLAN_CALENDAR_ID"]
    now_chicago = datetime.now(ZoneInfo("America/Chicago"))
    now_utc = now_chicago.astimezone(timezone.utc)
    time_max = now_utc + timedelta(days=days_ahead)

    try:
        service = _service()
        body = {
            "timeMin": now_utc.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": cal_id}],
        }
        result = service.freebusy().query(body=body).execute()
        busy_periods = result.get("calendars", {}).get(cal_id, {}).get("busy", [])

        # Build candidate slots: 9am–5pm on business days (America/Chicago)
        slots = []
        cursor = now_chicago.replace(hour=9, minute=0, second=0, microsecond=0)
        if cursor < now_chicago:
            cursor += timedelta(days=1)

        while cursor < time_max and len(slots) < 10:
            if cursor.weekday() < 5:  # Mon–Fri
                for hour in [9, 10, 11, 14, 15, 16]:
                    candidate_start = cursor.replace(hour=hour, minute=0)
                    candidate_end = candidate_start + timedelta(minutes=duration_minutes)
                    if candidate_end > time_max:
                        continue
                    # Check against busy periods
                    conflict = False
                    for busy in busy_periods:
                        b_start = datetime.fromisoformat(busy["start"])
                        b_end = datetime.fromisoformat(busy["end"])
                        if candidate_start < b_end and candidate_end > b_start:
                            conflict = True
                            break
                    if not conflict:
                        slots.append({
                            "start_datetime": candidate_start.isoformat(),
                            "end_datetime": candidate_end.isoformat(),
                            "timezone": "America/Chicago",
                        })
                        if len(slots) >= 6:
                            break
            cursor += timedelta(days=1)

        # Return 3 diverse slots (morning, afternoon spread)
        selected = slots[:3] if len(slots) >= 3 else slots
        return {"slots": selected, "calendar_id": cal_id}
    except Exception as exc:
        return {"slots": [], "error": str(exc)}


def create_event(
    title: str,
    start_datetime: str,
    end_datetime: str,
    attendee_email: str,
    description: str = "",
    timezone: str = "America/Chicago",
    calendar_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Google Calendar event and send invite to the attendee.

    Args:
        title: Event title.
        start_datetime: ISO 8601 start datetime.
        end_datetime: ISO 8601 end datetime.
        attendee_email: Lead's email address to invite.
        description: Event description / agenda.
        timezone: Timezone string (default: America/Chicago).
        calendar_id: Host calendar ID (defaults to env DECLAN_CALENDAR_ID).

    Returns:
        Dict with 'event_id', 'html_link', 'status'.
    """
    cal_id = calendar_id or os.environ["DECLAN_CALENDAR_ID"]
    event_body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_datetime, "timeZone": timezone},
        "end": {"dateTime": end_datetime, "timeZone": timezone},
        "attendees": [{"email": attendee_email}],
        "conferenceData": {
            "createRequest": {
                "requestId": f"backflip-{attendee_email.replace('@', '-')}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        "sendUpdates": "all",
    }
    try:
        service = _service()
        created = (
            service.events()
            .insert(
                calendarId=cal_id,
                body=event_body,
                conferenceDataVersion=1,
                sendNotifications=True,
            )
            .execute()
        )
        return {
            "event_id": created.get("id", ""),
            "html_link": created.get("htmlLink", ""),
            "meet_link": (
                created.get("conferenceData", {})
                .get("entryPoints", [{}])[0]
                .get("uri", "")
            ),
            "status": created.get("status", "confirmed"),
        }
    except Exception as exc:
        return {"event_id": "", "status": "error", "error": str(exc)}


def get_event(event_id: str, calendar_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch a calendar event by ID to verify it was created.

    Args:
        event_id: Google Calendar event ID.
        calendar_id: Calendar ID (defaults to env DECLAN_CALENDAR_ID).

    Returns:
        Dict with event details or error.
    """
    cal_id = calendar_id or os.environ["DECLAN_CALENDAR_ID"]
    try:
        service = _service()
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()
        return {
            "event_id": event.get("id"),
            "summary": event.get("summary"),
            "status": event.get("status"),
            "start": event.get("start", {}).get("dateTime"),
            "attendees": [a.get("email") for a in event.get("attendees", [])],
            "verified": True,
        }
    except Exception as exc:
        return {"event_id": event_id, "verified": False, "error": str(exc)}
