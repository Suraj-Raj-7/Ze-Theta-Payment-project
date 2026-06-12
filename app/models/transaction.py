# app/models/transaction.py

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, BigInteger, Integer,
    DateTime, Float, Enum, JSON, Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import enum
from app.database import Base

class TransactionStatus(str, enum.Enum):
    """
    All valid states a transaction can be in.
    Using Python Enum means only these exact values
    are ever allowed — typos are impossible.
    CREATED = "CREATED" means the string stored in DB
    is literally "CREATED".
    """
    CREATED = "CREATED"
    ROUTE_SELECTED = "ROUTE_SELECTED"
    ROUTE_FAILED = "ROUTE_FAILED"
    AUTH_INITIATED = "AUTH_INITIATED"
    AUTHORISED = "AUTHORISED"
    AUTH_FAILED = "AUTH_FAILED"
    AUTH_TIMEOUT = "AUTH_TIMEOUT"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    CAPTURE_INITIATED = "CAPTURE_INITIATED"
    CAPTURED = "CAPTURED"
    PARTIALLY_CAPTURED = "PARTIALLY_CAPTURED"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    VOID_INITIATED = "VOID_INITIATED"
    VOIDED = "VOIDED"
    REFUND_INITIATED = "REFUND_INITIATED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUND_FAILED = "REFUND_FAILED"
    SETTLED = "SETTLED"
    DISPUTE_OPENED = "DISPUTE_OPENED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class PaymentMethod(str, enum.Enum):
    """Valid payment methods"""
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    WALLET = "wallet"


class GatewayName(str, enum.Enum):
    """Valid gateway names"""
    RAZORPAY = "razorpay"
    STRIPE = "stripe"
    PAYU = "payu"
    UPI = "upi"
    
class Transaction(Base):
    """
    The core table. Every payment in the system is one row here.
    'Base' is from database.py — it tells SQLAlchemy this class
    is a database table, not just a regular Python class.
    """
    __tablename__ = "transactions"

    # ─────────────────────────────────────────
    # IDENTITY
    # ─────────────────────────────────────────

    # UUID primary key — more secure than auto-increment integers
    # because IDs can't be guessed (1, 2, 3... is guessable)
    # default=uuid.uuid4 means Python generates a new UUID
    # automatically every time a Transaction is created
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False
    )

    # The merchant's own order ID (e.g. "ORDER_SW123456")
    # We store this so we can look up a payment by order ID
    # index=True makes queries on this column fast
    merchant_order_id = Column(String(255), nullable=False, index=True)

    # Client-generated key to prevent double charges
    # unique=True means no two rows can have the same key
    # nullable=True because old transactions may not have it
    idempotency_key = Column(String(255), unique=True, nullable=True)

    # ─────────────────────────────────────────
    # MONEY — stored as integer paise, NEVER float
    # ─────────────────────────────────────────

    # ₹450.00 is stored as 45000 (paise)
    # BigInteger supports up to 9,223,372,036,854,775,807 paise
    # That's ₹92 trillion — more than enough
    amount = Column(BigInteger, nullable=False)

    # Always store currency with amount
    # "INR", "USD" etc. Default INR for our Indian payment system
    currency = Column(String(10), nullable=False, default="INR")

    # ─────────────────────────────────────────
    # STATE — the heart of the state machine
    # ─────────────────────────────────────────

    # Current state of this transaction
    # Stored as a string in DB ("CREATED", "CAPTURED" etc.)
    # index=True because we frequently query by status
    # e.g. "find all AUTH_INITIATED transactions older than 5 min"
    status = Column(
        Enum(TransactionStatus),
        nullable=False,
        default=TransactionStatus.CREATED,
        index=True
    )

    # ─────────────────────────────────────────
    # GATEWAY — which gateway handled this
    # ─────────────────────────────────────────

    # Which gateway was selected by our routing algorithm
    # nullable=True because at CREATED state, no gateway selected yet
    gateway = Column(Enum(GatewayName), nullable=True)

    # ID the gateway assigned to our order when we initiated payment
    # We need this to call capture/refund later
    gateway_order_id = Column(String(255), nullable=True)

    # ID the gateway assigned after payment was processed
    # This appears in webhooks — we use it to match webhooks to transactions
    gateway_payment_id = Column(String(255), nullable=True, index=True)

    # How many times we've tried gateways
    # If this is 3, we tried 3 different gateways
    attempt_count = Column(Integer, nullable=False, default=0)

    # Score the router gave the selected gateway
    # Stored for analytics — helps us understand routing decisions later
    routing_score = Column(Float, nullable=True)

    # ─────────────────────────────────────────
    # PAYMENT METHOD
    # ─────────────────────────────────────────

    # "upi", "card", "netbanking", "wallet"
    payment_method = Column(Enum(PaymentMethod), nullable=False)

    # Flexible JSON for method-specific details
    # Card: {"last4": "4242", "brand": "visa", "exp_month": 12}
    # UPI:  {"vpa": "user@paytm"}
    # JSONB is PostgreSQL's binary JSON — faster to query than plain JSON
    payment_method_details = Column(JSONB, nullable=True)

    # ─────────────────────────────────────────
    # ERROR TRACKING
    # ─────────────────────────────────────────

    # Human-readable failure reason
    # "INSUFFICIENT_FUNDS", "GATEWAY_TIMEOUT", "FRAUD_DETECTED"
    failure_reason = Column(String(500), nullable=True)

    # Raw error code from gateway — kept separate so we can
    # map multiple gateway codes to one internal code
    gateway_error_code = Column(String(255), nullable=True)

    # ─────────────────────────────────────────
    # TIMESTAMPS
    # ─────────────────────────────────────────

    # server_default=func.now() means PostgreSQL sets this automatically
    # when the row is inserted — more reliable than Python's datetime.now()
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # onupdate=func.now() means PostgreSQL updates this automatically
    # every time the row changes — we never need to set it manually
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Exact moment money was captured — needed for settlement timing
    captured_at = Column(DateTime(timezone=True), nullable=True)

    # When the auth hold expires (typically 7 days after auth)
    # After this, AUTHORISED → AUTH_EXPIRED automatically
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # ─────────────────────────────────────────
    # TRACING & METADATA
    # ─────────────────────────────────────────

    # Unique ID that follows this payment through every log,
    # every service, every webhook. One search finds everything.
    trace_id = Column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        nullable=False
    )

    # Flexible bag for extra info
    # {"customer_ip": "103.x.x.x", "user_agent": "Mozilla/..."}
    metadata_ = Column(
        "metadata",   # actual column name in DB is "metadata"
        JSONB,
        nullable=True,
        default=dict
    )

    def __repr__(self):
        """
        How this object prints when you do print(transaction)
        Useful for debugging — you'll see something like:
        <Transaction id=a1b2... amount=45000 status=CREATED>
        """
        return (
            f"<Transaction id={self.id} "
            f"amount={self.amount} "
            f"status={self.status}>"
        )