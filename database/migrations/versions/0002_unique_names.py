"""unique names so the seed script can't create duplicates

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_cafe_tables_branch_name", "cafe_tables", ["branch_id", "name"]
    )
    op.create_unique_constraint(
        "uq_menu_items_branch_name", "menu_items", ["branch_id", "name"]
    )
    # NULLS NOT DISTINCT needs Postgres 15+ (we run 16)
    op.execute(
        """
        ALTER TABLE modifiers
        ADD CONSTRAINT uq_modifiers_group_name
        UNIQUE NULLS NOT DISTINCT (group_name, name)
        """
    )


def downgrade() -> None:
    op.drop_constraint("uq_modifiers_group_name", "modifiers", type_="unique")
    op.drop_constraint("uq_menu_items_branch_name", "menu_items", type_="unique")
    op.drop_constraint("uq_cafe_tables_branch_name", "cafe_tables", type_="unique")
