"""
SQLAlchemy models for the cafe.

Rules that live in the database itself (see migrations/versions/0001_initial.py):
  * no two 'held' or 'confirmed' reservations may overlap on the same table
    (EXCLUDE constraint, needs the btree_gist extension)

Rules the TOOLS must enforce (the database cannot):
  * expired holds: hold_slot marks old holds 'expired' before inserting, and
    confirm_reservation checks status == 'held' and hold_expires_at > now()
  * one modifier per group (e.g. one spice level per item)
  * subtotal / total on orders are recomputed from the lines on every change
  * money is always Decimal, never float

Keep the CHECK / UNIQUE constraints below in sync with the migrations.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Reservation status values
RES_HELD = "held"
RES_CONFIRMED = "confirmed"
RES_CANCELLED = "cancelled"
RES_EXPIRED = "expired"

# Order status values
ORDER_DRAFT = "draft"
ORDER_CONFIRMED = "confirmed"
ORDER_CANCELLED = "cancelled"


class Base(DeclarativeBase):
    pass


class CafeTable(Base):
    __tablename__ = "cafe_tables"
    __table_args__ = (UniqueConstraint("branch_id", "name", name="uq_cafe_tables_branch_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    name: Mapped[str] = mapped_column(String(20))
    seats: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_reservation_time_order"),
        CheckConstraint(
            "status IN ('held','confirmed','cancelled','expired')", name="ck_reservation_status"
        ),
        # The no_double_booking EXCLUDE constraint exists only in the migration.
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    call_id: Mapped[str | None] = mapped_column(String(64), index=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("cafe_tables.id"))
    customer_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20))
    party_size: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default=RES_HELD)
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    table: Mapped[CafeTable] = relationship()


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    line1: Mapped[str] = mapped_column(String(255))
    landmark: Mapped[str | None] = mapped_column(String(255))
    pincode: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeliveryPincode(Base):
    """Pincodes inside the delivery area."""

    __tablename__ = "delivery_pincodes"

    pincode: Mapped[str] = mapped_column(String(10), primary_key=True)
    branch_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (UniqueConstraint("branch_id", "name", name="uq_menu_items_branch_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(30))  # indian / korean / continental / drinks
    is_veg: Mapped[bool] = mapped_column(Boolean)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    modifiers: Mapped[list["Modifier"]] = relationship(
        secondary="menu_item_modifiers", back_populates="items"
    )


class Modifier(Base):
    __tablename__ = "modifiers"
    __table_args__ = (
        # NULLS NOT DISTINCT so two ungrouped modifiers with the same name also clash
        UniqueConstraint(
            "group_name", "name", name="uq_modifiers_group_name", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))  # e.g. "hot", "no onion", "extra cheese"
    group_name: Mapped[str | None] = mapped_column(String(30))  # e.g. "spice"; one pick per group
    extra_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")

    items: Mapped[list[MenuItem]] = relationship(
        secondary="menu_item_modifiers", back_populates="modifiers"
    )


class MenuItemModifier(Base):
    """Which modifiers are allowed on which item."""

    __tablename__ = "menu_item_modifiers"

    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), primary_key=True)
    modifier_id: Mapped[int] = mapped_column(ForeignKey("modifiers.id"), primary_key=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("status IN ('draft','confirmed','cancelled')", name="ck_order_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    call_id: Mapped[str | None] = mapped_column(String(64), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    address_id: Mapped[int | None] = mapped_column(ForeignKey("addresses.id"))
    status: Mapped[str] = mapped_column(String(20), default=ORDER_DRAFT)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    """
    Name and price are copied here, so old orders never change when the menu changes.
    line_total = (unit_price + sum of modifier extra_price) * quantity
    """

    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_order_item_qty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    menu_item_id: Mapped[int | None] = mapped_column(ForeignKey("menu_items.id"))
    item_name: Mapped[str] = mapped_column(String(100))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quantity: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped[Order] = relationship(back_populates="items")
    modifiers: Mapped[list["OrderItemModifier"]] = relationship(
        back_populates="order_item", cascade="all, delete-orphan"
    )


class OrderItemModifier(Base):
    __tablename__ = "order_item_modifiers"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_item_id: Mapped[int] = mapped_column(ForeignKey("order_items.id", ondelete="CASCADE"))
    modifier_id: Mapped[int | None] = mapped_column(ForeignKey("modifiers.id"))
    modifier_name: Mapped[str] = mapped_column(String(50))
    extra_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, server_default="0")

    order_item: Mapped[OrderItem] = relationship(back_populates="modifiers")
