"""Repository layer for the Backflip SDR pipeline.

Provides CRUD, dedup, and query methods for core CRM entities:
- organizations: get_by_domain, get_known_domains, upsert, update_stage,
                 get_in_event_window, get_due_for_outreach
- contacts: get_by_email, get_known_emails, upsert, is_suppressed
- events: upsert, get_upcoming_events, get_by_org
"""
