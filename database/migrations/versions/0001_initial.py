"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-21
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # btree_gist lets an EXCLUDE constraint mix "=" on ints with "&&" on time ranges.
    # pg_trgm is for fuzzy menu search later.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "cafe_tables",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("branch_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("seats", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )

    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("branch_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("call_id", sa.String(64)),
        sa.Column("table_id", sa.Integer, sa.ForeignKey("cafe_tables.id"), nullable=False),
        sa.Column("customer_name", sa.String(100)),
        sa.Column("phone", sa.String(20)),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("starts_at", TS, nullable=False),
        sa.Column("ends_at", TS, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("hold_expires_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("ends_at > starts_at", name="ck_reservation_time_order"),
        sa.CheckConstraint(
            "status IN ('held','confirmed','cancelled','expired')", name="ck_reservation_status"
        ),
    )
    op.create_index("ix_reservations_call_id", "reservations", ["call_id"])

    # THE double-booking rule: two active reservations on the same table can't overlap in time.
    op.execute(
        """
        ALTER TABLE reservations
        ADD CONSTRAINT no_double_booking
        EXCLUDE USING gist (
            table_id WITH =,
            tstzrange(starts_at, ends_at) WITH &&
        ) WHERE (status IN ('held', 'confirmed'))
        """
    )

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("phone", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(100)),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "addresses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id")),
        sa.Column("line1", sa.String(255), nullable=False),
        sa.Column("landmark", sa.String(255)),
        sa.Column("pincode", sa.String(10), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "delivery_pincodes",
        sa.Column("pincode", sa.String(10), primary_key=True),
        sa.Column("branch_id", sa.Integer, nullable=False, server_default="1"),
    )

    op.create_table(
        "menu_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("branch_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("is_veg", sa.Boolean, nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("aliases", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("is_available", sa.Boolean, nullable=False, server_default="true"),
    )

    op.create_table(
        "modifiers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("group_name", sa.String(30)),
        sa.Column("extra_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
    )

    op.create_table(
        "menu_item_modifiers",
        sa.Column("menu_item_id", sa.Integer, sa.ForeignKey("menu_items.id"), primary_key=True),
        sa.Column("modifier_id", sa.Integer, sa.ForeignKey("modifiers.id"), primary_key=True),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("branch_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("call_id", sa.String(64)),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id")),
        sa.Column("address_id", sa.Integer, sa.ForeignKey("addresses.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("delivery_fee", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("confirmed_at", TS),
        sa.CheckConstraint(
            "status IN ('draft','confirmed','cancelled')", name="ck_order_status"
        ),
    )
    op.create_index("ix_orders_call_id", "orders", ["call_id"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "order_id", sa.Integer, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("menu_item_id", sa.Integer, sa.ForeignKey("menu_items.id")),
        sa.Column("item_name", sa.String(100), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("line_total", sa.Numeric(10, 2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_item_qty"),
    )

    op.create_table(
        "order_item_modifiers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "order_item_id",
            sa.Integer,
            sa.ForeignKey("order_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("modifier_id", sa.Integer, sa.ForeignKey("modifiers.id")),
        sa.Column("modifier_name", sa.String(50), nullable=False),
        sa.Column("extra_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    for table in (
        "order_item_modifiers",
        "order_items",
        "orders",
        "menu_item_modifiers",
        "modifiers",
        "menu_items",
        "delivery_pincodes",
        "addresses",
        "customers",
        "reservations",
        "cafe_tables",
    ):
        op.drop_table(table)
