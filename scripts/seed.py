#!/usr/bin/env python3
"""Seed the database with mock support docs and tickets for demo purposes.

Usage:
    python scripts/seed.py          # uses .env config
    python scripts/seed.py --clear  # drop existing data first
"""

import argparse
import sys
import time
import uuid
from datetime import datetime, timedelta

# Must import config before anything else to load .env
from app.config import settings

from openai import OpenAI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

client = OpenAI(api_key=settings.openai_api_key)

DOCUMENTS = [
    {
        "title": "Refund Policy",
        "type": "help_center",
        "chunks": [
            {
                "heading": "Annual Plans",
                "content": "Customers on annual plans may request a full refund within 30 days of purchase. After 30 days, refunds are prorated based on the remaining months in the billing cycle. To request a refund, contact our billing team at billing@example.com with your account number and reason for the request. Processing time is 5-10 business days.",
            },
            {
                "heading": "Monthly Plans",
                "content": "Monthly subscriptions can be cancelled at any time from your account settings. Refunds for the current billing period are provided on a prorated basis. If you were charged in error, please contact support within 7 days of the charge for a full adjustment. No refunds are issued for partial months after cancellation.",
            },
            {
                "heading": "Refund Processing",
                "content": "Refunds are processed within 5-10 business days after approval. The refund will be credited to the original payment method. For credit card payments, allow an additional 2-3 business days for the refund to appear on your statement. For PayPal, refunds are typically instant once processed.",
            },
        ],
    },
    {
        "title": "Account Recovery Guide",
        "type": "help_center",
        "chunks": [
            {
                "heading": "Reset Password",
                "content": "To reset your password, visit the login page and click 'Forgot Password'. Enter your email address and you will receive a password reset link within 5 minutes. The link expires after 1 hour. If you do not receive the email, check your spam folder or contact support to verify your email address.",
            },
            {
                "heading": "Account Locked",
                "content": "Your account will be temporarily locked after 5 failed login attempts. The lock lasts 30 minutes. If you need immediate access, you can unlock your account by verifying your identity through the recovery email. If you are unable to regain access, contact our support team with your account email and a government-issued ID.",
            },
            {
                "heading": "Two-Factor Authentication",
                "content": "If you lose access to your two-factor authentication device, use one of the backup codes provided during setup. Each code can be used once. If you have exhausted all backup codes, you will need to contact support and verify your identity through an alternative method, which may take 24-48 hours.",
            },
        ],
    },
    {
        "title": "Billing FAQ",
        "type": "help_center",
        "chunks": [
            {
                "heading": "Payment Methods",
                "content": "We accept Visa, Mastercard, American Express, Discover, and PayPal. You can manage your payment methods from the Billing section of your account settings. To add a new payment method, navigate to Settings > Billing > Payment Methods and click 'Add Payment Method'.",
            },
            {
                "heading": "Invoice Requests",
                "content": "Invoices for past payments can be downloaded from your account's billing history page. If you need a custom invoice with specific tax information, submit a request to billing@example.com with your company name, tax ID, and the billing period. Custom invoices are generated within 2-3 business days.",
            },
            {
                "heading": "Upgrade Mid-Cycle",
                "content": "When you upgrade your plan mid-cycle, the price difference is prorated for the remaining days in your current billing period. The upgraded features are available immediately. Your next billing date will remain the same; the new full price will apply starting the next billing cycle.",
            },
        ],
    },
]

TICKETS = [
    {
        "customer_id": "cust-001",
        "subject": "Charged twice for my monthly plan",
        "description": "I was charged $99 twice on the same day for my monthly plan. This is the second time this has happened. I need this resolved immediately and a refund for the duplicate charge.",
        "category": "billing",
        "priority": "high",
        "sentiment": "negative",
        "confidence": 0.92,
        "summary": "Customer was charged duplicate $99 for monthly plan",
        "status": "resolved",
        "requires_escalation": False,
        "draft_response": "I apologize for the duplicate charge. I have issued a full refund of $99 for the erroneous charge. The refund will appear within 5-10 business days. We have also added a flag to your account to prevent duplicate charges in the future.",
        "resolved_at_offset": 2,
        "messages": [
            ("customer", "I was charged twice! This is unacceptable."),
            ("agent", "I apologize for the inconvenience. I am looking into this now."),
            ("agent", "I have confirmed the duplicate charge and processed a refund."),
        ],
    },
    {
        "customer_id": "cust-002",
        "subject": "How do I reset my password?",
        "description": "I forgot my password and need to reset it. I tried clicking 'Forgot Password' on the login page but I'm not receiving the email. Can you help?",
        "category": "account",
        "priority": "low",
        "sentiment": "neutral",
        "confidence": 0.87,
        "summary": "Customer unable to reset password, not receiving recovery email",
        "status": "resolved",
        "requires_escalation": False,
        "draft_response": "Please check your spam folder for the password reset email. If it's not there, your email may have a typo or the account may be registered under a different address. Try resetting from an incognito window. If the issue persists, verify your account email by contacting support with your full name and account details.",
        "resolved_at_offset": 1,
        "messages": [
            ("customer", "I can't seem to reset my password."),
            ("agent", "Let me help you with that. Have you checked your spam folder?"),
        ],
    },
    {
        "customer_id": "cust-003",
        "subject": "Account locked — need immediate access",
        "description": "My account has been locked after too many failed login attempts and I urgently need to access my account for an important client meeting in 30 minutes. Nobody else has access to my account. This is costing me money every minute.",
        "category": "account",
        "priority": "critical",
        "sentiment": "negative",
        "confidence": 0.45,
        "summary": "Account locked before critical client meeting",
        "status": "open",
        "requires_escalation": True,
        "draft_response": "I understand this is urgent. Your account was locked due to 5 failed login attempts. The lock will automatically expire in 30 minutes. If you need immediate access, I can escalate this to our senior support team who can manually verify your identity.",
        "resolved_at_offset": None,
        "messages": [
            ("customer", "I need my account unlocked right now!"),
        ],
    },
    {
        "customer_id": "cust-004",
        "subject": "Suspicious login from unknown IP address",
        "description": "I received an email notification about a login attempt from an IP address in Russia. I am based in Canada and have never traveled there. This is very concerning. I need my account secured immediately.",
        "category": "technical",
        "priority": "critical",
        "sentiment": "negative",
        "confidence": 0.52,
        "summary": "Unauthorized access attempt detected from foreign IP",
        "status": "open",
        "requires_escalation": True,
        "draft_response": "This is a security concern. I have temporarily suspended your account to prevent unauthorized access. Please reset your password immediately using the 'Forgot Password' link. Enable two-factor authentication after logging back in. Our security team will investigate the login attempt and follow up within 24 hours.",
        "resolved_at_offset": None,
        "messages": [
            ("customer", "Someone is trying to break into my account!"),
            ("agent", "I have locked your account as a precaution. Let me escalate this to our security team."),
        ],
    },
    {
        "customer_id": "cust-005",
        "subject": "Can I upgrade my plan mid-cycle?",
        "description": "I'm currently on the Starter plan and want to upgrade to Professional. I just paid for this month a week ago. Will I lose the money I already paid? How does the pricing work for mid-cycle upgrades?",
        "category": "billing",
        "priority": "medium",
        "sentiment": "positive",
        "confidence": 0.91,
        "summary": "Customer inquiring about mid-cycle plan upgrade pricing",
        "status": "resolved",
        "requires_escalation": False,
        "draft_response": "Great news! When you upgrade mid-cycle, we prorate the price difference for the remaining days in your billing period. So you won't lose the money you already paid — you'll only be charged the difference. The upgrade takes effect immediately and your next billing date stays the same.",
        "resolved_at_offset": 1,
        "messages": [
            ("customer", "I'd like to upgrade my plan. How does billing work?"),
            ("agent", "We prorate the difference! You won't lose anything."),
        ],
    },
    {
        "customer_id": "cust-006",
        "subject": "Mobile app crashes on startup",
        "description": "Every time I open the mobile app on my iPhone 15, it crashes immediately after the splash screen. I've tried reinstalling the app, restarting my phone, and ensuring I'm on the latest iOS version. Nothing works.",
        "category": "technical",
        "priority": "high",
        "sentiment": "negative",
        "confidence": 0.78,
        "summary": "iOS app crashing immediately after splash screen",
        "status": "processing",
        "requires_escalation": False,
        "draft_response": "I'm sorry about the crash. This is a known issue affecting some iOS 17 users with the latest app version. Our engineering team has identified the bug and a fix is scheduled for the next release (v3.2.1), expected within 48 hours. In the meantime, please use the web version at app.example.com.",
        "resolved_at_offset": None,
        "messages": [
            ("customer", "App keeps crashing, very frustrating."),
        ],
    },
    {
        "customer_id": "cust-007",
        "subject": "Need invoice for tax purposes",
        "description": "I need a detailed invoice for all my payments in 2025 for my annual tax filing. I need it broken down by month with the service description and tax amounts included. I need this by end of week.",
        "category": "billing",
        "priority": "low",
        "sentiment": "neutral",
        "confidence": 0.95,
        "summary": "Customer requesting detailed 2025 invoice for tax filing",
        "status": "processing",
        "requires_escalation": False,
        "draft_response": "You can download invoices for past payments from your account's Billing History page. If you need a consolidated annual statement with tax details, please email billing@example.com with your account email and '2025 Annual Invoice Request' in the subject line. Our billing team will generate it within 2 business days.",
        "resolved_at_offset": None,
        "messages": [
            ("customer", "I need my invoices for tax season."),
        ],
    },
    {
        "customer_id": "cust-008",
        "subject": "Team member can't accept invite",
        "description": "I invited a new team member to our workspace 3 days ago but they still haven't received the invite email. I've tried resending twice. Their email is jane@example.co and I confirmed it's spelled correctly.",
        "category": "account",
        "priority": "medium",
        "sentiment": "neutral",
        "confidence": 0.88,
        "summary": "Team invite email not being delivered after multiple attempts",
        "status": "approved",
        "requires_escalation": False,
        "draft_response": "Invite emails sometimes get caught by spam filters. Ask your team member to check their spam folder. If it's not there, the email domain example.co may have strict filtering. I've manually added jane@example.co to your workspace — they can now log in directly using the 'Forgot Password' flow to set up their account.",
        "resolved_at_offset": 1,
        "messages": [
            ("customer", "My new hire can't accept the workspace invite."),
            ("agent", "Let me check the invite status and resend it."),
        ],
    },
]


def embed_text(text: str) -> list[float]:
    resp = client.embeddings.create(model=settings.embedding_model, input=text)
    return resp.data[0].embedding


def seed_documents(session: Session) -> list[str]:
    """Create support documents with embedded chunks. Returns list of source IDs."""
    source_ids = []
    now = datetime.utcnow()

    for doc in DOCUMENTS:
        source_id = str(uuid.uuid4())
        source_ids.append(source_id)

        session.execute(
            text("""
                INSERT INTO document_sources (id, title, source_type, metadata, created_at)
                VALUES (:id, :title, :type, '{}'::json, :created_at)
            """),
            {"id": source_id, "title": doc["title"], "type": doc["type"], "created_at": now},
        )

        for i, chunk in enumerate(doc["chunks"]):
            chunk_id = str(uuid.uuid4())
            embedding = embed_text(chunk["content"])
            tokens = len(chunk["content"].split())

            session.execute(
                text("""
                    INSERT INTO document_chunks (id, source_id, chunk_index, content, heading, tokens, embedding, metadata, created_at)
                    VALUES (:id, :source_id, :chunk_index, :content, :heading, :tokens, :embedding::vector, '{}'::json, :created_at)
                """),
                {
                    "id": chunk_id,
                    "source_id": source_id,
                    "chunk_index": i,
                    "content": chunk["content"],
                    "heading": chunk["heading"],
                    "tokens": tokens,
                    "embedding": str(embedding),
                    "created_at": now,
                },
            )

        print(f"  ✓ {doc['title']} ({len(doc['chunks'])} chunks)")

    return source_ids


def seed_tickets(session: Session):
    """Create mock tickets with classifications and messages."""
    now = datetime.utcnow()

    for i, td in enumerate(TICKETS):
        ticket_id = str(uuid.uuid4())
        created_at = now - timedelta(days=len(TICKETS) - i, hours=i)
        resolved_at = (
            created_at + timedelta(hours=td["resolved_at_offset"])
            if td["resolved_at_offset"]
            else None
        )

        session.execute(
            text("""
                INSERT INTO tickets (id, customer_id, subject, description, category, priority,
                    sentiment, confidence, summary, status, draft_response, requires_escalation, metadata, created_at, resolved_at)
                VALUES (:id, :customer_id, :subject, :description, :category, :priority,
                    :sentiment, :confidence, :summary, :status, :draft_response, :requires_escalation, '{}'::json, :created_at, :resolved_at)
            """),
            {
                "id": ticket_id,
                "customer_id": td["customer_id"],
                "subject": td["subject"],
                "description": td["description"],
                "category": td["category"],
                "priority": td["priority"],
                "sentiment": td["sentiment"],
                "confidence": td["confidence"],
                "summary": td["summary"],
                "status": td["status"],
                "draft_response": td["draft_response"],
                "requires_escalation": td.get("requires_escalation", False),
                "created_at": created_at,
                "resolved_at": resolved_at,
            },
        )

        for j, (role, content) in enumerate(td["messages"]):
            msg_id = str(uuid.uuid4())
            msg_time = created_at + timedelta(minutes=30 * (j + 1))
            session.execute(
                text("""
                    INSERT INTO ticket_messages (id, ticket_id, role, content, created_at)
                    VALUES (:id, :ticket_id, :role, :content, :created_at)
                """),
                {
                    "id": msg_id,
                    "ticket_id": ticket_id,
                    "role": role,
                    "content": content,
                    "created_at": msg_time,
                },
            )

        status_icon = {"resolved": "✓", "open": "⚡", "processing": "⋯", "approved": "✓"}.get(
            td["status"], "?"
        )
        esc = " [ESCALATED]" if td.get("requires_escalation") else ""
        print(f"  {status_icon} {td['subject'][:55]:55s} {td['category']:10s} {td['priority']:9s} {td['status']:10s}{esc}")


def clear_data(session: Session):
    print("Clearing existing data...")
    session.execute(text("DELETE FROM ticket_messages"))
    session.execute(text("DELETE FROM tickets"))
    session.execute(text("DELETE FROM document_chunks"))
    session.execute(text("DELETE FROM document_sources"))
    session.commit()
    print("  ✓ All data cleared")


def main():
    parser = argparse.ArgumentParser(description="Seed the database with demo data")
    parser.add_argument("--clear", action="store_true", help="Clear existing data first")
    args = parser.parse_args()

    if not settings.openai_api_key or settings.openai_api_key == "sk-...":
        print("❌ OPENAI_API_KEY not set in .env")
        sys.exit(1)

    db_url = settings.database_url_sync
    engine = create_engine(db_url)

    print("Connecting to database...")
    try:
        conn = engine.connect()
        conn.close()
    except Exception as e:
        print(f"❌ Cannot connect to database: {e}")
        print("   Make sure PostgreSQL + pgvector is running (docker compose up -d db)")
        sys.exit(1)

    print(f"\nDatabase: {db_url.split('@')[1] if '@' in db_url else db_url}")

    with Session(engine) as session:
        if args.clear:
            clear_data(session)

        print("\n━━━ Documents ━━━")
        seed_documents(session)
        session.commit()

        print("\n━━━ Tickets ━━━")
        seed_tickets(session)
        session.commit()

    print(f"\n✅ Seed complete. {len(DOCUMENTS)} documents, {len(TICKETS)} tickets created.")
    print(f"   Start the app: uvicorn app.main:app --reload")
    print(f"   Open browser:  http://localhost:8000")


if __name__ == "__main__":
    main()
